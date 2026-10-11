"""
Keeping every school student in a class, and teachers to their classes.

A student's level still decides what they can open (apps/accounts/access.py),
so the level leads and the class follows it: whenever a school student's
level is set or changed — joining with a code, bulk add, the control room —
they are placed in a class of the matching grade at their school
(apps/schools/grades.py), in the school's year. An existing class of a grade
on that level is used when there is one, else one is made (e.g. "Primary 3"),
which the school can rename or split later.

A school's year is the newest school year it has classes in (or the
calendar's newest, before it has any). It moves on only when the school
moves its classes up (promote, below), not the moment the next year is
added to the calendar.

    place(user)              for User.save: set user.school_class
    place_many(users)        the same for many saved users at once, batched
    school_year(school)      the year the school's classes are in now
    this_year(school)        its classes in that year, Creche first
    move(admin, students, c) students into class c (their level follows)
    pupils_of_teacher(t)     the students in the classes a teacher teaches
    sync_teachers(ids)       teachers' levels from their classes
    promote(admin, school, students)   the end of the year: see below
    undo(admin, batch)       puts a move or promotion back exactly
"""

import uuid

from django.db import transaction
from django.utils import timezone

from . import grades


def current_session():
    """The newest school year in the calendar, or None before there is one."""
    from apps.scheme.models import Session

    return Session.objects.order_by("-name").first()


def school_year(school):
    """The school year a school's classes are in now (a school or its id):
    the newest one it has classes in, else the calendar's newest."""
    from apps.scheme.models import Session

    school_id = getattr(school, "pk", school)
    return (Session.objects.filter(classes__school_id=school_id).order_by("-name").first()
            or current_session())


def next_year(school):
    """The school year after the school's, if the calendar has it."""
    from apps.scheme.models import Session

    now = school_year(school)
    later = Session.objects.order_by("name")
    return (later.filter(name__gt=now.name) if now else later.none()).first()


def _wants_class(user):
    return user.role == "student" and user.school_id and grades.grade_for_level(user.level)


def _school_student(user):
    return user.role == "student" and user.school_id


def _fits(found, user):
    """Is this class (school_id, grade) right for the user's school and level?"""
    school_id, grade = found
    return school_id == user.school_id and grades.level_for(grade) == user.level


def _class_for(school_id, level, session, made):
    """The school's class for `level` in `session`, made if there's none.
    `made` caches answers by (school, level) for a batch."""
    from .models import SchoolClass

    key = (school_id, level)
    if key not in made:
        keys = grades.grades_on(level)
        found = (SchoolClass.objects.filter(school_id=school_id, session=session, grade__in=keys)
                 .order_by("grade", "name", "pk").first())
        made[key] = found or SchoolClass.objects.create(
            school_id=school_id, session=session, grade=grades.grade_for_level(level))
    return made[key]


def place(user):
    """Point user.school_class at the right class (or at none, for anyone
    who isn't a school student with a level). Doesn't save. True when it
    changed."""
    if not _school_student(user):
        if user.school_class_id is None:
            return False
        user.school_class = None
        return True
    if not grades.grade_for_level(user.level):
        return False                 # a level no grade follows (any more): they keep their class
    if user.school_class_id:
        cached = user._state.fields_cache.get("school_class")
        if cached is not None:
            current = (cached.school_id, cached.grade)
        else:
            from .models import SchoolClass

            current = SchoolClass.objects.filter(pk=user.school_class_id).values_list("school_id", "grade").first()
        if current and _fits(current, user):
            return False
    user.school_class = _class_for(user.school_id, user.level, school_year(user.school_id), {})
    return True


def place_many(users):
    """place() for users already saved (e.g. by bulk_create), with a few
    queries for the whole batch rather than some per student."""
    from apps.accounts.models import User

    need = [u for u in users if _wants_class(u) and not u.school_class_id]
    if not need:
        return
    years, made = {}, {}
    for user in need:
        if user.school_id not in years:
            years[user.school_id] = school_year(user.school_id)
        user.school_class = _class_for(user.school_id, user.level, years[user.school_id], made)
    User.objects.bulk_update(need, ["school_class"], batch_size=200)


# ---------------------------------------------------------------------------
# A school's classes this year, for its pages and its sign-up form
# ---------------------------------------------------------------------------

GRADE_ORDER = {key: i for i, key in enumerate(grades.KEYS)}


def _sorted(found):
    return sorted(found, key=lambda c: (GRADE_ORDER.get(c.grade, 99), c.name.lower()))


def this_year(school):
    """The school's classes in its school year (school_year), Creche first,
    then by name."""
    from .models import SchoolClass

    session = school_year(school)
    found = SchoolClass.objects.filter(school=school, session=session) if session else \
        SchoolClass.objects.filter(school=school, session__isnull=True)
    return _sorted(found.select_related("class_teacher"))


def class_of_grade(school, grade, name="", session=None):
    """The school's class of this grade and name this year, made if needed."""
    from .models import SchoolClass

    session = session or school_year(school)
    return SchoolClass.objects.get_or_create(school=school, session=session, grade=grade, name=name)[0]


def join_choices(school):
    """The "Your class" choices on the sign-up form, grouped by stage: the
    school's classes, and each grade with no class yet, so a student can
    always find theirs. Values are "class:<pk>" or "grade:<key>". With no
    school yet, every grade."""
    classes = this_year(school) if school else []
    has_class = {c.grade for c in classes}
    groups = []
    for stage, label in grades.STAGES:
        options = []
        for grade in (g for g in grades.current() if g.stage == stage):
            if grade.key in has_class:
                options += [(f"class:{c.pk}", c.display_name) for c in classes if c.grade == grade.key]
            else:
                options.append((f"grade:{grade.key}", grade.label))
        groups.append((label, options))
    return groups


def chosen_class(school, value):
    """The class a "class:<pk>" or "grade:<key>" choice means at this school
    (a grade's class is made if needed), or None if it isn't one of the
    school's."""
    from .models import SchoolClass

    kind, _sep, ref = str(value or "").partition(":")
    if kind == "class" and ref.isdigit():
        return SchoolClass.objects.filter(school=school, pk=int(ref)).first()
    if kind == "grade" and ref in grades.DEFAULTS:
        return class_of_grade(school, ref)
    return None


# ---------------------------------------------------------------------------
# Moving students, and undoing it
# ---------------------------------------------------------------------------

def _log(admin, school, batch, kind, student, to_class):
    """Write the change to the school's level history before making it."""
    from .models import LevelChange

    LevelChange.objects.create(
        school=school, member=student, changed_by=admin, batch=batch, kind=kind,
        old_level=student.level, old_additional=student.additional_levels,
        new_level=to_class.level if to_class else student.level, new_additional="",
        old_class_id=student.school_class_id, new_class=to_class,
    )


def _put(student, to_class):
    student.school_class, student.level, student.additional_levels = to_class, to_class.level, ""
    student.save(update_fields=["school_class", "level", "additional_levels"])


def move(admin, students, school_class):
    """Put these students in `school_class`, taking them to its grade's
    level, and log it in the school's level history. The number moved."""
    batch, moved = uuid.uuid4().hex, 0
    with transaction.atomic():
        for student in students:
            if student.school_class_id == school_class.pk or student.school_id != school_class.school_id:
                continue
            _log(admin, school_class.school, batch, "move", student, school_class)
            _put(student, school_class)
            moved += 1
    return moved


@transaction.atomic
def undo(admin, batch):
    """Put a whole batch of class changes back: each student to the class
    and level they had, and graduates back on the school. Anyone changed
    again since is skipped. (put back, skipped)."""
    from .models import LevelChange

    changes = list(LevelChange.objects.select_for_update()
                   .filter(school=admin.school, batch=batch, undone_at__isnull=True).select_related("member"))
    restored, skipped = [], []
    for change in changes:
        member = change.member
        if change.kind == "graduate":
            if member.is_active or member.school_class_id != change.old_class_id:
                skipped.append(member)
                continue
            member.is_active = True
            member.save(update_fields=["is_active"])
        else:
            if member.school_class_id != change.new_class_id or member.level != change.new_level:
                skipped.append(member)
                continue
            member.school_class_id, member.level = change.old_class_id, change.old_level
            member.additional_levels = change.old_additional
            member.save(update_fields=["school_class", "level", "additional_levels"])
        restored.append(member)
    LevelChange.objects.filter(pk__in=[c.pk for c in changes]).update(undone_at=timezone.now())
    return restored, skipped


# ---------------------------------------------------------------------------
# The end of the year
# ---------------------------------------------------------------------------

class Promotion:
    def __init__(self):
        self.batch = uuid.uuid4().hex
        self.promoted, self.stayed, self.graduated = [], [], []
        self.year = None                 # the new school year, when the classes moved into one


@transaction.atomic
def promote(admin, school, chosen):
    """Move the school up a grade. Students in `chosen` go to the next
    grade's class with the same name (Primary 3 Gold -> Primary 4 Gold);
    SSS 3 students in it graduate (taken off the school, as if removed,
    and can be restored). Everyone else stays in their grade.

    When the calendar has the school's next year, the whole school moves
    into it: each class is carried over with its teachers (teachers stay
    with their grade), the students go into the new year's classes, and
    the school's year moves on. Otherwise the moves are within this year.
    Everything is logged, so undo() puts it all back."""
    from apps.accounts.models import User

    from .models import SchoolClass

    outcome = Promotion()
    now, later = this_year(school), next_year(school)
    outcome.year = later
    session = later or school_year(school)
    chosen_ids = {getattr(s, "pk", s) for s in chosen}
    made = {}

    def target(grade, name, like=None):
        """The class of `grade` and `name` in the year being moved into,
        carried over from `like` (its teachers) when it's new."""
        key = (grade, name)
        if key not in made:
            found, created = SchoolClass.objects.get_or_create(school=school, session=session, grade=grade, name=name)
            if created and like is not None:
                found.class_teacher = like.class_teacher
                found.save(update_fields=["class_teacher"])
                found.teachers.set(like.teachers.all())
            made[key] = found
        return made[key]

    if later:
        for found in now:                   # every class goes on into the new year, teachers and all
            target(found.grade, found.name, like=found)
    teachers_of = {(c.grade, c.name): c for c in now}
    students = list(User.objects.filter(school=school, role=User.Role.STUDENT, is_active=True,
                                        school_class__in=now).select_related("school_class"))
    for student in students:
        here = student.school_class
        up = grades.next_grade(here.grade) if student.pk in chosen_ids else here.grade
        if student.pk in chosen_ids and up is None:            # SSS 3: graduated
            _log(admin, school, outcome.batch, "graduate", student, None)
            student.is_active = False
            student.save(update_fields=["is_active"])
            student.device_logins.all().delete()
            outcome.graduated.append(student)
            continue
        to = target(up, here.name, like=teachers_of.get((up, here.name)))
        if to.pk == here.pk:
            outcome.stayed.append(student)
            continue
        _log(admin, school, outcome.batch, "promote" if up != here.grade else "move", student, to)
        _put(student, to)
        (outcome.promoted if up != here.grade else outcome.stayed).append(student)
    sync_teachers([t.pk for c in made.values() for t in c.teachers.all()])
    return outcome


# ---------------------------------------------------------------------------
# Teachers
# ---------------------------------------------------------------------------

def classes_taught(teacher):
    """The classes a teacher teaches in their school's year."""
    from .models import SchoolClass

    return SchoolClass.objects.filter(teachers=teacher, school_id=teacher.school_id,
                                      session=school_year(teacher.school_id))


def this_year_of(teacher):
    """classes_taught, in grade order: for the teacher's own pages."""
    return _sorted(classes_taught(teacher))


def pupils_of_teacher(teacher):
    """The active students in the classes a teacher teaches this year."""
    from apps.accounts.models import User

    return User.objects.filter(role=User.Role.STUDENT, is_active=True, school_id=teacher.school_id,
                               school_class__in=classes_taught(teacher).values("pk"))


def class_ids_for(teachers):
    """{teacher id: set of class ids} for many teachers at once, this year."""
    from .models import SchoolClass

    teachers = list(teachers)
    out = {t.pk: set() for t in teachers}
    years = {}
    for teacher in teachers:
        if teacher.school_id and teacher.school_id not in years:
            years[teacher.school_id] = school_year(teacher.school_id)
    rows = SchoolClass.teachers.through.objects.filter(user_id__in=out).values_list(
        "user_id", "schoolclass_id", "schoolclass__school_id", "schoolclass__session_id")
    for user_id, class_id, school_id, session_id in rows:
        year = years.get(school_id)
        if session_id == (year.pk if year else None):
            out[user_id].add(class_id)
    return out


def join_level_classes(teacher):
    """A new teacher starts in the classes of the level(s) they chose (a
    class is made for a level that has none), like the teachers already
    there when classes began. The school admin changes it on Classes."""
    from .models import SchoolClass

    if not (teacher.role == "teacher" and teacher.school_id):
        return
    session = school_year(teacher.school_id)
    for level in teacher.all_levels:
        if not grades.grade_for_level(level):
            continue
        keys = grades.grades_on(level)
        found = list(SchoolClass.objects.filter(school_id=teacher.school_id, session=session, grade__in=keys))
        if not found:
            found = [SchoolClass.objects.create(school_id=teacher.school_id, session=session,
                                                grade=grades.grade_for_level(level))]
        for school_class in found:
            school_class.teachers.add(teacher)


def sync_teachers(teacher_ids):
    """Each teacher's levels from the classes they teach this year (main
    level the youngest class's, the rest as extra levels), so what they can
    open matches their classes. A teacher with no class keeps their levels."""
    from apps.accounts.models import User

    from .models import SchoolClass

    teachers = list(User.objects.filter(pk__in=set(teacher_ids), role=User.Role.TEACHER))
    taught = class_ids_for(teachers)
    grade_of = dict(SchoolClass.objects.filter(pk__in={c for ids in taught.values() for c in ids})
                    .values_list("pk", "grade"))
    changed = []
    for teacher in teachers:
        levels = sorted({grades.level_for(grade_of[c]) for c in taught[teacher.pk]},
                        key=lambda lvl: grades.KEYS.index(grades.grades_on(lvl)[0]))
        if not levels:
            continue
        extra = f",{','.join(levels[1:])}," if levels[1:] else ""
        if (teacher.level, teacher.additional_levels) != (levels[0], extra):
            teacher.level, teacher.additional_levels = levels[0], extra
            changed.append(teacher)
    User.objects.bulk_update(changed, ["level", "additional_levels"])


# ---------------------------------------------------------------------------
# Changing a grade (the control room's Classes & grades)
# ---------------------------------------------------------------------------

@transaction.atomic
def change_grade(key, label, level):
    """Rename grade `key` and set the content level it follows. Back to the
    code's own name and level, the change is simply removed. When the level
    changes, every student in a class of the grade moves to it at once (and
    their teachers' levels follow). The number of students moved."""
    from apps.accounts.models import User

    from .models import GradeSetting, SchoolClass

    before = grades.level_for(key)
    default = grades.DEFAULTS[key]
    if (label, level) == (default.label, default.level):
        GradeSetting.objects.filter(grade=key).delete()
    else:
        GradeSetting.objects.update_or_create(grade=key, defaults={"label": label, "level": level})
    grades.forget()
    if level == before:
        return 0
    moved = User.objects.filter(role=User.Role.STUDENT, school_class__grade=key).update(level=level)
    sync_teachers(SchoolClass.teachers.through.objects.filter(schoolclass__grade=key).values_list("user_id", flat=True))
    return moved
