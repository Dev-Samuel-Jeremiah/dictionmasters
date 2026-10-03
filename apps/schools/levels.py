"""
A school admin moving their teachers and students between levels.

    move(admin, members, level)       everyone to `level` (a teacher keeps any
                                      other levels they also teach)
    set_levels(admin, member, levels) one person's exact levels: one for a
                                      student, one or more for a teacher
    promote(admin, students)          each student up one level: Pre-Level to
                                      Level 1, Level 3 to Level 4 ...; anyone
                                      already at the top level, or with no
                                      level yet, stays where they are
    undo(admin, batch)                puts a whole change back as it was

Every change is written to LevelChange, grouped by batch, so the dashboard
can list what was done and undo it. Undo only touches people whose levels
haven't been changed again since, so it never overwrites a later decision.
A level decides what someone can open (apps/accounts/access.py), so the
change takes effect on their very next page.
"""

import uuid
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.echospell.models import LEVEL_NAME_CHOICES

from .models import LevelChange

LEVELS = [value for value, _label in LEVEL_NAME_CHOICES]
TOP = LEVELS[-1]


def next_level(level):
    """The level after `level`, or None at the top (or for no level)."""
    if level not in LEVELS or level == TOP:
        return None
    return LEVELS[LEVELS.index(level) + 1]


def _sorted(levels):
    return sorted(dict.fromkeys(levels), key=LEVELS.index)


def _pack(extra):
    return f",{','.join(extra)}," if extra else ""


@dataclass
class Outcome:
    batch: str = ""
    changed: list = field(default_factory=list)       # (member, old display, new display)
    at_top: list = field(default_factory=list)
    no_level: list = field(default_factory=list)
    unchanged: list = field(default_factory=list)


def _apply(admin, outcome, kind, member, level, additional):
    """Give `member` these levels and log it, if that's a change."""
    if member.level == level and member.additional_levels == additional:
        outcome.unchanged.append(member)
        return
    before = member.level_display
    LevelChange.objects.create(
        school=admin.school, member=member, changed_by=admin, batch=outcome.batch, kind=kind,
        old_level=member.level, old_additional=member.additional_levels,
        new_level=level, new_additional=additional,
    )
    member.level, member.additional_levels = level, additional
    member.save(update_fields=["level", "additional_levels"])
    outcome.changed.append((member, before or "No level", member.level_display))


def _new_outcome():
    return Outcome(batch=uuid.uuid4().hex)


@transaction.atomic
def move(admin, members, level):
    if level not in LEVELS:
        raise ValueError("Choose a level.")
    outcome = _new_outcome()
    for member in members:
        extra = [lvl for lvl in member.additional_levels_list if lvl != level] if member.role == User.Role.TEACHER else []
        _apply(admin, outcome, "move", member, level, _pack(_sorted(extra)))
    return outcome


@transaction.atomic
def set_levels(admin, member, levels):
    levels = [lvl for lvl in levels if lvl in LEVELS]
    if not levels:
        raise ValueError("Choose at least one level.")
    levels = _sorted(levels)
    if member.role != User.Role.TEACHER:
        levels = levels[:1]           # a student is in one level
    outcome = _new_outcome()
    # A teacher's main level stays their main one if they still teach it.
    main = member.level if member.level in levels else levels[0]
    _apply(admin, outcome, "move", member, main, _pack([lvl for lvl in levels if lvl != main]))
    return outcome


@transaction.atomic
def promote(admin, students):
    outcome = _new_outcome()
    for student in students:
        if not student.level:
            outcome.no_level.append(student)
            continue
        after = next_level(student.level)
        if after is None:
            outcome.at_top.append(student)
            continue
        _apply(admin, outcome, "promote", student, after, "")
    return outcome


def batches(school, limit=8):
    """The latest changes, grouped: [{batch, kind, when, by, rows, can_undo, undone}]."""
    recent = list(LevelChange.objects.filter(school=school).select_related("member", "changed_by")[:400])
    groups = {}
    for change in recent:
        group = groups.setdefault(change.batch, {"batch": change.batch, "kind": change.get_kind_display(),
                                                  "when": change.created_at, "by": change.changed_by,
                                                  "rows": [], "undone": change.undone_at is not None})
        group["rows"].append(change)
    out = list(groups.values())[:limit]
    for group in out:
        group["count"] = len(group["rows"])
        moves = {}
        for change in group["rows"]:
            key = (change.old_level or "No level", change.new_level or "No level")
            moves[key] = moves.get(key, 0) + 1
        group["moves"] = sorted(moves.items(), key=lambda item: -item[1])
        group["can_undo"] = not group["undone"]
    return out


@transaction.atomic
def undo(admin, batch):
    """(put back, skipped): skipped are people changed again since."""
    changes = list(LevelChange.objects.select_for_update().filter(school=admin.school, batch=batch, undone_at__isnull=True)
                   .select_related("member"))
    restored, skipped = [], []
    for change in changes:
        member = change.member
        if member.level != change.new_level or member.additional_levels != change.new_additional:
            skipped.append(member)
            continue
        member.level, member.additional_levels = change.old_level, change.old_additional
        member.save(update_fields=["level", "additional_levels"])
        restored.append(member)
    LevelChange.objects.filter(pk__in=[c.pk for c in changes]).update(undone_at=timezone.now())
    return restored, skipped
