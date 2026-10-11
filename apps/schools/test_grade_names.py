"""Phase D of classes: school people see grades where individual learners
see levels, and individual learners are asked their qualification."""

import re

from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import TestCase

from apps.accounts.forms import SchoolTeamMemberForm
from apps.accounts.views import TOUR_DONE
from apps.scheme.models import Session

from .models import School, SchoolClass

User = get_user_model()


def person(email, **extra):
    return User.objects.create_user(email, "mango-river-47", first_name=email.split("@")[0].title(), **extra)


class GradeNameTests(TestCase):
    def setUp(self):
        Session.objects.create(name="2026/2027")
        self.school = School.objects.create(name="Unity", email="u@example.com")
        self.gold = SchoolClass.objects.create(school=self.school, grade="primary_3", name="Gold",
                                               session=Session.objects.first())
        self.ada = person("ada@example.com", role="student", school=self.school, level="Level 3", school_class=self.gold)

    def test_how_a_level_reads(self):
        self.assertEqual(User.objects.select_related("school_class").get(pk=self.ada.pk).level_display, "Primary 3 Gold")
        self.assertEqual(User.objects.get(pk=self.ada.pk).level_display, "Primary 3")      # class not loaded: no query
        tola = person("tola@example.com", role="teacher", school=self.school, level="Level 3", additional_levels=",Level 7,")
        self.assertEqual(tola.level_display, "Primary 3 and JSS 1")
        tiny = person("tiny@example.com", role="student", school=self.school, level="Pre-Level")
        self.assertEqual(User.objects.get(pk=tiny.pk).level_display, "Pre-School")
        self.assertEqual(person("solo@example.com", role="individual", level="Level 3").level_display, "Level 3")

    def test_the_level_name_filter(self):
        page = Template("{% load grades %}{{ level|level_name:who }}")
        self.assertEqual(page.render(Context({"level": "Level 8", "who": self.ada})), "JSS 2")
        solo = person("solo@example.com", role="individual")
        self.assertEqual(page.render(Context({"level": "Level 8", "who": solo})), "Level 8")

    def test_the_school_dashboard_speaks_in_grades(self):
        self.client.force_login(person("head@example.com", role="school_admin", school=self.school))
        page = self.client.get("/school/dashboard/").content.decode()
        self.assertIn('<option value="Level 3">Primary 3</option>', page)
        self.assertIn('<option value="Pre-Level">Pre-School</option>', page)
        self.assertNotRegex(page, r">Level \d+<")
        self.assertIn("Move up a grade", page)

    def test_the_school_registration_form_offers_grades(self):
        choices = dict(SchoolTeamMemberForm(kind="student").fields["level"].choices)
        self.assertEqual((choices["Level 7"], choices["Pre-Level"]), ("JSS 1", "Pre-School"))


class QualificationTests(TestCase):
    def sign_up(self, **extra):
        session = self.client.session
        session[TOUR_DONE] = True
        session.save()
        return self.client.post("/accounts/register/individual/", {
            "first_name": "Ngozi", "email": "ngozi@example.com", "password1": "kola-river-9",
            "password2": "kola-river-9", "start": "trial", **extra})

    def test_asked_at_sign_up(self):
        page = self.sign_up()
        self.assertFalse(User.objects.filter(email="ngozi@example.com").exists())
        self.assertContains(page, "Your highest qualification")
        self.sign_up(qualification="masters")
        self.assertEqual(User.objects.get(email="ngozi@example.com").qualification, "masters")

    def test_asked_once_on_the_home_of_someone_who_signed_up_before(self):
        solo = person("solo@example.com", role="individual")
        self.client.force_login(solo)
        home = self.client.get("/accounts/dashboard/")
        self.assertContains(home, "data-qualification")
        self.client.post("/accounts/qualification/", {"qualification": "phd", "next": "/accounts/dashboard/"})
        solo.refresh_from_db()
        self.assertEqual(solo.qualification, "phd")
        self.assertNotContains(self.client.get("/accounts/dashboard/"), "data-qualification")

    def test_not_asked_of_children_or_school_students(self):
        child = person("child@example.com", role="individual", simple_home=True)
        self.client.force_login(child)
        self.assertNotContains(self.client.get("/accounts/dashboard/", follow=True), "data-qualification")   # their simple home
        school = School.objects.create(name="Unity", email="u@example.com")
        pupil = person("pupil@example.com", role="student", school=school, level="Level 2")
        self.client.post("/accounts/qualification/", {"qualification": "phd"})
        self.client.force_login(pupil)
        self.client.post("/accounts/qualification/", {"qualification": "phd"})
        pupil.refresh_from_db()
        self.assertEqual(pupil.qualification, "")

    def test_the_cards_options_are_the_models(self):
        with open("templates/accounts/_qualification.html") as card:
            values = re.findall(r'<option value="([a-z]+)">', card.read())
        self.assertEqual(values, list(User.Qualification.values))
