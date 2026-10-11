"""
A school's stages and grades, and the content level each grade follows.

Schools are organised the Nigerian way: Pre-School, Primary, Junior
Secondary and Senior Secondary, each with its grades. The site's content
is organised by level (Pre-Level, Level 1 … Level 12: the EchoSpell book,
the scheme of work, age bands, billing), so every grade follows one level:

    Pre-School          Creche, Nursery 1, Nursery 2, Kindergarten   Pre-Level
    Primary             Primary 1 – Primary 6                        Level 1 – 6
    Junior Secondary    JSS 1 – JSS 3                                Level 7 – 9
    Senior Secondary    SSS 1 – SSS 3                                Level 10 – 12

School people see grades; individual learners keep levels.

    level_for(grade)        "primary_3" -> "Level 3"
    grade_for_level(level)  "Level 3" -> "primary_3"; Pre-Level -> Kindergarten
    next_grade(grade)       the grade a class moves up to, None after SSS 3
"""

from dataclasses import dataclass


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

GRADES = [
    Grade("creche", "Creche", "pre_school", "Pre-Level"),
    Grade("nursery_1", "Nursery 1", "pre_school", "Pre-Level"),
    Grade("nursery_2", "Nursery 2", "pre_school", "Pre-Level"),
    Grade("kindergarten", "Kindergarten", "pre_school", "Pre-Level"),
    *[Grade(f"primary_{n}", f"Primary {n}", "primary", f"Level {n}") for n in range(1, 7)],
    *[Grade(f"jss_{n}", f"JSS {n}", "junior_secondary", f"Level {n + 6}") for n in range(1, 4)],
    *[Grade(f"sss_{n}", f"SSS {n}", "senior_secondary", f"Level {n + 9}") for n in range(1, 4)],
]

BY_KEY = {grade.key: grade for grade in GRADES}
STAGE_LABELS = dict(STAGES)

# Grouped by stage, for a <select> with optgroups.
GRADE_CHOICES = [
    (label, [(grade.key, grade.label) for grade in GRADES if grade.stage == stage])
    for stage, label in STAGES
]

# The grade a student of a level is placed in when nothing else says
# which: the last Pre-School grade for Pre-Level, else the one grade.
_FOR_LEVEL = {}
for _grade in GRADES:
    _FOR_LEVEL[_grade.level] = _grade.key


def level_for(grade):
    """The content level a grade follows, or "" for an unknown grade."""
    found = BY_KEY.get(grade)
    return found.level if found else ""


def grade_for_level(level):
    """The grade a student of `level` goes into by default, or None."""
    return _FOR_LEVEL.get(level)


def label_for(grade):
    found = BY_KEY.get(grade)
    return found.label if found else ""


def next_grade(grade):
    """The grade after `grade` (Kindergarten -> Primary 1, Primary 6 ->
    JSS 1, JSS 3 -> SSS 1), or None after SSS 3 or for an unknown grade."""
    keys = [g.key for g in GRADES]
    if grade not in BY_KEY or grade == keys[-1]:
        return None
    return keys[keys.index(grade) + 1]


def label_for_level(level):
    """How a content level reads to school people: "Level 3" -> "Primary 3",
    "Level 8" -> "JSS 2", "Pre-Level" -> "Pre-School"; anything else as it is."""
    if level == "Pre-Level":
        return STAGE_LABELS["pre_school"]
    return label_for(grade_for_level(level)) or level


# A level dropdown worded in grades, for school forms whose value is still
# a level (the school registration form, the dashboard's level tools).
LEVEL_AS_GRADE_CHOICES = [(grade.level, label_for_level(grade.level))
                          for grade in GRADES if grade.stage != "pre_school" or grade.key == "kindergarten"]
