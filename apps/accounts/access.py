"""
Who can see which level.

A school's teachers and students are given a level when they join, by
the code their school admin generated. From then on the site only shows
them that level's work: its EchoSpell groups and activities, its
assessments, its words.

A teacher who covers more than one level — Level 1, Level 3 and Level 6,
say — can be given the rest from the control room (User.additional_levels,
apps/manage/level_field.py); everything below reads User.all_levels
rather than the single `level` field, so a teacher given several levels
this way can open all of them.

Individual learners, school admins and platform staff have no level set,
and see everything.

Content with no level of its own — a placement test, a word that hasn't
been graded — belongs to everybody, so it is always shown.

Content made for several levels — a learning module, a reading book, a
library item — keeps them as ",Level 1,Level 2," (blank for everyone),
narrowed by limit_to_level_list. A whole tool can be kept for some
levels too (learning_tools.ToolLevels, set in the control room):
can_use_tool. That one applies to students only; a teacher must be able
to open any tool to teach it.

Students also fall into an age band (age_band) — Little ones, Middle,
Older — which decides how much their home and Learn page show.

A teacher's class is the same rule turned round: the active students at
their school in a level they teach (pupils_of, teaches). A teacher with
no level yet teaches the whole school's students.

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
    levels = user.all_levels
    if not levels:
        # A school account without a level yet: show everything rather
        # than lock them out of the whole site.
        return None
    if INCLUDE_LOWER_LEVELS:
        # Each level's own levels-and-below, all together — a teacher
        # given Level 1 and Level 6 this way can also open Level 2-5.
        expanded = set()
        for one in levels:
            expanded.update(LEVEL_ORDER[: LEVEL_ORDER.index(one) + 1] if one in LEVEL_ORDER else [one])
        return sorted(expanded, key=lambda v: LEVEL_ORDER.index(v) if v in LEVEL_ORDER else len(LEVEL_ORDER))
    return levels


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


def in_level(queryset, level_name):
    """Of a queryset of accounts, only those whose main level or one of
    their extra levels is this one — so a teacher given several levels
    from the control room shows up under each of them, not just their
    main one. For the control room's Schools & people page."""
    return queryset.filter(Q(level=level_name) | Q(additional_levels__contains=f",{level_name},"))


def pupils_of(teacher):
    """The students a teacher teaches: active students at their school in
    one of their levels. Nobody, for anyone who isn't a school teacher."""
    from apps.accounts.models import User

    if not (getattr(teacher, "is_authenticated", False) and teacher.is_teacher and teacher.school_id):
        return User.objects.none()
    pupils = User.objects.filter(school_id=teacher.school_id, role=User.Role.STUDENT, is_active=True)
    levels = accessible_levels(teacher)
    return pupils if levels is None else pupils.filter(level__in=levels)


def teaches(teacher, pupil):
    """Is this student one of the teacher's pupils?"""
    return pupils_of(teacher).filter(pk=pupil.pk).exists()


def is_pupil_of(teacher, pupil):
    """pupils_of's rule for two accounts already in hand, with no query —
    for matching many teachers to many pupils at once (the weekly
    "Needs help" email). Keep the two in step."""
    if not (teacher.is_teacher and teacher.school_id and pupil.is_student and pupil.is_active):
        return False
    if pupil.school_id != teacher.school_id:
        return False
    levels = accessible_levels(teacher)
    return levels is None or pupil.level in levels


# ---------------------------------------------------------------------------
# Content for several levels, whole tools, and age bands
# ---------------------------------------------------------------------------

def pack_levels(levels):
    """Levels as stored on content: ",Level 1,Level 3," in the site's own
    order, or "" for everyone."""
    chosen = sorted(set(levels), key=lambda v: LEVEL_ORDER.index(v) if v in LEVEL_ORDER else len(LEVEL_ORDER))
    return ("," + ",".join(chosen) + ",") if chosen else ""


def unpack_levels(stored):
    return [lvl for lvl in (stored or "").split(",") if lvl]


def limit_to_level_list(queryset, user, field="levels"):
    """Narrow content made for several levels to the ones this person may
    see. Content with no levels ticked belongs to everyone."""
    levels = accessible_levels(user)
    if levels is None:
        return queryset
    condition = Q(**{field: ""})
    for level in levels:
        # The commas either side stop "Level 1" matching inside "Level 12".
        condition |= Q(**{f"{field}__contains": f",{level},"})
    return queryset.filter(condition)


def tool_levels():
    """{tool url name: [levels]} for every tool kept for some levels only.
    One small query; a tool not listed is open to everyone."""
    from apps.learning_tools.models import ToolLevels

    return {row.tool: unpack_levels(row.levels) for row in ToolLevels.objects.exclude(levels="")}


def can_use_tool(user, tool, kept=None):
    """May this person open the tool (its url name, e.g. "clash:hub")?
    Only students are held back, and only by a tool that staff have kept
    for some levels. Pass `kept` (tool_levels()) when asking about many."""
    if not getattr(user, "is_authenticated", False) or user.is_staff or user.role != "student":
        return True
    kept = tool_levels() if kept is None else kept
    levels = kept.get(tool)
    if not levels or not user.level:
        return True
    return user.level in levels


BANDS = [
    {"key": "little", "label": "Little ones", "levels": LEVEL_ORDER[0:3]},   # Pre-Level – Level 2
    {"key": "middle", "label": "Middle", "levels": LEVEL_ORDER[3:7]},        # Level 3 – Level 6
    {"key": "older", "label": "Older", "levels": LEVEL_ORDER[7:]},           # Level 7 – Level 12
]


def age_band(user):
    """A student's age band, from their level, or None — for everyone
    else, and a student with no level yet, the pages stay as they are."""
    if not getattr(user, "is_authenticated", False) or user.role != "student" or not user.level:
        return None
    return next((band for band in BANDS if user.level in band["levels"]), None)
