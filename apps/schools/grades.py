"""
A school's stages and grades, and the content level each grade follows.

Schools are organised the Nigerian way: Pre-School, Primary, Junior
Secondary and Senior Secondary, each with its grades. The site's content
is organised by level (Pre-Level, Level 1 … Level 12: the EchoSpell book,
age bands, billing), so every grade follows one level.
By default:

    Pre-School          Creche, Nursery 1, Nursery 2, Kindergarten   Pre-Level
    Primary             Grade 1 – Grade 6                            Level 1 – 6
    Junior Secondary    Grade 7 – Grade 9                            Level 7 – 9
    Senior Secondary    Grade 10 – Grade 12                          Level 10 – 12

(The grades were called Primary 1-6, JSS 1-3 and SSS 1-3 at first;
OLD_NAMES still reads those, e.g. in a bulk-add spreadsheet.)

Staff can rename a grade and change the level it follows in the control
room (Classes & grades; GradeSetting). current() is the grades with those
changes applied, read from the database at most every CACHE_SECONDS per
process, and at once in the process that saved them (forget()). The grades
themselves — their keys, stages and order — are fixed here.

School people see grades; individual learners keep levels.

    current()               the grades as they are now, in order
    level_for(grade)        "primary_3" -> "Level 3"
    grade_for_level(level)  "Level 3" -> "primary_3"; Pre-Level -> Kindergarten
    label_for(grade)        "primary_3" -> "Grade 3"
    label_for_level(level)  "Level 3" -> "Grade 3", "Pre-Level" -> "Pre-School"
    next_grade(grade)       the grade a class moves up to, None after Grade 12
"""

import time
from dataclasses import dataclass, replace

from django.conf import settings


@dataclass(frozen=True)
class Grade:
    key: str
    label: str
    stage: str
    level: str


STAGES = [
    ("pre_school", "Pre-School"),
    ("primary", "Primary"),
    ("junior_secondary", "Junior Secondary"),
    ("senior_secondary", "Senior Secondary"),
]
STAGE_LABELS = dict(STAGES)

# The grades as the code ships them. Use current(), which has any changes.
DEFAULT_GRADES = [
    Grade("creche", "Creche", "pre_school", "Pre-Level"),
    Grade("nursery_1", "Nursery 1", "pre_school", "Pre-Level"),
    Grade("nursery_2", "Nursery 2", "pre_school", "Pre-Level"),
    Grade("kindergarten", "Kindergarten", "pre_school", "Pre-Level"),
    # Grade N follows Level N: Grade 1-6 are Primary, 7-9 Junior Secondary, 10-12 Senior Secondary.
    *[Grade(f"primary_{n}", f"Grade {n}", "primary", f"Level {n}") for n in range(1, 7)],
    *[Grade(f"jss_{n}", f"Grade {n + 6}", "junior_secondary", f"Level {n + 6}") for n in range(1, 4)],
    *[Grade(f"sss_{n}", f"Grade {n + 9}", "senior_secondary", f"Level {n + 9}") for n in range(1, 4)],
]
DEFAULTS = {grade.key: grade for grade in DEFAULT_GRADES}

# The names the grades had at first, still understood when typed (bulk add).
OLD_NAMES = {**{f"Primary {n}": f"primary_{n}" for n in range(1, 7)},
             **{f"JSS {n}": f"jss_{n}" for n in range(1, 4)},
             **{f"SSS {n}": f"sss_{n}" for n in range(1, 4)}}
KEYS = [grade.key for grade in DEFAULT_GRADES]

# For the model field: the keys never change; labels on pages come from current().
GRADE_CHOICES = [
    (label, [(grade.key, grade.label) for grade in DEFAULT_GRADES if grade.stage == stage])
    for stage, label in STAGES
]

# A long wait in tests, where saving forgets at once and nothing else saves.
CACHE_SECONDS = 10 ** 9 if getattr(settings, "TESTING", False) else 30
_cache = {"at": 0.0, "grades": None}


def forget():
    """Read the grades afresh next time (after a change, or in a test)."""
    _cache["grades"] = None


def current():
    """The grades with staff's changes (GradeSetting) applied, in order."""
    now = time.monotonic()
    if _cache["grades"] is None or now - _cache["at"] > CACHE_SECONDS:
        from django.db import DatabaseError

        try:
            from .models import GradeSetting

            changed = {row.grade: row for row in GradeSetting.objects.all()}
        except DatabaseError:            # before the table exists (migrating)
            changed = {}
        _cache["grades"] = [
            replace(grade, label=changed[grade.key].label or grade.label, level=changed[grade.key].level or grade.level)
            if grade.key in changed else grade
            for grade in DEFAULT_GRADES
        ]
        _cache["at"] = now
    return _cache["grades"]


def by_key():
    return {grade.key: grade for grade in current()}


def grade_choices():
    """Grades for a form's <select>, grouped by stage, with today's names."""
    return [(label, [(g.key, g.label) for g in current() if g.stage == stage]) for stage, label in STAGES]


def level_for(grade):
    """The content level a grade follows, or "" for an unknown grade."""
    found = by_key().get(grade)
    return found.level if found else ""


def grades_on(level):
    """The keys of the grades that follow `level`, in order."""
    return [g.key for g in current() if g.level == level]


def grade_for_level(level):
    """The grade a student of `level` goes into by default (the last grade
    on that level: Kindergarten for Pre-Level), or None."""
    keys = grades_on(level)
    return keys[-1] if keys else None


def label_for(grade):
    found = by_key().get(grade)
    return found.label if found else ""


def label_for_level(level):
    """How a content level reads to school people: "Level 3" -> "Grade 3",
    "Level 8" -> "Grade 8"; a level several grades follow reads as their
    stage when they make up the whole stage ("Pre-School"), else as its
    grades ("Nursery 2 and Kindergarten"); anything else as it is."""
    found = [g for g in current() if g.level == level]
    if not found:
        return level
    if len(found) == 1:
        return found[0].label
    stages = {g.stage for g in found}
    if len(stages) == 1 and len(found) == sum(1 for g in current() if g.stage in stages):
        return STAGE_LABELS[stages.pop()]
    return ", ".join(g.label for g in found[:-1]) + f" and {found[-1].label}"


def level_as_grade_choices():
    """A level dropdown worded in grades, for school forms whose value is
    still a level (the school registration form, the dashboard's tools)."""
    from apps.echospell.models import LEVEL_NAME_CHOICES

    return [(level, label_for_level(level)) for level, _label in LEVEL_NAME_CHOICES if grades_on(level)]


def next_grade(grade):
    """The grade after `grade` (Kindergarten -> Grade 1, Grade 6 ->
    Grade 7 ...), or None after Grade 12 or for an unknown grade."""
    if grade not in DEFAULTS or grade == KEYS[-1]:
        return None
    return KEYS[KEYS.index(grade) + 1]
