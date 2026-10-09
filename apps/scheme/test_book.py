"""The scheme the way the book is written (builder.book_plan): a level's
EchoSpell Group 1 is Week 1, its cards one a day, its activities on Friday.
And the two builders sharing a draft: the book's EchoSpell, the AI's
Learning Modules, 44 Academy and Tricks, each leaving the other's alone."""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.echospell.models import (
    Activity, ActivityAttempt, ActivityItem, CardLesson, Category, Dialogue, Group, Level, Passage,
)

from apps.learning_modules.models import Day, LearningModule, Term as ModuleTerm, Week

from .builder import MAX_PER_DAY, book_plan
from .models import SchemeEntry
from .tests import YearTestCase, make
from .timetable import timetable

User = get_user_model()
TUESDAY_WEEK_1 = date(2026, 9, 8)


class BookCase(YearTestCase):
    def setUp(self):
        super().setUp()
        Group.objects.all().delete()
        self.level, _ = Level.objects.update_or_create(name="Level 2", defaults={"is_published": True})
        self.cats = [
            Category.objects.create(name="Book Spelling", kind="words", order=1),
            Category.objects.create(name="Book Passage", kind="passage", order=2),
            Category.objects.create(name="Book Dialogue", kind="dialogue", order=3),
            Category.objects.create(name="Book Vocabulary", kind="words", order=4),
        ]
        self.level.categories.set(self.cats)
        spelling, passage, dialogue, vocab = self.cats
        self.g1, self.g2, self.g3 = [Group.objects.create(level=self.level, number=n, slug=f"bk{n}") for n in (1, 2, 3)]
        CardLesson.objects.create(group=self.g1, category=spelling, word="Goat")
        CardLesson.objects.create(group=self.g1, category=vocab, word="Coat")
        Passage.objects.create(group=self.g1, title="The goat")
        Dialogue.objects.create(group=self.g1, title="At the farm")
        self.spell = Activity.objects.create(group=self.g1, kind="dictation", title="Spell it", pass_mark=100)
        ActivityItem.objects.create(activity=self.spell, answer="goat")
        CardLesson.objects.create(group=self.g2, category=spelling, word="Boat")
        CardLesson.objects.create(group=self.g3, category=spelling, word="Moat")
        self.terms = [{"number": 1, "weeks": 2, "break_after": 0}, {"number": 2, "weeks": 5, "break_after": 0}]

    def placed(self, plan, term, week):
        return [(d, i) for t, w, d, i in plan if (t, w) == (term, week)]


class BookPlanTests(BookCase):
    def test_group_one_is_week_one_cards_a_day_activities_friday(self):
        spelling, passage, dialogue, vocab = self.cats
        plan = book_plan("Level 2", self.terms)
        self.assertEqual(self.placed(plan, 1, 1), [
            ("monday", f"card:{self.g1.pk}-{spelling.pk}"),
            ("tuesday", f"card:{self.g1.pk}-{passage.pk}"),
            ("wednesday", f"card:{self.g1.pk}-{dialogue.pk}"),
            ("thursday", f"card:{self.g1.pk}-{vocab.pk}"),
            ("friday", f"activity:{self.spell.pk}"),
        ])
        # Group 2 has no activities: nothing on Friday. The book is EchoSpell only.
        self.assertEqual(self.placed(plan, 1, 2), [("monday", f"card:{self.g2.pk}-{spelling.pk}")])
        # Groups run on into the next term.
        self.assertEqual(self.placed(plan, 2, 1)[0], ("monday", f"card:{self.g3.pk}-{spelling.pk}"))
        self.assertEqual(self.placed(plan, 2, 2), [])                     # no Group 4 yet

    def test_more_than_four_cards_go_two_a_day(self):
        extra = Category.objects.create(name="Book Puzzle", kind="words", order=5)
        self.level.categories.add(extra)
        CardLesson.objects.create(group=self.g1, category=extra, word="Goat")
        days = [d for d, i in self.placed(book_plan("Level 2", self.terms), 1, 1) if i.startswith("card:")]
        self.assertEqual(len(days), 5)
        self.assertTrue(all(days.count(d) <= 2 for d in set(days)))
        self.assertNotIn("friday", days)


class BookSchemeTests(BookCase):
    def build_and_publish(self):
        self.client.force_login(make("staff@example.com", is_staff=True))
        base = {"level": "Level 2", "term": "1"}
        response = self.client.post("/manage/scheme-of-work/", {**base, "action": "book"}, follow=True)
        self.assertContains(response, "Draft ready for Level 2: 3 EchoSpell groups laid out as 3 weeks")
        self.assertContains(response, "Book Spelling, Group 1")
        for term in ("1", "2"):
            self.client.post("/manage/scheme-of-work/", {"level": "Level 2", "term": term, "action": "publish"})

    def test_built_from_the_book_and_seen_by_the_student(self):
        self.build_and_publish()
        week = timetable(self.ada, TUESDAY_WEEK_1)
        self.assertEqual([r["title"] for r in week["rows"]][:2], ["Book Spelling, Group 1", "Book Passage, Group 1"])
        self.assertEqual(week["next"]["title"], "Book Passage, Group 1")      # Tuesday's card
        self.assertIn("Spell it, Group 1", [r["title"] for r in week["rows"]])

    def test_ticks_from_opening_the_card_and_passing_the_activity(self):
        self.build_and_publish()
        self.client.force_login(self.ada)
        with self.on(TUESDAY_WEEK_1):
            card = SchemeEntry.objects.get(kind="card", group=self.g1, category=self.cats[1])
            self.assertRedirects(self.client.get(f"/scheme/go/{card.pk}/"),
                                 f"/echospell/{self.level.slug}/{self.g1.slug}/{self.cats[1].slug}/",
                                 fetch_redirect_response=False)
            self.client.get(f"/echospell/{self.level.slug}/{self.g1.slug}/{self.cats[1].slug}/")
        ActivityAttempt.objects.create(user=self.ada, activity=self.spell, status="marked", percent=100, passed=True)
        done = {r["title"]: r["done"] for r in timetable(self.ada, TUESDAY_WEEK_1)["rows"]}
        self.assertTrue(done["Book Passage, Group 1"])
        self.assertTrue(done["Spell it, Group 1"])
        self.assertFalse(done["Book Spelling, Group 1"])

    def test_a_later_weeks_group_stays_shut(self):
        self.build_and_publish()
        self.client.force_login(self.ada)
        with self.on(TUESDAY_WEEK_1):
            self.assertEqual(self.client.get(f"/echospell/{self.level.slug}/{self.g1.slug}/").status_code, 200)
            self.assertEqual(self.client.get(f"/echospell/{self.level.slug}/{self.g2.slug}/").status_code, 403)

    @override_settings(OPENAI_API_KEY="")
    def test_cards_can_be_added_one_by_one_too(self):
        self.client.force_login(make("staff@example.com", is_staff=True))
        page = self.client.get("/manage/scheme-of-work/?level=Level 2&term=1")
        self.assertContains(page, f'value="card:{self.g1.pk}-{self.cats[0].pk}"')
        self.assertContains(page, f'value="activity:{self.spell.pk}"')
        self.client.post("/manage/scheme-of-work/", {"level": "Level 2", "term": "1", "action": "add", "week": "3",
                                                     "day": "monday", "content": f"card:{self.g2.pk}-{self.cats[0].pk}"})
        entry = SchemeEntry.objects.get(week=3)
        self.assertEqual((entry.kind, entry.group, entry.category), ("card", self.g2, self.cats[0]))


@override_settings(OPENAI_API_KEY="")
class TwoBuildersTests(BookCase):
    url = "/manage/scheme-of-work/"

    def setUp(self):
        super().setUp()
        LearningModule.objects.all().delete()
        week = Week.objects.create(term=ModuleTerm.objects.create(
            module=LearningModule.objects.create(name="Sounds", slug="sounds"), name="First Term"), number=1)
        for day in ("monday", "tuesday", "wednesday", "thursday", "friday"):
            Day.objects.create(week=week, day_name=day)
        self.client.force_login(make("staff@example.com", is_staff=True))

    def post(self, action, term="1", **extra):
        return self.client.post(self.url, {"level": "Level 2", "term": term, "action": action, **extra}, follow=True)

    def kinds(self, **filters):
        return sorted(SchemeEntry.objects.filter(level="Level 2", **filters).values_list("kind", flat=True))

    def test_each_builder_replaces_only_its_own_part(self):
        self.post("book")
        self.post("build", scope="year")
        both = self.kinds(is_draft=True)
        self.assertIn("card", both)
        self.assertIn("module_day", both)
        # Building from the book again keeps the modules, and the AI again keeps the cards.
        self.post("book")
        self.assertEqual(self.kinds(is_draft=True), both)
        self.assertContains(self.post("build", scope="year"), "around the EchoSpell lessons")
        self.assertEqual(self.kinds(is_draft=True), both)
        self.assertNotIn("daily_practice", both)

    def test_the_ai_fits_around_the_books_days(self):
        self.post("book")
        self.post("build", scope="term")
        per_day = {}
        for entry in SchemeEntry.objects.filter(is_draft=True, term=1, week=1):
            per_day[entry.day] = per_day.get(entry.day, 0) + 1
        self.assertTrue(all(n <= MAX_PER_DAY for n in per_day.values()), per_day)
        monday = list(SchemeEntry.objects.filter(is_draft=True, term=1, week=1, day="monday").order_by("order"))
        self.assertEqual([e.kind for e in monday], ["card", "module_day"])      # the book's card first

    def test_a_build_starts_from_the_live_scheme(self):
        self.post("book")
        self.post("publish", term="1")
        live = self.kinds(is_draft=False, term=1)
        self.post("build", scope="term")
        self.assertEqual(self.kinds(is_draft=False, term=1), live)               # live untouched until published
        self.assertEqual([k for k in self.kinds(is_draft=True, term=1) if k in ("card", "activity")], live)
        self.post("publish", term="1")
        self.assertIn("module_day", self.kinds(is_draft=False, term=1))
        self.assertIn("card", self.kinds(is_draft=False, term=1))
