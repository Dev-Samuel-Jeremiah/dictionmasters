"""
Which EchoSpell levels a learner opens.

EchoSpell is written level by level, and the higher levels may not be
written yet: today the book stops at Level 7. Rather than show a Grade 8
pupil an empty page, a level with no EchoSpell of its own uses the nearest
level below it that has some, so Levels 8 to 12 all use Level 7 for now.
The day a real Level 8 is imported (published, with groups), Level 8
learners move onto it by themselves; nothing here needs changing.

    echospell_level("Level 9")       "Level 7" (or "Level 9" once it exists)
    accessible(user)                 the EchoSpell levels they may open, or None for all
    limit_to_levels / require_level  as in apps.accounts.access, for EchoSpell levels

Everything else about levels (assessments, words, modules) still follows
apps.accounts.access, untouched.
"""

from django.core.exceptions import PermissionDenied
from django.db.models import Q

from apps.accounts.access import LEVEL_ORDER, accessible_levels


def _written():
    """The levels that have EchoSpell of their own: published, with groups."""
    from .models import Level

    return set(Level.objects.filter(is_published=True, groups__isnull=False).values_list("name", flat=True))


def echospell_level(name, written=None):
    """The EchoSpell level that a learner on `name` uses."""
    written = _written() if written is None else written
    if name in written or name not in LEVEL_ORDER:
        return name
    below = [one for one in LEVEL_ORDER[: LEVEL_ORDER.index(name)] if one in written]
    return below[-1] if below else name


def accessible(user):
    """The EchoSpell levels this person may open, or None for every level."""
    levels = accessible_levels(user)
    if levels is None:
        return None
    written = _written()
    return sorted({echospell_level(one, written) for one in levels},
                  key=lambda v: LEVEL_ORDER.index(v) if v in LEVEL_ORDER else len(LEVEL_ORDER))


def limit_to_levels(queryset, user, field="level", allow_blank=True):
    """apps.accounts.access.limit_to_levels, for EchoSpell levels."""
    levels = accessible(user)
    if levels is None:
        return queryset
    condition = Q(**{f"{field}__in": levels})
    if allow_blank:
        condition |= Q(**{field: ""})
    return queryset.filter(condition)


def require_level(user, level_name):
    levels = accessible(user)
    if levels is not None and level_name and level_name not in levels:
        raise PermissionDenied("That belongs to another level.")
