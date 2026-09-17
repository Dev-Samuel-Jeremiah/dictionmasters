"""
Who can see which level.

A school's teachers and students are given a level when they join, by
the code their school admin generated. From then on the site only shows
them that level's work: its EchoSpell groups and activities, its
assessments, its words.

Individual learners, school admins and platform staff have no level set,
and see everything.

Content with no level of its own — a placement test, a word that hasn't
been graded — belongs to everybody, so it is always shown.

Everything routes through here, so the rule is written once and the same
answer is given on every page.
"""

from django.core.exceptions import PermissionDenied
from django.db.models import Q

from apps.echospell.models import LEVEL_NAME_CHOICES

LEVEL_ORDER = [value for value, _label in LEVEL_NAME_CHOICES]

# A learner sees their own level only. Turn this on to let them look back
# over everything below their level as well.
INCLUDE_LOWER_LEVELS = False

SCOPED_ROLES = {"teacher", "student"}


def accessible_levels(user):
    """The levels this person may open, or None for every level."""
    if not getattr(user, "is_authenticated", False):
        return None
    if user.is_staff or user.role not in SCOPED_ROLES:
        return None
    level = (user.level or "").strip()
    if not level:
        # A school account without a level yet: show everything rather
        # than lock them out of the whole site.
        return None
    if INCLUDE_LOWER_LEVELS and level in LEVEL_ORDER:
        return LEVEL_ORDER[: LEVEL_ORDER.index(level) + 1]
    return [level]


def is_level_scoped(user):
    return accessible_levels(user) is not None


def can_see_level(user, level_name):
    """Is this level (a name like "Level 3", or blank) open to them?"""
    levels = accessible_levels(user)
    if levels is None or not level_name:
        return True
    return level_name in levels


def require_level(user, level_name):
    if not can_see_level(user, level_name):
        raise PermissionDenied("That belongs to another level.")


def limit_to_levels(queryset, user, field="level", allow_blank=True):
    """Narrow a queryset to the levels this person may see.

    `field` is the path to the level name, e.g. "level" on a word or
    "level__name" on an EchoSpell group. Rows with no level are kept
    when `allow_blank`, since they belong to everyone.
    """
    levels = accessible_levels(user)
    if levels is None:
        return queryset
    condition = Q(**{f"{field}__in": levels})
    if allow_blank:
        condition |= Q(**{field: ""})
    return queryset.filter(condition)
