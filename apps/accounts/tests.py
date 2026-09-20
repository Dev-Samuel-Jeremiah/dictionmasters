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


class PasswordGuidanceTests(TestCase):
    """Anyone setting a password is told what is wanted, before they are
    told they got it wrong."""

    def test_every_registration_page_says_what_a_password_needs(self):
        from .forms import PASSWORD_HELP

        for url in ["/accounts/register/individual/", "/accounts/register/school/",
                    "/accounts/register/student/", "/accounts/join/"]:
            page = self.client.get(url)
            self.assertEqual(page.status_code, 200, url)
            self.assertContains(page, "8 characters or more", msg_prefix=url)
            self.assertContains(page, "mango river 47", msg_prefix=url)
        self.assertIn("8 characters or more", PASSWORD_HELP)

    def test_the_guidance_matches_what_is_actually_checked(self):
        """The four things the page ticks off are the four the site
        enforces, so nothing is promised here and refused on sending."""
        from django.conf import settings

        enforced = {rule["NAME"].rsplit(".", 1)[-1] for rule in settings.AUTH_PASSWORD_VALIDATORS}
        self.assertEqual(enforced, {
            "UserAttributeSimilarityValidator",    # "Not your name or email"
            "MinimumLengthValidator",              # "8 characters or more"
            "CommonPasswordValidator",             # "Not a common password"
            "NumericPasswordValidator",            # "Not only numbers"
        })


class NamingTests(TestCase):
    def test_the_tool_is_called_44_academy(self):
        user = get_user_model().objects.create_user(
            email="named@example.com", password="mango-river-47", first_name="Ada", is_staff=True)
        self.client.force_login(user)
        for url in ["/book/", "/book/44-academy/", "/learning-tools/"]:
            page = self.client.get(url)
            self.assertContains(page, "44 Academy", msg_prefix=url)
            self.assertNotContains(page, "Book of Conversation", msg_prefix=url)
