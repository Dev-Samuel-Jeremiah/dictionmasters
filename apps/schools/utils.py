"""Short, human-typeable codes for schools and for the access codes a
school hands to a teacher or student.

Ambiguous characters (0/O, 1/I) are left out so a code copied onto a
slip of paper and typed back in by a child is less likely to fail.
"""

import random

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _random_code(length):
    return "".join(random.choice(ALPHABET) for _ in range(length))


def generate_school_code(model, field="code", length=6, prefix="DM-"):
    while True:
        candidate = f"{prefix}{_random_code(length)}"
        if not model.objects.filter(**{field: candidate}).exists():
            return candidate


def generate_access_code(model, field="code", length=8):
    while True:
        candidate = _random_code(length)
        if not model.objects.filter(**{field: candidate}).exists():
            return candidate
