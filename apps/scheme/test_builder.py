"""The scheme builder with AI (apps/scheme/builder.py: Learning Modules,
the 44 Academy and Tricks), the draft it makes, the control room's
Calendar, and the school admin's view of the scheme. OpenAI is never
called: its answers are faked. Its sharing the draft with Build from the
book is in test_book.py."""

import io
import json
from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.book.models import ACADEMY, TRICKS, Sound, SoundCategory
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
        Sound.objects.all().delete()
        academy = SoundCategory.objects.create(name="Vowels", programme=ACADEMY)
        tricks = SoundCategory.objects.create(name="Tricks", programme=TRICKS)
        self.sounds = [Sound.objects.create(category=academy, name=f"Sound {n}", slug=f"sb{n}", order=n, is_published=True)
                       for n in range(1, 5)]
        self.tricks = [Sound.objects.create(category=tricks, name=f"Trick {n}", slug=f"tb{n}", order=n, is_published=True)
                       for n in range(1, 3)]

    def ids(self, kind, found):
        return [f"{kind}:{x.pk}" for x in found]


class CatalogueAndCheckTests(BuilderCase):
    def test_the_catalogue_is_the_three_courses_in_order(self):
        items = builder.catalogue("Level 2", TERM_1)
        self.assertEqual(set(items), {"module_day", "sound", "trick"})        # not EchoSpell, recitals, …
        self.assertEqual([i["id"] for i in items["module_day"]], self.ids("module_day", self.days))   # not Level 9's
        self.assertEqual([i["id"] for i in items["sound"]], self.ids("sound", self.sounds))
        self.assertEqual([i["id"] for i in items["trick"]], self.ids("trick", self.tricks))

    def test_only_real_placements_survive(self):
        items = builder.catalogue("Level 2", TERM_1)
        m, s = f"module_day:{self.days[0].pk}", f"sound:{self.sounds[0].pk}"
        kept = builder.clean_plan([
            {"term": 1, "week": 1, "day": "monday", "item": m},
            {"term": 1, "week": 1, "day": "monday", "item": m},                  # again
            {"term": 1, "week": 13, "day": "monday", "item": m},                 # past the term
            {"term": 2, "week": 1, "day": "monday", "item": m},                  # a term not asked for
            {"term": 1, "week": 2, "day": "saturday", "item": m},                # not a school day
            {"term": 1, "week": 2, "day": "any", "item": f"group:{self.groups[0].pk}"},   # the book's part
            {"term": 1, "week": 3, "day": "any", "item": s},
            {"term": 1, "week": "x", "day": "monday", "item": m},
        ], items, TERM_1)
        self.assertEqual(kept, [(1, 1, "monday", m), (1, 3, "", s)])

    def test_at_most_three_a_day_counting_the_books_lessons(self):
        items = builder.catalogue("Level 2", TERM_1)
        plan = [{"term": 1, "week": 1, "day": "monday", "item": i} for i in self.ids("sound", self.sounds)]
        self.assertEqual(len(builder.clean_plan(plan, items, TERM_1)), 3)
        self.assertEqual(len(builder.clean_plan(plan, items, TERM_1, {(1, 1, "monday"): 2})), 1)
        # The Learning Modules day, the daily course, is never squeezed out.
        day = [{"term": 1, "week": 1, "day": "monday", "item": f"module_day:{self.days[0].pk}"}]
        self.assertEqual(len(builder.clean_plan(day, items, TERM_1, {(1, 1, "monday"): 3})), 1)


class RulePlanTests(BuilderCase):
    def test_a_module_day_each_school_day_and_a_sound_and_a_trick_a_week(self):
        items = builder.catalogue("Level 2", TERM_1)
        kept = builder.clean_plan(builder.rule_plan(TERM_1, items), items, TERM_1)
        week_1 = [(d, i) for t, w, d, i in kept if w == 1]
        self.assertEqual([i for d, i in week_1 if i.startswith("module_day:")], self.ids("module_day", self.days[:5]))
        # A sound and a trick from week 1, side by side…
        self.assertEqual([(d, i) for d, i in week_1 if i.startswith(("sound:", "trick:"))],
                         [("tuesday", f"sound:{self.sounds[0].pk}"), ("thursday", f"trick:{self.tricks[0].pk}")])
        self.assertIn((1, 2, "thursday", f"trick:{self.tricks[1].pk}"), kept)
        # …and once the tricks are done, two sounds a week.
        self.assertEqual([i for t, w, d, i in kept if w == 3 and i.startswith("sound:")], self.ids("sound", self.sounds[2:]))
        # The revision week (11) brings nothing new.
        new = {i for t, w, d, i in kept if w < 11}
        self.assertTrue({i for t, w, d, i in kept if w == 11} <= new)

    def test_it_fits_around_the_books_days(self):
        items = builder.catalogue("Level 2", TERM_1)
        taken = {(1, 1, "monday"): 3, (1, 1, "tuesday"): 2}
        kept = builder.clean_plan(builder.rule_plan(TERM_1, items, taken), items, TERM_1, taken)
        week_1 = {}
        for t, w, d, i in kept:
            if w == 1:
                week_1.setdefault(d, []).append(i)
        # The module day still comes every day, in order, on a full day too…
        self.assertEqual([week_1[d][0] for d in ("monday", "tuesday", "wednesday", "thursday", "friday")],
                         self.ids("module_day", self.days[:5]))
        self.assertEqual(week_1["monday"], [f"module_day:{self.days[0].pk}"])
        # …and the sound takes Tuesday's last place.
        self.assertEqual(week_1["tuesday"], self.ids("module_day", self.days[1:2]) + self.ids("sound", self.sounds[:1]))
        taken[(1, 1, "thursday")] = 3                                          # no room: the lightest day
        kept = builder.clean_plan(builder.rule_plan(TERM_1, items, taken), items, TERM_1, taken)
        self.assertIn((1, 1, "wednesday", f"trick:{self.tricks[0].pk}"), kept)


class BuildTests(BuilderCase):
    @override_settings(OPENAI_API_KEY="")
    def test_with_no_key_the_draft_is_planned_by_rule_and_students_see_nothing(self):
        result = builder.build("Level 2", TERM_1)
        self.assertEqual(result["source"], "rules")
        self.assertIn("No OpenAI key", result["message"])
        self.assertEqual(set(SchemeEntry.objects.filter(is_draft=True).values_list("kind", flat=True)),
                         {"module_day", "sound", "trick"})
        self.assertFalse(SchemeEntry.objects.filter(is_draft=False).exists())
        self.assertEqual(timetable(self.ada, date(2026, 9, 8))["state"], "empty")

    @override_settings(OPENAI_API_KEY="test-key", OPENAI_MODEL="gpt-test")
    def test_the_ai_plan_is_checked_and_saved_as_the_draft(self):
        m1, m2 = self.ids("module_day", self.days[:2])
        answer = {"entries": [
            {"term": 1, "week": 1, "day": "monday", "item": m1},
            {"term": 1, "week": 2, "day": "any", "item": m2},
            {"term": 1, "week": 2, "day": "monday", "item": f"group:{self.groups[0].pk}"},   # not the AI's to place
        ]}
        reply = {"choices": [{"message": {"content": json.dumps(answer)}}]}
        sent = {}

        def fake_urlopen(request, timeout):
            sent["body"] = json.loads(request.data)
            return io.BytesIO(json.dumps(reply).encode())

        SchemeEntry.objects.create(level="Level 2", term=1, week=1, day="monday", kind="group", group=self.groups[0])
        with mock.patch("apps.scheme.builder.urllib.request.urlopen", fake_urlopen):
            result = builder.build("Level 2", TERM_1, note="Vowels first")
        self.assertEqual((result["source"], result["count"]), ("ai", 2))
        self.assertEqual(sent["body"]["model"], "gpt-test")
        self.assertEqual(sent["body"]["response_format"]["json_schema"]["name"], "scheme_of_work")
        told = json.loads(sent["body"]["messages"][1]["content"])
        self.assertEqual(told["planner_note"], "Vowels first")
        self.assertEqual(told["echospell_lessons_per_day"], [{"term": 1, "week": 1, "day": "monday", "lessons": 1}])
        self.assertEqual(list(SchemeEntry.objects.filter(is_draft=True, kind="module_day").order_by("week")
                              .values_list("week", "day")), [(1, "monday"), (2, "")])

    @override_settings(OPENAI_API_KEY="test-key")
    def test_an_ai_failure_falls_back_to_the_rules(self):
        with mock.patch("apps.scheme.builder.ai_plan", side_effect=builder.PlanError("down")):
            result = builder.build("Level 2", TERM_1)
        self.assertEqual(result["source"], "rules")
        self.assertIn("didn't answer", result["message"])
        self.assertGreater(result["count"], 0)

    def test_a_level_with_nothing_to_teach(self):
        # No module of its own, but the shared ones, the 44 Academy and Tricks…
        result = builder.build("Level 11", TERM_1, use_ai=False)
        self.assertGreater(result["count"], 0)
        self.assertFalse(SchemeEntry.objects.filter(level="Level 11", module_day__week__term__module__slug="big-words").exists())
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
                                    "content": f"module_day:{self.days[0].pk}"})
        self.assertEqual(SchemeEntry.objects.filter(is_draft=True).count(), drafts + 1)
        self.assertTrue(SchemeEntry.objects.filter(pk=self.live.pk, is_draft=False).exists())
        # The draft started from the live scheme's EchoSpell…
        self.assertTrue(SchemeEntry.objects.filter(is_draft=True, kind="group", group=self.groups[4]).exists())
        # …and publishing replaces the live scheme, EchoSpell still on it.
        self.client.post(self.url, {**self.base, "action": "publish"})
        self.assertFalse(SchemeEntry.objects.filter(pk=self.live.pk).exists())
        self.assertEqual(SchemeEntry.objects.filter(is_draft=False).count(), drafts + 1)
        self.assertTrue(SchemeEntry.objects.filter(is_draft=False, kind="group", group=self.groups[4]).exists())
        self.assertFalse(SchemeEntry.objects.filter(is_draft=True).exists())

    @override_settings(OPENAI_API_KEY="")
    def test_discard_leaves_the_live_scheme(self):
        self.client.post(self.url, {**self.base, "action": "build", "scope": "year"})
        self.assertTrue(SchemeEntry.objects.filter(is_draft=True, term=1).exists())
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
