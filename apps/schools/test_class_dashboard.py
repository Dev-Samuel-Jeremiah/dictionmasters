"""A teacher's class (Phase 1B): who counts as their pupils, the numbers
shown for each, and that nobody else can see them."""

from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.access import pupils_of, teaches
from apps.accounts.models import User
from apps.assessments.models import Assessment, Attempt as AssessmentAttempt
from apps.echospell.models import Activity, ActivityAttempt, Group, GroupProgress, Level
from apps.learning_modules.models import Day, DayProgress, LearningModule, Term, Week

from .class_progress import class_progress
from .models import School


class ClassTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Unity School", email="unity@example.com")
        self.other_school = School.objects.create(name="Hope School", email="hope@example.com")
        self.teacher = self.person("teacher", "Level 2", role="teacher", additional=",Level 3,")
        self.ada = self.person("ada", "Level 2")
        self.ben = self.person("ben", "Level 3")
        self.cara = self.person("cara", "Level 5")                       # a level the teacher doesn't teach
        self.dan = self.person("dan", "Level 2", school=self.other_school)
        self.eve = self.person("eve", "Level 2")
        self.eve.is_active = False                                        # removed by the school admin
        self.eve.save()

    def person(self, name, level="", role="student", school=None, additional=""):
        return User.objects.create_user(f"{name}@example.com", "pw-12345678", first_name=name.title(), role=role,
                                        school=school or self.school, level=level, additional_levels=additional)

    def row(self, pupil, data=None):
        data = data or class_progress(pupils_of(self.teacher))
        return next(r for r in data["rows"] if r["pupil"].pk == pupil.pk)

    # ----- who is in the class -----

    def test_a_teacher_has_the_active_students_in_their_own_levels(self):
        self.assertEqual(set(pupils_of(self.teacher)), {self.ada, self.ben})
        self.assertTrue(teaches(self.teacher, self.ada))
        self.assertFalse(teaches(self.teacher, self.cara))
        self.assertFalse(teaches(self.teacher, self.dan))

    def test_a_teacher_with_no_level_yet_has_the_whole_school(self):
        new = self.person("new", role="teacher")
        self.assertEqual(set(pupils_of(new)), {self.ada, self.ben, self.cara})

    def test_nobody_else_has_a_class(self):
        for who in (self.ada, self.person("head", role="school_admin"),
                    User.objects.create_user("solo@example.com", "pw-12345678", first_name="Solo")):
            self.assertFalse(pupils_of(who).exists())

    # ----- the numbers -----

    def test_each_pupils_progress(self):
        level, _ = Level.objects.update_or_create(name="Level 2", defaults={"is_published": True})
        Group.objects.filter(level=level).delete()
        first = Group.objects.create(level=level, number=1, slug="c-g1")
        Group.objects.create(level=level, number=2, slug="c-g2")
        GroupProgress.objects.create(user=self.ada, group=first)
        activity = Activity.objects.create(group=first, kind="read-aloud", title="Read", pass_mark=50)
        ActivityAttempt.objects.create(user=self.ada, activity=activity, status="marked", percent=80)
        ActivityAttempt.objects.create(user=self.ada, activity=activity, status="reviewed", percent=60)
        test = Assessment.objects.create(title="Speaking check", kind=Assessment.Kind.SPEAKING, pass_mark=60)
        AssessmentAttempt.objects.create(user=self.ada, assessment=test, status="awaiting", submitted_at=timezone.now())
        module = LearningModule.objects.create(name="Sound Discovery")
        week = Week.objects.create(term=Term.objects.create(module=module, name="First Term"), number=1)
        DayProgress.objects.create(user=self.ada, day=Day.objects.create(week=week, day_name="monday"))

        data = class_progress(pupils_of(self.teacher))
        ada = self.row(self.ada, data)
        self.assertEqual((ada["echospell_done"], ada["echospell_total"], ada["echospell_percent"]), (1, 2, 50))
        self.assertEqual(ada["activity_avg"], 70)
        self.assertIsNone(ada["assessment_avg"])                          # still waiting to be marked
        self.assertEqual(ada["to_mark"], 1)
        self.assertEqual(ada["module_days"], 1)
        self.assertEqual(ada["state"], "active")
        self.assertEqual(ada["sessions_week"], 5)
        self.assertEqual(self.row(self.ben, data)["state"], "new")
        self.assertEqual(data["summary"], {"pupils": 2, "active": 1, "quiet": 0, "new": 1, "to_mark": 1, "needs_help": 0})

    def test_a_pupil_with_nothing_lately_is_quiet(self):
        module = LearningModule.objects.create(name="Sound Discovery")
        week = Week.objects.create(term=Term.objects.create(module=module, name="First Term"), number=1)
        done = DayProgress.objects.create(user=self.ben, day=Day.objects.create(week=week, day_name="monday"))
        DayProgress.objects.filter(pk=done.pk).update(completed_at=timezone.now() - timedelta(days=10))
        ben = self.row(self.ben)
        self.assertEqual(ben["state"], "quiet")
        self.assertEqual(ben["sessions_week"], 0)

    def test_the_class_costs_the_same_however_many_pupils(self):
        with CaptureQueriesContext(connection) as small:
            class_progress(pupils_of(self.teacher))
        for n in range(15):
            self.person(f"extra{n}", "Level 2")
        with CaptureQueriesContext(connection) as big:
            data = class_progress(pupils_of(self.teacher))
        self.assertEqual(len(data["rows"]), 17)
        self.assertEqual(len(small), len(big))

    # ----- the pages -----

    def test_the_teacher_sees_their_class_and_can_open_a_pupil(self):
        self.client.force_login(self.teacher)
        page = self.client.get("/school/class/")
        self.assertContains(page, "My class")
        self.assertContains(page, "Ada")
        self.assertContains(page, "Ben")
        self.assertNotContains(page, "Cara")
        self.assertNotContains(page, "Dan")
        self.assertContains(page, "All my levels")
        only_three = self.client.get("/school/class/?level=Level 3")
        self.assertNotContains(only_three, f'href="/school/class/{self.ada.pk}/"')
        self.assertContains(only_three, f'href="/school/class/{self.ben.pk}/"')
        self.assertContains(self.client.get(f"/school/class/{self.ada.pk}/"), "Ada")

    def test_a_level_the_teacher_does_not_teach_shows_their_whole_class(self):
        self.client.force_login(self.teacher)
        page = self.client.get("/school/class/?level=Level 5")
        self.assertNotContains(page, "Cara")
        self.assertContains(page, "Ada")

    def test_pupils_outside_the_class_cannot_be_opened(self):
        self.client.force_login(self.teacher)
        for pupil in (self.cara, self.dan, self.eve, self.teacher):
            self.assertEqual(self.client.get(f"/school/class/{pupil.pk}/").status_code, 404, pupil.first_name)

    def test_only_teachers_get_in(self):
        for who in (self.ada, self.person("head", role="school_admin"),
                    User.objects.create_user("solo@example.com", "pw-12345678", first_name="Solo")):
            self.client.force_login(who)
            self.assertRedirects(self.client.get("/school/class/"), "/", fetch_redirect_response=False)
            self.assertRedirects(self.client.get(f"/school/class/{self.ada.pk}/"), "/", fetch_redirect_response=False)

    def test_the_teachers_home_shows_their_class(self):
        self.client.force_login(self.teacher)
        page = self.client.get("/accounts/dashboard/")
        self.assertContains(page, "data-my-class")
        self.assertContains(page, "2 pupils")
        self.assertNotContains(page, "Your class dashboard is on its way")
        # Their own learner view is still there underneath.
        self.assertContains(page, "Continue in EchoSpell")
