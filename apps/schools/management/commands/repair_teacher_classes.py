"""
Put teachers in the classes of every level they've been given.

Until November 2026, giving a teacher a second level (in the control room
or the admin site) gave them no class for it: their dashboard showed none
of that level's students, and the next change to their classes cut the
level off again. This puts every school teacher in a class of each level
they have but don't teach a class of yet (apps/schools/classes.py,
follow_levels). It never takes anyone out of a class.

    manage.py repair_teacher_classes            what it would do: changes nothing
    manage.py repair_teacher_classes --apply    do it

A level already cut off can't be told from one never given: give it again
in the control room, and the teacher's classes follow from now on.
"""

from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import User
from apps.schools import grades
from apps.schools.classes import class_ids_for, follow_levels
from apps.schools.models import SchoolClass


class Command(BaseCommand):
    help = "Put teachers in the classes of every level they've been given (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Make the changes (otherwise only report).")

    def handle(self, *args, **options):
        teachers = list(User.objects.filter(role=User.Role.TEACHER, is_active=True, school__isnull=False)
                        .select_related("school"))
        taught = class_ids_for(teachers)
        level_of = {pk: grades.level_for(grade) for pk, grade in
                    SchoolClass.objects.filter(pk__in={c for ids in taught.values() for c in ids})
                    .values_list("pk", "grade")}
        missing = {}
        for teacher in teachers:
            have = {level_of[c] for c in taught[teacher.pk]}
            lacking = [lvl for lvl in teacher.all_levels if grades.grade_for_level(lvl) and lvl not in have]
            if lacking:
                missing[teacher] = lacking

        per_school = Counter(teacher.school.name for teacher in missing)
        self.stdout.write(f"{len(teachers)} school teachers; {len(missing)} have a level with no class of it.")
        for school, count in per_school.most_common():
            self.stdout.write(f"  {school}: {count} teacher{'s' if count != 1 else ''}")
        if not options["apply"]:
            self.stdout.write("Nothing changed. Run again with --apply to put them in those classes.")
            return
        with transaction.atomic():
            fixed = sum(1 for teacher in missing if follow_levels(teacher, remove=False))
        self.stdout.write(self.style.SUCCESS(f"Done: {fixed} teacher{'s' if fixed != 1 else ''} put in their levels' classes."))
