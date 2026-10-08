"""The scheme builder (apps/scheme/builder.py), the draft it makes, the
control room's Calendar, and the school admin's view of the scheme. OpenAI
is never called: its answers are faked."""

import io
import json
from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.assessments.models import Assessment
from apps.echospell.models import Group, Level
from apps.learning_modules.models import Day, LearningModule, Term as ModuleTerm, Week

from . import builder
from .models import SchemeEntry, SchoolTermDates, Session, Term
from .tests import YearTestCase, make
from .timetable import timetable

User = get_user_model()
TERM_1 = [{"number": 1, "weeks": 12, "break_after": 6}]


class BuilderCase(YearTestCase):
    def setUp(self):
        super().setUp()
        Group.objects.all().delete()
        LearningModule.objects.all().delete()
        level, _ = Level.objects.update_or_create(name="Level 2", defaults={"is_published": True})
        self.groups = [Group.objects.create(level=level, number=n, slug=f"b{n}") for n in range(1, 6)]
        module = LearningModule.objects.create(name="Sounds", slug="sounds")
        other = LearningModule.objects.create(name="Big words", slug="big-words", levels=",Level 9,")
        self.days = []
        for module_ in (module, other):
            mterm = ModuleTerm.objects.create(module=module_, name="First Term")
            for n in (1, 2, 3):
                week = Week.objects.create(term=mterm, number=n)
                for day in ("monday", "tuesday", "wednesday", "thursday", "friday"):
                    made = Day.objects.create(week=week, day_name=day)
                    if module_ is module:
                        self.days.append(made)
        self.ca1 = Assessment.objects.create(title="CA 1", kind="ca", level="Level 2", term=1, ca_number=1)
        self.ca2 = Assessment.objects.create(title="CA 2", kind="ca", level="Level 2", term=1, ca_number=2)
        self.exam = Assessment.objects.create(title="Exam", kind="exam", level="Level 2", term=1)
        Assessment.objects.create(title="Second term CA", kind="ca", level="Level 2", term=2, ca_number=1)


class CatalogueAndCheckTests(BuilderCase):
    def test_the_catalogue_is_the_levels_content_in_order(self):
        items = builder.catalogue("Level 2", TERM_1)
        self.assertEqual([i["id"] for i in items["group"]], [f"group:{g.pk}" for g in self.groups])
        self.assertEqual(len(items["module_day"]), 15)                 # not the Level 9 module
        self.assertEqual({i["title"] for i in items["assessment"]}, {"CA 1", "CA 2", "Exam"})
        self.assertIn("daily_practice", items)

    def test_only_real_placements_survive(self):
        items = builder.catalogue("Level 2", TERM_1)
        g = f"group:{self.groups[0].pk}"
        kept = builder.clean_plan([
            {"term": 1, "week": 1, "day": "monday", "item": g},
            {"term": 1, "week": 1, "day": "monday", "item": g},                  # again
            {"term": 1, "week": 13, "day": "monday", "item": g},                 # past the term
            {"term": 2, "week": 1, "day": "monday", "item": g},                  # a term not asked for
            {"term": 1, "week": 2, "day": "saturday", "item": g},                # not a school day
            {"term": 1, "week": 2, "day": "any", "item": "group:999999"},        # not in the catalogue
            {"term": 1, "week": 3, "day": "friday", "item": "daily_practice:"},
            {"term": 1, "week": "x", "day": "monday", "item": g},
        ], items, TERM_1)
        self.assertEqual(kept, [(1, 1, "monday", g), (1, 3, "friday", "daily_practice:")])

    def test_at_most_three_a_day(self):
        items = builder.catalogue("Level 2", TERM_1)
        plan = [{"term": 1, "week": 1, "day": "monday", "item": f"group:{g.pk}"} for g in self.groups]
        self.assertEqual(len(builder.clean_plan(plan, items, TERM_1)), 3)


class RulePlanTests(BuilderCase):
    def test_every_school_day_has_something_and_the_tests_land_well(self):
        items = builder.catalogue("Level 2", TERM_1)
        kept = builder.clean_plan(builder.rule_plan(TERM_1, items), items, TERM_1)
        for week in range(1, 13):
            days = {d for t, w, d, i in kept if w == week}
            self.assertTrue({"friday"} <= days, week)                        # Daily Practice at least
        self.assertIn((1, 5, "thursday", f"assessment:{self.ca1.pk}"), kept)
        self.assertIn((1, 9, "thursday", f"assessment:{self.ca2.pk}"), kept)
        self.assertIn((1, 12, "wednesday", f"assessment:{self.exam.pk}"), kept)
        # Courses keep their order: group 1 before group 2 ...
        weeks = {}
        for t, w, d, i in kept:
            if i.startswith("group:"):
                weeks.setdefault(i, w)                                       # first time it's taught
        self.assertEqual(sorted(weeks, key=weeks.get), [f"group:{g.pk}" for g in self.groups])
        # The revision week (11) brings no new course content.
        new = {i for t, w, d, i in kept if w < 11}
        self.assertTrue({i for t, w, d, i in kept if w == 11 and i != "daily_practice:"} <= new)


class BuildTests(BuilderCase):
    @override_settings(OPENAI_API_KEY="")
    def test_with_no_key_the_draft_is_planned_by_rule_and_students_see_nothing(self):
        result = builder.build("Level 2", TERM_1)
        self.assertEqual(result["source"], "rules")
        self.assertIn("No OpenAI key", result["message"])
        self.assertTrue(SchemeEntry.objects.filter(is_draft=True).exists())
        self.assertFalse(SchemeEntry.objects.filter(is_draft=False).exists())
        self.assertEqual(timetable(self.ada, date(2026, 9, 8))["state"], "empty")

    @override_settings(OPENAI_API_KEY="test-key", OPENAI_MODEL="gpt-test")
    def test_the_ai_plan_is_checked_and_saved_as_the_draft(self):
        g1, g2 = (f"group:{g.pk}" for g in self.groups[:2])
        answer = {"entries": [
            {"term": 1, "week": 1, "day": "monday", "item": g1},
            {"term": 1, "week": 2, "day": "any", "item": g2},
            {"term": 1, "week": 2, "day": "monday", "item": "group:999999"},
        ]}
        reply = {"choices": [{"message": {"content": json.dumps(answer)}}]}
        sent = {}

        def fake_urlopen(request, timeout):
            sent["body"] = json.loads(request.data)
            return io.BytesIO(json.dumps(reply).encode())

        with mock.patch("apps.scheme.builder.urllib.request.urlopen", fake_urlopen):
            result = builder.build("Level 2", TERM_1, note="Vowels first")
        self.assertEqual((result["source"], result["count"]), ("ai", 2))
        self.assertEqual(sent["body"]["model"], "gpt-test")
        self.assertEqual(sent["body"]["response_format"]["json_schema"]["name"], "scheme_of_work")
        self.assertIn("Vowels first", sent["body"]["messages"][1]["content"])
        self.assertEqual(list(SchemeEntry.objects.filter(is_draft=True).order_by("week").values_list("week", "day")),
                         [(1, "monday"), (2, "")])

    @override_settings(OPENAI_API_KEY="test-key")
    def test_an_ai_failure_falls_back_to_the_rules(self):
        with mock.patch("apps.scheme.builder.ai_plan", side_effect=builder.PlanError("down")):
            result = builder.build("Level 2", TERM_1)
        self.assertEqual(result["source"], "rules")
        self.assertIn("didn't answer", result["message"])
        self.assertGreater(result["count"], 0)

    def test_a_level_with_nothing_to_teach(self):
        Assessment.objects.all().delete()
        # No groups or modules of its own, but the shared courses (44 Academy,
        # recitals, the library) and Daily Practice still make a plan…
        result = builder.build("Level 11", TERM_1, use_ai=False)
        self.assertGreater(result["count"], 0)
        self.assertFalse(SchemeEntry.objects.filter(level="Level 11", kind="group").exists())
        # …and a level with truly nothing gives a clear message.
        with mock.patch("apps.scheme.builder.catalogue", return_value={}):
            self.assertIn("no content", builder.build("Level 11", TERM_1)["message"])


class EditorDraftTests(BuilderCase):
    url = "/manage/scheme-of-work/"

    def setUp(self):
        super().setUp()
        self.client.force_login(make("staff@example.com", is_staff=True))
        self.base = {"level": "Level 2", "term": "1"}
        self.live = SchemeEntry.objects.create(level="Level 2", term=1, week=1, day="monday", kind="group",
                                               group=self.groups[4])

    @override_settings(OPENAI_API_KEY="")
    def test_build_check_edit_and_publish(self):
        response = self.client.post(self.url, {**self.base, "action": "build", "scope": "term"}, follow=True)
        self.assertContains(response, "Draft ready for Level 2")
        self.assertContains(response, "data-scheme-draft")
        drafts = SchemeEntry.objects.filter(is_draft=True).count()
        # Editing works on the draft, not the live scheme.
        self.client.post(self.url, {**self.base, "view": "draft", "action": "add", "week": "3", "day": "friday",
                                    "content": "daily_practice:"})
        self.assertEqual(SchemeEntry.objects.filter(is_draft=True).count(), drafts + 1)
        self.assertTrue(SchemeEntry.objects.filter(pk=self.live.pk, is_draft=False).exists())
        # Publishing replaces the live scheme.
        self.client.post(self.url, {**self.base, "action": "publish"})
        self.assertFalse(SchemeEntry.objects.filter(pk=self.live.pk).exists())
        self.assertEqual(SchemeEntry.objects.filter(is_draft=False).count(), drafts + 1)
        self.assertFalse(SchemeEntry.objects.filter(is_draft=True).exists())

    @override_settings(OPENAI_API_KEY="")
    def test_discard_leaves_the_live_scheme(self):
        self.client.post(self.url, {**self.base, "action": "build", "scope": "year"})
        self.assertTrue(SchemeEntry.objects.filter(is_draft=True, term=3).exists())
        self.client.post(self.url, {**self.base, "action": "discard"})
        self.assertFalse(SchemeEntry.objects.filter(is_draft=True, term=1).exists())
        self.assertTrue(SchemeEntry.objects.filter(pk=self.live.pk, is_draft=False).exists())

    def test_the_year_build_uses_the_calendars_weeks(self):
        specs = __import__("apps.manage.scheme_editor", fromlist=["_term_specs"])._term_specs([1, 2])
        self.assertEqual(specs, [{"number": 1, "weeks": 13, "break_after": 7},
                                 {"number": 2, "weeks": 13, "break_after": 0}])


class CalendarTests(YearTestCase):
    url = "/manage/calendar/"

    def setUp(self):
        super().setUp()
        self.client.force_login(make("staff@example.com", is_staff=True))

    def test_a_term_is_set_by_its_weeks(self):
        page = self.client.get(self.url)
        self.assertContains(page, "School year 2026/2027")
        self.client.post(self.url, {"action": "save_term", "year": self.session.pk, "number": 3,
                                    "starts": "2027-04-26", "weeks": "12", "break_after": "6"})
        third = Term.objects.get(session=self.session, number=3)
        self.assertEqual((third.ends, third.break_starts, third.break_ends),
                         (date(2027, 7, 23), date(2027, 6, 7), date(2027, 6, 11)))
        self.assertContains(self.client.get(f"{self.url}?year={self.session.pk}"), "Week 7")

    def test_a_new_school_year(self):
        self.client.post(self.url, {"action": "add_year", "name": "2027/2028"})
        self.assertTrue(Session.objects.filter(name="2027/2028").exists())

    def test_only_staff(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 302)


class SchoolAdminTests(YearTestCase):
    def test_the_school_sets_its_terms_by_weeks(self):
        self.client.force_login(self.admin)
        with self.on(date(2026, 9, 1)):
            self.client.post("/scheme/term-dates/", {
                f"starts-{self.first.pk}": "2026-09-21", f"ends-{self.first.pk}": "2026-12-11",
                f"by_weeks-{self.first.pk}": "on", f"weeks-{self.first.pk}": "10", f"break_after-{self.first.pk}": "5",
                f"starts-{self.second.pk}": "2027-01-05", f"ends-{self.second.pk}": "2027-04-02",
            })
        own = SchoolTermDates.objects.get(school=self.school, term=self.first)
        self.assertEqual((own.starts, own.ends, own.break_starts), (date(2026, 9, 21), date(2026, 12, 4), date(2026, 10, 26)))

    def test_the_school_sees_the_live_scheme_only(self):
        level, _ = Level.objects.update_or_create(name="Level 2", defaults={"is_published": True})
        group = Group.objects.create(level=level, number=7, slug="s7")
        SchemeEntry.objects.create(level="Level 2", term=1, week=2, day="tuesday", kind="group", group=group)
        SchemeEntry.objects.create(level="Level 2", term=1, week=3, day="tuesday", kind="daily_practice", is_draft=True)
        self.client.force_login(self.admin)
        page = self.client.get("/scheme/school/?level=Level 2&term=1")
        self.assertContains(page, "EchoSpell Group 7")
        self.assertContains(page, "from Mon 14 Sep")
        self.assertNotContains(page, "Daily Practice")
        self.assertContains(self.client.get("/school/dashboard/"), 'href="/scheme/school/"')

    def test_only_the_school_admin(self):
        self.client.force_login(self.teacher)
        self.assertRedirects(self.client.get("/scheme/school/"), "/", fetch_redirect_response=False)
