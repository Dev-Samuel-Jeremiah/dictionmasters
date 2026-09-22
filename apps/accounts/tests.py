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


class DashboardCardTests(TestCase):
    def test_yela_has_a_card_that_opens_the_reading_tutor(self):
        user = get_user_model().objects.create_user(
            email="cards@example.com", password="mango-river-47", first_name="Ada")
        self.client.force_login(user)
        page = self.client.get("/accounts/dashboard/")
        self.assertContains(page, "Yela")
        self.assertContains(page, "your AI Diction Assistant")
        self.assertContains(page, 'href="/tutor/"')
        # Nothing read yet: the card invites instead of counting.
        self.assertContains(page, "Read aloud")


class TemplateHygieneTests(TestCase):
    def test_no_comment_spills_onto_the_page(self):
        """Django's {# … #} comment only works on one line. Spread over two,
        it is printed on the page as text — which has happened twice. Longer
        notes belong in {% comment %} … {% endcomment %}."""
        import pathlib
        import re

        from django.conf import settings

        spilled = []
        for folder in settings.TEMPLATES[0]["DIRS"]:
            for path in pathlib.Path(folder).rglob("*.html"):
                text = path.read_text()
                for match in re.finditer(r"\{#", text):
                    rest = text[match.start():]
                    close = rest.find("#}")
                    if close < 0 or "\n" in rest[:close]:
                        spilled.append(f"{path.name}:{text[:match.start()].count(chr(10)) + 1}")
        self.assertEqual(spilled, [], "Multi-line {# #} comments show up on the page")
