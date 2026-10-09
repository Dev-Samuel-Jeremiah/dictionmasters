"""The scheme the way the book is written (builder.book_plan): a level's
EchoSpell Group 1 is Week 1, its cards one a day, its activities on Friday."""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.echospell.models import (
    Activity, ActivityAttempt, ActivityItem, CardLesson, Category, Dialogue, Group, Level, Passage,
)

from .builder import book_plan
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
        # Group 2 has no activities: Daily Practice on Friday.
        self.assertEqual(self.placed(plan, 1, 2), [("monday", f"card:{self.g2.pk}-{spelling.pk}"),
                                                    ("friday", "daily_practice:")])
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
