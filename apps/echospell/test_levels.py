"""A level with no EchoSpell of its own uses the nearest one below it
(apps/echospell/levels.py): the book stops at Level 7 for now, so a Grade
8 pupil opens Level 7 rather than an empty page."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.assignments.forms import _fits, work_choices
from apps.assignments.models import Assignment

from .levels import echospell_level
from .models import Group, Level

User = get_user_model()


class BorrowedLevelTests(TestCase):
    def setUp(self):
        Level.objects.filter(name__in=["Level 8", "Level 9"]).update(is_published=True)   # published but empty
        self.six, _ = Level.objects.update_or_create(name="Level 6", defaults={"is_published": True})
        self.seven, _ = Level.objects.update_or_create(name="Level 7", defaults={"is_published": True})
        self.g6 = Group.objects.create(level=self.six, number=61, slug="borrow-61")
        self.g7 = Group.objects.create(level=self.seven, number=71, slug="borrow-71")
        self.pupil = User.objects.create_user("grade8@example.com", "pw-12345678", first_name="Abel",
                                              role="student", level="Level 8")
        self.client.force_login(self.pupil)

    def test_the_nearest_written_level_below(self):
        self.assertEqual(echospell_level("Level 8"), "Level 7")
        self.assertEqual(echospell_level("Level 12"), "Level 7")
        self.assertEqual(echospell_level("Level 7"), "Level 7")
        self.assertEqual(echospell_level("Level 6"), "Level 6")

    def test_a_grade_8_pupil_opens_level_7(self):
        hub = self.client.get("/echospell/")
        self.assertContains(hub, "Level 7")
        self.assertNotContains(hub, "Levels are being put together")
        self.assertEqual(self.client.get(f"/echospell/{self.seven.slug}/{self.g7.slug}/").status_code, 200)
        self.assertEqual(self.client.get(f"/echospell/{self.six.slug}/{self.g6.slug}/").status_code, 403)

    def test_their_own_level_takes_over_once_it_is_written(self):
        eight, _ = Level.objects.update_or_create(name="Level 8", defaults={"is_published": True})
        own = Group.objects.create(level=eight, number=81, slug="own-81")
        self.assertEqual(echospell_level("Level 8"), "Level 8")
        self.assertEqual(echospell_level("Level 9"), "Level 8")
        self.assertEqual(self.client.get(f"/echospell/{eight.slug}/{own.slug}/").status_code, 200)
        self.assertEqual(self.client.get(f"/echospell/{self.seven.slug}/{self.g7.slug}/").status_code, 403)

    def test_a_grade_8_class_can_be_set_level_7_groups(self):
        values = {v for _label, options in work_choices(["Level 8"]) for v, _text in options}
        self.assertIn(f"group:{self.g7.pk}", values)
        self.assertNotIn(f"group:{self.g6.pk}", values)
        self.assertTrue(_fits(Assignment.Kind.GROUP, self.g7, "Level 8", {})[0])
        self.assertFalse(_fits(Assignment.Kind.GROUP, self.g6, "Level 8", {})[0])
