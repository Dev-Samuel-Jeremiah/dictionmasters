"""Phase 5, the school year: the term calendar, the scheme of work, CA
tests and exams, report cards and promotion from results."""

from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts import grown_ups
from apps.assessments.models import Assessment, Attempt, Question
from apps.echospell.models import Group, GroupProgress, Level
from apps.schools.models import LevelChange, School

from .calendar import terms_for, where_we_are
from .models import Grading, ReportCard, SchoolTermDates, Session, Term
from .results import publish, term_results

User = get_user_model()


def make(email, **extra):
    return User.objects.create_user(email, "mango-river-47", first_name=email.split("@")[0].title(), **extra)


class YearTestCase(TestCase):
    """A school year: First Term 7 Sep – 11 Dec 2026 with a half-term
    26–30 Oct, Second Term 5 Jan – 2 Apr 2027."""

    def setUp(self):
        self.session = Session.objects.create(name="2026/2027")
        self.first = Term.objects.create(session=self.session, number=1, starts=date(2026, 9, 7),
                                         ends=date(2026, 12, 11), break_starts=date(2026, 10, 26),
                                         break_ends=date(2026, 10, 30))
        self.second = Term.objects.create(session=self.session, number=2, starts=date(2027, 1, 5),
                                          ends=date(2027, 4, 2))
        self.school = School.objects.create(name="Unity", email="u@example.com")
        self.admin = make("head@example.com", role="school_admin", school=self.school)
        self.teacher = make("teach@example.com", role="teacher", school=self.school, level="Level 2")
        self.ada = make("ada@example.com", role="student", school=self.school, level="Level 2")
        self.ben = make("ben@example.com", role="student", school=self.school, level="Level 2")

    def on(self, day):
        """Pretend today is `day` for the calendar and the timetable."""
        from contextlib import ExitStack

        stack = ExitStack()
        for where in ("apps.scheme.calendar.timezone.localdate", "apps.scheme.timetable.timezone.localdate"):
            stack.enter_context(mock.patch(where, return_value=day))
        return stack


class CalendarTests(YearTestCase):
    def test_weeks_count_from_the_first_day_and_skip_the_break(self):
        self.assertEqual(where_we_are(self.ada, date(2026, 9, 7))["week"], 1)
        self.assertEqual(where_we_are(self.ada, date(2026, 9, 14))["label"], "First Term, Week 2")
        self.assertEqual(where_we_are(self.ada, date(2026, 10, 23))["week"], 7)
        self.assertEqual(where_we_are(self.ada, date(2026, 10, 27))["state"], "break")
        self.assertEqual(where_we_are(self.ada, date(2026, 11, 2))["week"], 8)

    def test_between_terms_is_a_holiday_with_the_next_term_named(self):
        place = where_we_are(self.ada, date(2026, 12, 20))
        self.assertEqual(place["state"], "holiday")
        self.assertIn("Second Term starts Tuesday 05 January", place["label"])

    def test_a_school_can_keep_its_own_dates(self):
        SchoolTermDates.objects.create(school=self.school, term=self.first,
                                       starts=date(2026, 9, 14), ends=date(2026, 12, 11))
        self.assertEqual(where_we_are(self.ada, date(2026, 9, 14))["week"], 1)
        solo = make("solo@example.com")
        self.assertEqual(where_we_are(solo, date(2026, 9, 14))["week"], 2)
        self.assertEqual(where_we_are(self.ada, date(2026, 10, 27))["state"], "term")   # their own: no break

    def test_with_no_calendar_nothing_is_claimed(self):
        Term.objects.all().delete()
        self.assertEqual(where_we_are(self.ada, date(2026, 9, 14))["state"], "none")

    def test_term_dates_must_make_sense(self):
        bad = Term(session=self.session, number=3, starts=date(2027, 5, 1), ends=date(2027, 4, 1))
        with self.assertRaises(ValidationError):
            bad.full_clean()

    def test_the_school_admin_shifts_and_resets_their_dates(self):
        self.client.force_login(self.admin)
        with self.on(date(2026, 9, 1)):
            page = self.client.get("/scheme/term-dates/")
            self.assertContains(page, "First Term 2026/2027")
            data = {f"starts-{self.first.pk}": "2026-09-14", f"ends-{self.first.pk}": "2026-12-11",
                    f"starts-{self.second.pk}": "2027-01-05", f"ends-{self.second.pk}": "2027-04-02"}
            self.client.post("/scheme/term-dates/", data)
            own = SchoolTermDates.objects.get(school=self.school)
            self.assertEqual((own.term, own.starts), (self.first, date(2026, 9, 14)))
            self.client.post("/scheme/term-dates/", {**data, f"platform-{self.first.pk}": "on"})
            self.assertFalse(SchoolTermDates.objects.exists())


class SchoolTestTests(YearTestCase):
    def test_a_ca_test_needs_its_level_term_and_number_and_is_sat_once(self):
        with self.assertRaises(ValidationError):
            Assessment(title="CA", kind=Assessment.Kind.CA).full_clean()
        test = Assessment.objects.create(title="CA", kind=Assessment.Kind.CA, level="Level 2", term=1,
                                         ca_number=1, max_attempts=5)
        self.assertEqual(test.max_attempts, 1)
        self.assertEqual(test.slot, "ca1")

    def test_it_opens_and_closes_on_its_dates(self):
        now = timezone.now()
        test = Assessment.objects.create(title="Exam", kind=Assessment.Kind.EXAM, level="Level 2", term=1,
                                         opens_at=now + timedelta(days=1), closes_at=now + timedelta(days=2))
        Question.objects.create(assessment=test, prompt="Pick", options="a\nb", answer="a")
        # A student with no school: a school's students reach tests through
        # their scheme of work (test_timetable.py), which isn't what's tested here.
        pupil = make("loose@example.com", role="student", level="Level 2")
        self.client.force_login(pupil)
        page = self.client.post(f"/assessments/{test.slug}/start/", follow=True)
        self.assertContains(page, "This test opens on")
        Assessment.objects.filter(pk=test.pk).update(opens_at=now - timedelta(days=2), closes_at=now - timedelta(days=1))
        self.assertContains(self.client.post(f"/assessments/{test.slug}/start/", follow=True), "This test has closed")
        Assessment.objects.filter(pk=test.pk).update(closes_at=now + timedelta(days=1))
        self.client.post(f"/assessments/{test.slug}/start/")
        self.assertTrue(Attempt.objects.filter(user=pupil, assessment=test).exists())

    def test_individuals_do_not_see_school_tests(self):
        Assessment.objects.create(title="Exam", kind=Assessment.Kind.EXAM, level="Level 2", term=1)
        self.client.force_login(make("solo@example.com"))
        self.assertNotIn("exam", [k["value"] for k in self.client.get("/assessments/").context["kinds"]])
        self.assertEqual(self.client.get("/assessments/type/exam/").status_code, 404)
        self.client.force_login(make("loose@example.com", role="student", level="Level 2"))
        self.assertIn("exam", [k["value"] for k in self.client.get("/assessments/").context["kinds"]])


class ReportCardTests(YearTestCase):
    def setUp(self):
        super().setUp()
        self.ca1 = Assessment.objects.create(title="CA 1", kind=Assessment.Kind.CA, level="Level 2", term=1, ca_number=1)
        self.ca2 = Assessment.objects.create(title="CA 2", kind=Assessment.Kind.CA, level="Level 2", term=1, ca_number=2)
        self.exam = Assessment.objects.create(title="Exam", kind=Assessment.Kind.EXAM, level="Level 2", term=1)
        when = timezone.make_aware(timezone.datetime(2026, 10, 1, 10, 0))
        for test, status, percent in ((self.ca1, "marked", 80), (self.ca2, "awaiting", 0), (self.exam, "submitted", 70)):
            Attempt.objects.create(user=self.ada, assessment=test, status=status, percent=percent, submitted_at=when)
        self.dated = next(t for t in terms_for(self.school) if t.term == self.first)

    def row(self, pupil):
        return next(r for r in term_results(User.objects.filter(pk=pupil.pk), self.dated))

    def test_the_total_is_weighted_and_graded(self):
        row = self.row(self.ada)
        self.assertEqual((row["ca1"], row["ca2"], row["exam"]), (80, None, 70))
        self.assertEqual(row["pending"], ["ca2"])
        self.assertEqual(row["total"], 58)          # 80×20% + 0×20% + 70×60%
        self.assertEqual(row["grade"], "C")
        self.assertEqual(self.row(self.ben)["missing"], ["ca1", "ca2", "exam"])

    def test_grades_follow_the_boundaries(self):
        grading = Grading.load()
        self.assertEqual([grading.grade(n) for n in (70, 69, 50, 45, 40, 39)], ["A", "B", "C", "D", "E", "F"])

    def test_the_teacher_comments_and_the_admin_publishes_a_frozen_copy(self):
        self.client.force_login(self.teacher)
        with self.on(date(2026, 12, 14)):
            page = self.client.get("/scheme/reports/")
            self.assertContains(page, "First Term 2026/2027")
            self.client.post("/scheme/reports/", {"term": self.first.pk, f"comment-{self.ada.pk}": "A good term."})
            self.assertEqual(self.client.post("/scheme/reports/", {"term": self.first.pk, "action": "publish"}).status_code, 403)
            self.client.force_login(self.admin)
            self.client.post("/scheme/reports/", {"term": self.first.pk, "action": "publish"})
        card = ReportCard.objects.get(student=self.ada, term=self.first)
        self.assertEqual((card.total, card.grade, card.teacher_comment), (58, "C", "A good term."))
        self.assertIsNotNone(card.published_at)
        # Marking CA 2 afterwards doesn't change a published card.
        Attempt.objects.filter(assessment=self.ca2).update(status="marked", percent=100)
        self.assertEqual(self.row(self.ada)["total"], 58)

    def test_who_can_open_a_card(self):
        url = f"/scheme/reports/{self.first.pk}/{self.ada.pk}/"
        other = make("other@example.com", role="teacher", school=self.school, level="Level 5")
        self.client.force_login(other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.teacher)
        self.assertContains(self.client.get(url), "Draft, not published yet")
        self.client.force_login(self.ada)
        self.assertEqual(self.client.get(url).status_code, 404)           # not published yet

        publish(self.admin, term_results(User.objects.filter(pk=self.ada.pk), self.dated), self.dated)
        self.assertRedirects(self.client.get(url), "/accounts/grown-ups/", fetch_redirect_response=False)
        self.client.post("/accounts/grown-ups/", {"action": "set", "pin": "2468", "pin2": "2468"})
        page = self.client.get("/accounts/grown-ups/")
        self.assertContains(page, "data-report-cards")
        self.assertContains(self.client.get(url), "Report card")
        session = self.client.session
        session.pop(grown_ups.SESSION_KEY)
        session.save()
        self.assertRedirects(self.client.get(url), "/accounts/grown-ups/", fetch_redirect_response=False)

    def test_a_whole_class_costs_the_same_as_two(self):
        Grading.load()          # made on first use; not part of what's measured
        with CaptureQueriesContext(connection) as few:
            term_results(User.objects.filter(role="student"), self.dated)
        for n in range(10):
            make(f"kid{n}@example.com", role="student", school=self.school, level="Level 2")
        with CaptureQueriesContext(connection) as many:
            rows = term_results(User.objects.filter(role="student"), self.dated)
        self.assertEqual(len(rows), 12)
        self.assertEqual(len(few), len(many))


class PromotionTests(YearTestCase):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        ReportCard.objects.create(student=self.ada, term=self.first, total=65, published_at=now)
        ReportCard.objects.create(student=self.ada, term=self.second, total=71, published_at=now)
        ReportCard.objects.create(student=self.ben, term=self.first, total=40, published_at=now)
        ReportCard.objects.create(student=self.ben, term=self.second, total=90)          # not published: ignored

    def test_students_at_the_mark_are_suggested_and_the_admin_decides(self):
        self.client.force_login(self.admin)
        with self.on(date(2027, 4, 10)):
            page = self.client.get("/scheme/promote/")
            rows = {r["student"].pk: r for r in page.context["rows"]}
            self.assertEqual((rows[self.ada.pk]["average"], rows[self.ada.pk]["suggested"]), (68, True))
            self.assertEqual((rows[self.ben.pk]["average"], rows[self.ben.pk]["suggested"]), (40, False))
            response = self.client.post("/scheme/promote/", {"students": [self.ada.pk]}, follow=True)
        self.assertContains(response, "1 student promoted")
        self.ada.refresh_from_db()
        self.ben.refresh_from_db()
        self.assertEqual((self.ada.level, self.ben.level), ("Level 3", "Level 2"))
        self.assertTrue(LevelChange.objects.filter(member=self.ada, old_level="Level 2", new_level="Level 3").exists())

    def test_only_the_school_admin_promotes(self):
        self.client.force_login(self.teacher)
        self.assertRedirects(self.client.get("/scheme/promote/"), "/", fetch_redirect_response=False)
