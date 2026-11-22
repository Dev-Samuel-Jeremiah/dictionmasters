"""The class-access report of 18 November 2026: a teacher or student given
several levels in the control room keeps every one of them, and a teacher
sees the students of every class those levels bring (apps/schools/classes.py,
follow_levels)."""

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.accounts.access import can_see_level, can_use_tool, pupils_of
from apps.scheme.models import Session

from . import classes
from .models import School, SchoolClass

User = get_user_model()


def person(email, **extra):
    return User.objects.create_user(email, "mango-river-47", first_name=email.split("@")[0].title(), **extra)


class MultiClassAccessTests(TestCase):
    def setUp(self):
        self.year = Session.objects.create(name="2026/2027")
        self.school = School.objects.create(name="Unity", email="u@example.com")
        self.staff = person("boss@example.com", is_staff=True)
        self.classes = {grade: SchoolClass.objects.create(school=self.school, session=self.year, grade=grade)
                        for grade in ("primary_3", "primary_4", "primary_6", "jss_1")}
        self.pupils = {grade: person(f"{grade}@example.com", role="student", school=self.school,
                                     level=found.level, school_class=found)
                       for grade, found in self.classes.items()}
        # A Level 4 teacher, in the Level 4 class, as schools start out.
        self.teacher = person("tola@example.com", role="teacher", school=self.school, level="Level 4")

    def grant(self, member, *levels):
        """Tick these levels on the control room's profile form."""
        self.client.force_login(self.staff)
        answer = self.client.post(f"/manage/profiles/{member.pk}/", {
            "first_name": member.first_name, "last_name": member.last_name,
            "school": member.school_id or "", "levels_taught": list(levels)})
        self.assertIn(answer.status_code, (200, 302))
        member.refresh_from_db()

    def taught(self, teacher):
        return sorted(c.level for c in classes.classes_taught(teacher))

    def test_a_teacher_given_levels_3_and_4_keeps_both(self):
        self.assertEqual(self.taught(self.teacher), ["Level 4"])
        self.grant(self.teacher, "Level 3", "Level 4")
        self.assertEqual(self.teacher.all_levels, ["Level 3", "Level 4"])
        self.assertEqual(self.taught(self.teacher), ["Level 3", "Level 4"])
        # The next change to their classes used to cut Level 3 off again.
        other = person("ngozi@example.com", role="teacher", school=self.school, level="Level 4")
        self.classes["primary_4"].teachers.add(other)
        self.classes["primary_4"].teachers.add(self.teacher)
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.all_levels, ["Level 3", "Level 4"])
        self.assertTrue(can_see_level(self.teacher, "Level 3"))
        self.assertTrue(can_see_level(self.teacher, "Level 4"))

    def test_a_teacher_given_levels_6_and_7_sees_both_levels_students(self):
        self.assertEqual(list(pupils_of(self.teacher)), [self.pupils["primary_4"]])
        self.grant(self.teacher, "Level 6", "Level 7")
        seen = set(pupils_of(self.teacher))
        self.assertEqual(seen, {self.pupils["primary_6"], self.pupils["jss_1"]})
        self.assertEqual(self.taught(self.teacher), ["Level 6", "Level 7"])       # Level 4 taken away

    def test_a_level_taken_away_takes_its_class(self):
        self.grant(self.teacher, "Level 3", "Level 4")
        self.classes["primary_3"].class_teacher = self.teacher
        self.classes["primary_3"].save()
        self.grant(self.teacher, "Level 4")
        self.assertEqual(self.taught(self.teacher), ["Level 4"])
        self.classes["primary_3"].refresh_from_db()
        self.assertIsNone(self.classes["primary_3"].class_teacher)

    def test_the_schools_own_arrangement_of_a_level_is_kept(self):
        """A teacher the school put in Grade 4 Gold only isn't added to Blue."""
        blue = SchoolClass.objects.create(school=self.school, session=self.year, grade="primary_4", name="Blue")
        self.assertNotIn(blue, classes.classes_taught(self.teacher))      # made after they joined
        self.grant(self.teacher, "Level 3", "Level 4")
        self.assertNotIn(blue, classes.classes_taught(self.teacher))
        self.assertIn(self.classes["primary_3"], classes.classes_taught(self.teacher))

    def test_a_level_with_no_class_yet_gets_one(self):
        self.grant(self.teacher, "Level 4", "Level 9")
        made = SchoolClass.objects.get(school=self.school, session=self.year, grade="jss_3")
        self.assertIn(self.teacher, made.teachers.all())

    def test_a_student_given_several_levels_keeps_them(self):
        student = self.pupils["primary_3"]
        self.grant(student, "Level 3", "Level 4")
        self.assertEqual(student.all_levels, ["Level 3", "Level 4"])
        self.assertEqual(student.school_class, self.classes["primary_3"])    # their class follows the first
        self.assertTrue(can_see_level(student, "Level 4"))
        # Moved to another class: the extra level stays.
        admin = person("head@example.com", role="school_admin", school=self.school)
        classes.move(admin, [student], self.classes["primary_6"])
        student.refresh_from_db()
        self.assertEqual(student.all_levels, ["Level 4", "Level 6"])

    def test_tools_kept_for_some_levels_open_for_any_of_a_students_levels(self):
        from apps.learning_tools.models import ToolLevels

        student = self.pupils["primary_3"]
        ToolLevels.objects.create(tool="clash:hub", levels=",Level 4,")
        self.assertFalse(can_use_tool(student, "clash:hub"))
        self.grant(student, "Level 3", "Level 4")
        self.assertTrue(can_use_tool(student, "clash:hub"))

    def test_the_repair_puts_teachers_already_affected_right(self):
        # As before the fix: a second level stored, but no class for it.
        User.objects.filter(pk=self.teacher.pk).update(additional_levels=",Level 6,")
        out = StringIO()
        call_command("repair_teacher_classes", stdout=out)
        self.assertIn("1 have a level with no class", out.getvalue())
        self.assertEqual(self.taught(self.teacher), ["Level 4"])                # a dry run changes nothing
        call_command("repair_teacher_classes", "--apply", stdout=StringIO())
        self.assertEqual(self.taught(self.teacher), ["Level 4", "Level 6"])
        self.assertIn(self.pupils["primary_6"], pupils_of(self.teacher))
        out = StringIO()
        call_command("repair_teacher_classes", stdout=out)
        self.assertIn("0 have a level with no class", out.getvalue())
