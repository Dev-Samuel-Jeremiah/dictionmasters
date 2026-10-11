"""
Keeping every school student in a class.

A student's level still decides what they can open (apps/accounts/access.py),
so the level leads and the class follows it: whenever a school student's
level is set or changed — joining with a code, bulk add, a promotion, the
control room — they are placed in a class of the matching grade at their
school (apps/schools/grades.py), in the newest school year. An existing
class of a grade on that level is used when there is one, else one is made
(e.g. "Primary 3"), which the school can rename or split later.

    place(user)          for User.save: set user.school_class, True if changed
    place_many(users)    the same for many saved users at once, batched
    current_session()    the school year new classes belong to
"""

from . import grades


def current_session():
    """The newest school year in the calendar, or None before there is one."""
    from apps.scheme.models import Session

    return Session.objects.order_by("-name").first()


def _wants_class(user):
    return user.role == "student" and user.school_id and grades.grade_for_level(user.level)


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
        keys = [g.key for g in grades.GRADES if g.level == level]
        found = (SchoolClass.objects.filter(school_id=school_id, session=session, grade__in=keys)
                 .order_by("grade", "name", "pk").first())
        made[key] = found or SchoolClass.objects.create(
            school_id=school_id, session=session, grade=grades.grade_for_level(level))
    return made[key]


def place(user):
    """Point user.school_class at the right class (or at none, for anyone
    who isn't a school student with a level). Doesn't save. True when it
    changed."""
    if not _wants_class(user):
        if user.school_class_id is None:
            return False
        user.school_class = None
        return True
    if user.school_class_id:
        cached = user._state.fields_cache.get("school_class")
        if cached is not None:
            current = (cached.school_id, cached.grade)
        else:
            from .models import SchoolClass

            current = SchoolClass.objects.filter(pk=user.school_class_id).values_list("school_id", "grade").first()
        if current and _fits(current, user):
            return False
    user.school_class = _class_for(user.school_id, user.level, current_session(), {})
    return True


def place_many(users):
    """place() for users already saved (e.g. by bulk_create), with a few
    queries for the whole batch rather than some per student."""
    from apps.accounts.models import User

    need = [u for u in users if _wants_class(u) and not u.school_class_id]
    if not need:
        return
    session, made = current_session(), {}
    for user in need:
        user.school_class = _class_for(user.school_id, user.level, session, made)
    User.objects.bulk_update(need, ["school_class"], batch_size=200)


# ---------------------------------------------------------------------------
# A school's classes this year, for its pages and its sign-up form
# ---------------------------------------------------------------------------

GRADE_ORDER = {grade.key: i for i, grade in enumerate(grades.GRADES)}


def this_year(school):
    """The school's classes in the current school year (and any made before
    there was a calendar), Creche first, then by name."""
    from .models import SchoolClass

    session = current_session()
    found = SchoolClass.objects.filter(school=school, session=session) if session else \
        SchoolClass.objects.filter(school=school, session__isnull=True)
    return sorted(found.select_related("class_teacher"), key=lambda c: (GRADE_ORDER.get(c.grade, 99), c.name.lower()))


def class_of_grade(school, grade, name="", session=None):
    """The school's class of this grade and name this year, made if needed."""
    from .models import SchoolClass

    session = session or current_session()
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
        for grade in (g for g in grades.GRADES if g.stage == stage):
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
    if kind == "grade" and ref in grades.BY_KEY:
        return class_of_grade(school, ref)
    return None


def move(admin, students, school_class):
    """Put these students in `school_class`, taking them to its grade's
    level. Level changes go in the school's level history like any other
    move (apps/schools/levels.py). The number moved."""
    import uuid

    from django.db import transaction

    from .models import LevelChange

    batch, moved = uuid.uuid4().hex, 0
    with transaction.atomic():
        for student in students:
            if student.school_class_id == school_class.pk or student.school_id != school_class.school_id:
                continue
            if student.level != school_class.level:
                LevelChange.objects.create(
                    school=school_class.school, member=student, changed_by=admin, batch=batch, kind="move",
                    old_level=student.level, old_additional=student.additional_levels,
                    new_level=school_class.level, new_additional="",
                )
            student.school_class, student.level, student.additional_levels = school_class, school_class.level, ""
            student.save(update_fields=["school_class", "level", "additional_levels"])
            moved += 1
    return moved
