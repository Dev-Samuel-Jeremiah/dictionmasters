"""The bell: updates made when something happens (signals.py), reminders
worked out live (reminders.py), and the bell's pages (views.py)."""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import PasswordHelpRequest
from apps.assessments.models import Assessment, Attempt
from apps.scheme.models import ReportCard, Session, Term
from apps.schools.models import School, SchoolClass

from . import reminders
from .models import Notification
from .notify import quiet

User = get_user_model()


def person(email, **extra):
    return User.objects.create_user(email, "mango-river-47", first_name=email.split("@")[0].title(), **extra)


class BellCase(TestCase):
    def setUp(self):
        self.session = Session.objects.create(name="2026/2027")
        self.school = School.objects.create(name="Unity", email="u@example.com")
        self.admin = person("head@example.com", role="school_admin", school=self.school)
        self.gold = SchoolClass.objects.create(school=self.school, session=self.session, grade="primary_3", name="Gold")
        self.tola = person("tola@example.com", role="teacher", school=self.school, level="Level 3")
        self.ada = person("ada@example.com", role="student", school=self.school, level="Level 3",
                          school_class=self.gold)
        self.test = Assessment.objects.create(title="CA 1", kind="ca", level="Level 3", term=1, is_published=True)
        Notification.objects.all().delete()          # start each test with an empty bell
        self.addCleanup(lambda: [reminders.forget(u.pk) for u in User.objects.all()])

    def titles(self, user):
        return list(Notification.objects.filter(user=user).values_list("title", flat=True))


class UpdateTests(BellCase):
    def test_handing_in_tells_the_teacher_and_marking_tells_the_pupil(self):
        attempt = Attempt.objects.create(user=self.ada, assessment=self.test)
        attempt.status = Attempt.Status.AWAITING
        attempt.save()
        attempt.save()                                         # saved again: no second update
        self.assertEqual(self.titles(self.tola), ["Ada handed in CA 1"])
        attempt.status, attempt.percent = Attempt.Status.MARKED, 72
        attempt.save()
        self.assertEqual(self.titles(self.ada), ["Your CA 1 is marked"])
        note = Notification.objects.get(user=self.ada)
        self.assertEqual((note.body, note.url), ("You scored 72%.", f"/assessments/attempt/{attempt.pk}/result/"))

    def test_a_new_test_tells_its_levels_school_pupils(self):
        other = person("ben@example.com", role="student", school=self.school, level="Level 4")
        solo = person("solo@example.com", role="individual", level="Level 3")
        exam = Assessment.objects.create(title="Exam", kind="exam", level="Level 3", term=1, is_published=True)
        exam.save()
        self.assertEqual(self.titles(self.ada), ["New test: Exam"])
        self.assertEqual(self.titles(other) + self.titles(solo), [])

    def test_a_published_report_card_tells_the_pupil(self):
        term = Term.objects.create(session=self.session, number=1, starts=date(2026, 9, 7), ends=date(2026, 12, 11))
        card = ReportCard.objects.create(student=self.ada, term=term, total=70)
        self.assertEqual(self.titles(self.ada), [])
        card.published_at = timezone.now()
        card.save()
        self.assertEqual(len(self.titles(self.ada)), 1)
        self.assertIn("report card", self.titles(self.ada)[0])

    def test_joining_tells_the_teachers_and_the_admin(self):
        self.gold.teachers.add(self.tola)
        person("bo@example.com", role="student", school=self.school, level="Level 3", school_class=self.gold)
        self.assertEqual(self.titles(self.tola), ["Bo joined Grade 3 Gold"])
        self.assertEqual(self.titles(self.admin), ["Bo joined as a student"])
        person("grace@example.com", role="teacher", school=self.school, level="Level 1")
        self.assertIn("Grace joined as a teacher", self.titles(self.admin))

    def test_bulk_tools_stay_quiet(self):
        with quiet():
            person("cy@example.com", role="student", school=self.school, level="Level 3")
        self.assertEqual(self.titles(self.admin), [])

    def test_a_password_help_request_tells_the_admin(self):
        PasswordHelpRequest.objects.create(user=self.ada, school=self.school)
        self.assertEqual(self.titles(self.admin), ["Ada needs help with their password"])


class ReminderTests(BellCase):
    def test_a_learner_is_reminded_of_an_unfinished_test(self):
        attempt = Attempt.objects.create(user=self.ada, assessment=self.test)
        found = reminders.for_user(self.ada)
        self.assertIn("Finish your test: CA 1", [r["title"] for r in found])
        self.assertIn(f"/assessments/attempt/{attempt.pk}/", [r["url"] for r in found])

    def test_a_school_test_closing_soon(self):
        Assessment.objects.create(title="CA 2", kind="ca", level="Level 3", term=1, is_published=True,
                                  closes_at=timezone.now() + timedelta(days=1))
        self.assertIn("CA 2 closes soon", [r["title"] for r in reminders.for_user(self.ada)])

    def test_a_streak_that_ends_tonight(self):
        from apps.clash.models import Match

        Match.objects.create(user=self.ada, status=Match.Status.FINISHED, seed=1, mode="classic", difficulty="beginner",
                             finished_at=timezone.now() - timedelta(days=1))
        Match.objects.filter(user=self.ada).update(started_at=timezone.now() - timedelta(days=1))
        self.assertIn("Keep your 1-day streak going!", [r["title"] for r in reminders.for_user(self.ada)])

    def test_a_teacher_is_reminded_of_work_to_mark(self):
        self.gold.teachers.add(self.tola)
        Attempt.objects.create(user=self.ada, assessment=self.test, status=Attempt.Status.AWAITING)
        self.assertIn("1 answer to mark", [r["title"] for r in reminders.for_user(self.tola)])

    def test_an_admin_is_reminded_of_students_with_no_class_and_help_requests(self):
        person("lost@example.com", role="student", school=self.school)        # no level, so no class
        PasswordHelpRequest.objects.create(user=self.ada, school=self.school)
        titles = [r["title"] for r in reminders.for_user(self.admin)]
        self.assertIn("1 student with no class", titles)
        self.assertIn("1 password help request", titles)


class BellPageTests(BellCase):
    def test_the_bell_shows_a_count_and_the_dropdown_marks_updates_read(self):
        Notification.objects.create(user=self.ada, title="Your CA 1 is marked", url="/assessments/results/")
        self.client.force_login(self.ada)
        home = self.client.get("/accounts/dashboard/")
        self.assertContains(home, "data-bell")
        self.assertContains(home, 'data-bell-count>1</span>')
        self.assertEqual(self.client.get("/notifications/count/").json(), {"count": 1})
        panel = self.client.get("/notifications/panel/")
        self.assertContains(panel, "Your CA 1 is marked")
        self.assertEqual(self.client.get("/notifications/count/").json(), {"count": 0})

    def test_opening_an_update_goes_where_it_leads(self):
        note = Notification.objects.create(user=self.ada, title="Results", url="/assessments/results/")
        self.client.force_login(self.ada)
        self.assertRedirects(self.client.get(f"/notifications/{note.pk}/"), "/assessments/results/",
                             fetch_redirect_response=False)
        note.refresh_from_db()
        self.assertIsNotNone(note.read_at)
        self.client.force_login(self.tola)
        self.assertEqual(self.client.get(f"/notifications/{note.pk}/").status_code, 404)    # not theirs

    def test_the_page_and_mark_all_read(self):
        Notification.objects.create(user=self.ada, title="One")
        Notification.objects.create(user=self.ada, title="Two")
        self.client.force_login(self.ada)
        self.assertContains(self.client.get("/notifications/"), "Two")
        self.assertFalse(Notification.objects.filter(user=self.ada, read_at__isnull=True).exists())
        Notification.objects.create(user=self.ada, title="Three")
        self.client.post("/notifications/read-all/")
        self.assertFalse(Notification.objects.filter(user=self.ada, read_at__isnull=True).exists())

    def test_all_caught_up(self):
        self.client.force_login(person("new@example.com", role="individual"))
        self.assertContains(self.client.get("/notifications/panel/"), "You're all caught up!")
