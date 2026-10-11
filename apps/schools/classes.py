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
