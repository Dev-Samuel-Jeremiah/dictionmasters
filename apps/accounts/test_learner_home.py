"""The simple home (Phase 1A): one "Today's lesson" button for students,
the same card on top of an individual's full dashboard, the For grown-ups
page with its simple-home switch, and the tidied Learn page."""

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.echospell.models import CardPosition, Category, Group, GroupProgress, Level
from apps.learning_modules.models import Day, LearningModule, Term, Week
from apps.learning_tools.views import TOOLS

from .dashboard_data import todays_lesson

User = get_user_model()


def make(email, **extra):
    return User.objects.create_user(email=email, password="mango-river-47", first_name="Ada", **extra)


def level(name, order):
    found, _ = Level.objects.update_or_create(name=name, defaults={"order": order, "is_published": True})
    return found


class LessonPickTests(TestCase):
    """Resume EchoSpell, then the next EchoSpell group, then the next
    module day, then Daily Practice."""

    def setUp(self):
        # Start from nothing, whatever the migrations put in.
        Group.objects.all().delete()
        LearningModule.objects.all().delete()
        self.student = make("pupil@example.com", role="student", level="Level 3")

    def add_module_day(self):
        module = LearningModule.objects.create(name="Sound Discovery")
        week = Week.objects.create(term=Term.objects.create(module=module, name="First Term"), number=1)
        return Day.objects.create(week=week, day_name="monday")

    def test_nothing_to_carry_on_with_falls_back_to_daily_practice(self):
        lesson = todays_lesson(self.student)
        self.assertEqual(lesson["kind"], "daily_practice")
        self.assertEqual(lesson["url"], "/daily-practice/")

    def test_a_module_day_when_there_is_no_echospell_group(self):
        self.add_module_day()
        lesson = todays_lesson(self.student)
        self.assertEqual(lesson["kind"], "modules")
        self.assertIn("Sound Discovery: Monday", lesson["title"])

    def test_the_next_echospell_group_comes_before_a_module_day(self):
        self.add_module_day()
        Group.objects.create(level=level("Level 3", 3), number=1, slug="g1")
        lesson = todays_lesson(self.student)
        self.assertEqual(lesson["kind"], "echospell")
        self.assertEqual(lesson["title"], "EchoSpell: Level 3, Group 1")

    def test_only_groups_from_the_learners_own_level(self):
        Group.objects.create(level=level("Level 1", 1), number=1, slug="low")
        Group.objects.create(level=level("Level 3", 3), number=2, slug="mine")
        self.assertEqual(todays_lesson(self.student)["title"], "EchoSpell: Level 3, Group 2")

    def test_a_finished_group_is_skipped(self):
        first = Group.objects.create(level=level("Level 3", 3), number=1, slug="g1")
        Group.objects.create(level=first.level, number=2, slug="g2")
        GroupProgress.objects.create(user=self.student, group=first)
        self.assertEqual(todays_lesson(self.student)["title"], "EchoSpell: Level 3, Group 2")

    def test_carrying_on_comes_first(self):
        lvl = level("Level 3", 3)
        Group.objects.create(level=lvl, number=1, slug="g1")
        later = Group.objects.create(level=lvl, number=5, slug="g5")
        category = Category.objects.create(name="Spelling")
        lvl.categories.add(category)
        CardPosition.objects.create(user=self.student, group=later, category=category)
        lesson = todays_lesson(self.student)
        self.assertEqual(lesson["label"], "Carry on where you stopped")
        self.assertEqual(lesson["title"], "EchoSpell: Level 3, Group 5")
        self.assertIn(f"/{category.slug}/", lesson["url"])


class HomeTests(TestCase):
    def home(self, user):
        self.client.force_login(user)
        return self.client.get("/accounts/dashboard/")

    def test_a_student_gets_one_button(self):
        page = self.home(make("pupil@example.com", role="student", level="Level 1"))
        self.assertTemplateUsed(page, "accounts/learner_home.html")
        self.assertContains(page, "data-todays-lesson", count=1)
        self.assertContains(page, "Today's lesson")
        self.assertContains(page, 'href="/learning-tools/" class="lh-more__link"')
        self.assertContains(page, 'href="/accounts/grown-ups/"')
        self.assertNotContains(page, "Quick tools")
        self.assertNotContains(page, "Your courses")

    def test_an_individual_keeps_the_full_dashboard_with_the_card_on_top(self):
        page = self.home(make("adult@example.com"))
        self.assertTemplateUsed(page, "accounts/dashboard.html")
        self.assertContains(page, "data-todays-lesson", count=1)
        self.assertContains(page, "Quick tools")
        # The card replaces Continue in EchoSpell, so it isn't offered twice.
        self.assertNotContains(page, "Continue in EchoSpell")
        self.assertContains(page, 'href="/accounts/grown-ups/"')

    def test_an_individual_with_the_simple_home_switched_on(self):
        page = self.home(make("child@example.com", simple_home=True))
        self.assertTemplateUsed(page, "accounts/learner_home.html")

    def test_teachers_keep_their_dashboard_unchanged(self):
        page = self.home(make("teach@example.com", role="teacher", level="Level 2", simple_home=True))
        self.assertTemplateUsed(page, "accounts/dashboard.html")
        self.assertNotContains(page, "data-todays-lesson")
        self.assertContains(page, "Continue in EchoSpell")

    def test_school_admins_still_go_to_the_school_dashboard(self):
        page = self.home(make("head@example.com", role="school_admin"))
        self.assertRedirects(page, "/school/dashboard/", fetch_redirect_response=False)

    def test_the_home_does_not_ask_once_per_group(self):
        """The number of queries stays the same however much content there is."""
        Group.objects.all().delete()
        student = make("count@example.com", role="student", level="Level 4")
        self.client.force_login(student)
        lvl = level("Level 4", 4)
        Group.objects.create(level=lvl, number=1, slug="c1")
        self.client.get("/accounts/dashboard/")
        with CaptureQueriesContext(connection) as few:
            self.client.get("/accounts/dashboard/")
        for number in range(2, 12):
            GroupProgress.objects.create(user=student, group=Group.objects.create(level=lvl, number=number, slug=f"c{number}"))
        with CaptureQueriesContext(connection) as many:
            self.client.get("/accounts/dashboard/")
        self.assertEqual(len(few), len(many))


class GrownUpsTests(TestCase):
    url = "/accounts/grown-ups/"

    def test_an_individual_can_switch_the_simple_home_on_and_off(self):
        adult = make("parent@example.com")
        self.client.force_login(adult)
        page = self.client.get(self.url)
        self.assertContains(page, "Use the simple home")
        self.assertContains(page, "This week")
        self.assertContains(page, "Recent activity")

        self.assertRedirects(self.client.post(self.url, {"simple_home": "on"}), self.url)
        adult.refresh_from_db()
        self.assertTrue(adult.simple_home)
        self.assertTemplateUsed(self.client.get("/accounts/dashboard/"), "accounts/learner_home.html")

        self.client.post(self.url, {})
        adult.refresh_from_db()
        self.assertFalse(adult.simple_home)
        self.assertTemplateUsed(self.client.get("/accounts/dashboard/"), "accounts/dashboard.html")

    def test_students_and_teachers_have_no_switch(self):
        for user in (make("pupil@example.com", role="student", level="Level 1"),
                     make("teach@example.com", role="teacher", level="Level 1")):
            self.client.force_login(user)
            page = self.client.get(self.url)
            self.assertEqual(page.status_code, 200)
            self.assertNotContains(page, "Use the simple home")
            self.client.post(self.url, {"simple_home": "on"})
            user.refresh_from_db()
            self.assertFalse(user.simple_home)

    def test_school_admins_go_to_the_school_dashboard(self):
        self.client.force_login(make("head@example.com", role="school_admin"))
        self.assertRedirects(self.client.get(self.url), "/school/dashboard/", fetch_redirect_response=False)

    def test_signed_out_visitors_are_sent_to_log_in(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)


class LearnPageTests(TestCase):
    url = "/learning-tools/"

    def shown(self, user):
        self.client.force_login(user)
        page = self.client.get(self.url)
        return page, [tool["url_name"] for section in page.context["sections"] for tool in section["tools"]]

    def test_every_course_and_tool_is_listed_once(self):
        names = [tool["url_name"] for tool in TOOLS]
        self.assertEqual(len(names), len(set(names)))
        page, shown = self.shown(make("teach@example.com", role="teacher"))
        self.assertEqual(sorted(shown), sorted(names))
        self.assertContains(page, "<h1>Learn</h1>", html=False)
        self.assertContains(page, "All courses and tools")
        self.assertContains(page, "The Etiquette Advantage", count=1)

    def test_students_do_not_see_teacher_tools(self):
        _page, shown = self.shown(make("pupil@example.com", role="student", level="Level 1"))
        self.assertNotIn("lesson_audio:hub", shown)
        self.assertIn("echospell:hub", shown)
