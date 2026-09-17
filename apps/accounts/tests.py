"""A couple of checks that the account rules hold: level access and that
a joining code decides a person's level."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.access import accessible_levels, can_see_level


class LevelAccessTests(TestCase):
    def setUp(self):
        self.User = get_user_model()

    def test_individual_learner_sees_every_level(self):
        learner = self.User.objects.create_user(email="solo@example.com", password="x" * 12, first_name="Solo")
        self.assertIsNone(accessible_levels(learner))
        self.assertTrue(can_see_level(learner, "Level 7"))

    def test_student_sees_only_their_own_level(self):
        student = self.User.objects.create_user(
            email="pupil@example.com", password="x" * 12, first_name="Pupil", role="student", level="Level 1"
        )
        self.assertEqual(accessible_levels(student), ["Level 1"])
        self.assertTrue(can_see_level(student, "Level 1"))
        self.assertFalse(can_see_level(student, "Level 3"))

    def test_content_with_no_level_is_open_to_everyone(self):
        student = self.User.objects.create_user(
            email="pupil2@example.com", password="x" * 12, first_name="Pupil", role="student", level="Level 2"
        )
        self.assertTrue(can_see_level(student, ""))
