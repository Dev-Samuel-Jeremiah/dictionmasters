"""Schools' classes (Phase A): the grades, every school student placed in a
class that follows their level, and the migration that placed the
students already on the site."""

import importlib

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.db.models import RestrictedError
from django.test import TestCase

from apps.scheme.models import Session

from . import grades, levels
from .classes import place_many
from .models import School, SchoolClass

User = get_user_model()


def person(email, **extra):
    return User.objects.create_user(email, "mango-river-47", first_name=email.split("@")[0].title(), **extra)


class GradeTests(TestCase):
    def test_every_grade_follows_a_level(self):
        self.assertEqual(len(grades.DEFAULT_GRADES), 16)
        self.assertEqual([g.label for g in grades.DEFAULT_GRADES if g.stage == "pre_school"],
                         ["Creche", "Nursery 1", "Nursery 2", "Kindergarten"])
        self.assertEqual({grades.level_for(g.key) for g in grades.DEFAULT_GRADES if g.stage == "pre_school"}, {"Pre-Level"})
        self.assertEqual(grades.level_for("primary_3"), "Level 3")
        self.assertEqual(grades.level_for("jss_1"), "Level 7")
        self.assertEqual(grades.level_for("sss_3"), "Level 12")
        self.assertEqual(grades.grade_for_level("Pre-Level"), "kindergarten")
        self.assertEqual(grades.grade_for_level("Level 9"), "jss_3")
        self.assertIsNone(grades.grade_for_level(""))

    def test_moving_up_crosses_the_stages(self):
        self.assertEqual(grades.next_grade("kindergarten"), "primary_1")
        self.assertEqual(grades.next_grade("primary_6"), "jss_1")
        self.assertEqual(grades.next_grade("jss_3"), "sss_1")
        self.assertIsNone(grades.next_grade("sss_3"))


class PlacementTests(TestCase):
    def setUp(self):
        self.session = Session.objects.create(name="2026/2027")
        self.school = School.objects.create(name="Unity", email="u@example.com")
        self.other = School.objects.create(name="Hope", email="h@example.com")

    def student(self, email, level="Level 3", school=None):
        return person(email, role="student", school=school or self.school, level=level)

    def test_a_new_student_goes_into_their_grades_class(self):
        ada = self.student("ada@example.com")
        self.assertEqual(ada.school_class.display_name, "Grade 3")
        self.assertEqual((ada.school_class.school, ada.school_class.session), (self.school, self.session))
        # A classmate shares it; another level, or another school, gets its own.
        self.assertEqual(self.student("bo@example.com").school_class, ada.school_class)
        self.assertEqual(self.student("cy@example.com", "Level 7").school_class.display_name, "Grade 7")
        self.assertNotEqual(self.student("di@example.com", school=self.other).school_class, ada.school_class)

    def test_an_existing_class_of_the_grade_is_used(self):
        gold = SchoolClass.objects.create(school=self.school, session=self.session, grade="primary_3", name="Gold")
        self.assertEqual(self.student("ada@example.com").school_class, gold)
        self.assertEqual(str(gold), "Grade 3 Gold")
        nursery = SchoolClass.objects.create(school=self.school, session=self.session, grade="nursery_1")
        self.assertEqual(self.student("bo@example.com", "Pre-Level").school_class, nursery)

    def test_a_promotion_moves_them_to_the_next_grades_class(self):
        ada = self.student("ada@example.com")
        admin = person("head@example.com", role="school_admin", school=self.school)
        levels.promote(admin, [ada])
        ada.refresh_from_db()
        self.assertEqual((ada.level, ada.school_class.display_name), ("Level 4", "Grade 4"))

    def test_only_school_students_with_a_level_have_a_class(self):
        for user in (person("t@example.com", role="teacher", school=self.school, level="Level 3"),
                     person("i@example.com", role="individual", level="Level 3"),
                     person("new@example.com", role="student", school=self.school)):
            self.assertIsNone(user.school_class)
        ada = self.student("ada@example.com")
        ada.school = None                        # left the school
        ada.save()
        ada.refresh_from_db()
        self.assertIsNone(ada.school_class)

    def test_a_class_moved_to_another_grade_takes_its_students(self):
        ada = self.student("ada@example.com")
        group = ada.school_class
        group.grade = "primary_5"
        group.save()
        ada.refresh_from_db()
        self.assertEqual((ada.level, ada.school_class), ("Level 5", group))

    def test_a_class_with_students_cant_be_deleted_but_the_school_can(self):
        ada = self.student("ada@example.com")
        with self.assertRaises(RestrictedError):
            ada.school_class.delete()
        self.school.delete()
        self.assertFalse(User.objects.filter(pk=ada.pk).exists())
        self.assertFalse(SchoolClass.objects.filter(school_id=ada.school_id).exists())

    def test_bulk_made_students_are_placed_in_a_few_queries(self):
        made = User.objects.bulk_create([
            User(email=f"s{n}@example.com", first_name="S", role="student", school=self.school,
                 level="Level 3" if n % 2 else "Level 4")
            for n in range(20)
        ])
        with self.assertNumQueries(7):          # the school's year (2), two classes found or made (2 each), the update
            place_many(made)
        self.assertEqual(set(User.objects.filter(role="student").values_list("school_class__grade", flat=True)),
                         {"primary_3", "primary_4"})


class MigrationTests(TestCase):
    """The data migration, run on accounts made before classes existed."""

    def test_existing_students_and_teachers_get_classes(self):
        Session.objects.create(name="2026/2027")
        school = School.objects.create(name="Unity", email="u@example.com")
        ada = person("ada@example.com", role="student", school=school, level="Level 3")
        bo = person("bo@example.com", role="student", school=school, level="Pre-Level")
        solo = person("solo@example.com", role="teacher", school=school, level="Level 3",
                      additional_levels=",Level 8,")
        pair = [person(f"t{n}@example.com", role="teacher", school=school, level="Pre-Level") for n in (1, 2)]
        User.objects.update(school_class=None)              # as before this phase
        SchoolClass.objects.all().delete()

        importlib.import_module("apps.schools.migrations.0009_place_students_in_classes").forwards(django_apps, None)

        ada.refresh_from_db(), bo.refresh_from_db()
        self.assertEqual((ada.school_class.display_name, ada.level), ("Grade 3", "Level 3"))
        self.assertEqual((bo.school_class.display_name, bo.level), ("Kindergarten", "Pre-Level"))
        self.assertEqual(sorted(c.display_name for c in solo.teaching_classes.all()), ["Grade 3", "Grade 8"])
        self.assertEqual(ada.school_class.class_teacher, solo)          # its only teacher
        self.assertEqual(set(bo.school_class.teachers.all()), set(pair))
        self.assertIsNone(bo.school_class.class_teacher)               # two teachers: the school decides
        self.assertEqual(SchoolClass.objects.count(), 3)
