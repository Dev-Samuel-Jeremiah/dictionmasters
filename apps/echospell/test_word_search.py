"""Word search: the grid made from an activity's words, and marking what the
learner finds."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from .activity_kinds import get_kind
from .marking import feedback_for, mark_response
from .models import Activity, ActivityAttempt, ActivityItem, Group, Level
from .word_search import DIRECTIONS, build, letters_of

User = get_user_model()

WORDS = "accolade cohesion cruel debris bosom chameleon extravagant gesture incumbent army".split()


def hidden(rows, word):
    """Is `word` in the grid, running across, down or diagonally?"""
    size = len(rows)
    for r in range(size):
        for c in range(size):
            for dr, dc in DIRECTIONS:
                end_r, end_c = r + dr * (len(word) - 1), c + dc * (len(word) - 1)
                if end_r < size and end_c < size and all(rows[r + dr * i][c + dc * i] == word[i] for i in range(len(word))):
                    return True
    return False


class GridTests(TestCase):
    def test_every_word_is_in_a_square_of_letters(self):
        grid = build(WORDS, seed="book")
        self.assertEqual(len(grid["rows"]), grid["size"])
        self.assertTrue(all(len(row) == grid["size"] for row in grid["rows"]))
        self.assertTrue(all(cell.isalpha() and len(cell) == 1 for row in grid["rows"] for cell in row))
        for word in WORDS:
            self.assertTrue(hidden(grid["rows"], word.upper()), word)

    def test_the_same_words_make_the_same_grid(self):
        self.assertEqual(build(WORDS, seed="a"), build(list(reversed(WORDS)), seed="a"))
        self.assertNotEqual(build(WORDS, seed="a")["rows"], build(WORDS + ["goat"], seed="a")["rows"])

    def test_spaces_capitals_long_words_and_nothing_at_all(self):
        self.assertEqual(letters_of("Ice cream!"), "ICECREAM")
        self.assertTrue(hidden(build(["Ice cream"], seed="x")["rows"], "ICECREAM"))
        long_word = "internationalisation"
        grid = build([long_word], seed="x")
        self.assertEqual(grid["size"], len(long_word))
        self.assertEqual(build([], seed="x")["placed"], 0)


class ActivityTests(TestCase):
    def setUp(self):
        self.level, _ = Level.objects.update_or_create(name="Level 3", defaults={"is_published": True})
        self.group = Group.objects.create(level=self.level, number=30, slug="search-30")
        self.activity = Activity.objects.create(group=self.group, kind="word-search", title="Activity Group 30")
        self.cruel = ActivityItem.objects.create(activity=self.activity, answer="cruel", hint="Not kind")
        self.army = ActivityItem.objects.create(activity=self.activity, answer="army")
        self.pupil = User.objects.create_user("pupil@example.com", "pw-12345678", first_name="Ada",
                                              role="student", level="Level 3")
        self.client.force_login(self.pupil)
        self.url = f"/echospell/{self.level.slug}/{self.group.slug}/activities/{self.activity.slug}/"

    def test_the_page_draws_the_grid_and_the_words(self):
        page = self.client.get(self.url)
        self.assertContains(page, "word-search__cell", count=self.activity.word_grid["size"] ** 2)
        self.assertContains(page, 'data-word="cruel"')
        self.assertContains(page, f'name="item-{self.cruel.pk}"')
        self.assertContains(page, "Not kind")
        self.assertContains(page, "2 words")
        self.assertContains(page, "js/word_search.js")

    def test_marked_on_the_words_found(self):
        response = self.client.post(self.url, {f"item-{self.cruel.pk}": "cruel", f"item-{self.army.pk}": ""})
        attempt = ActivityAttempt.objects.get(user=self.pupil)
        self.assertEqual(attempt.percent, 50)
        result = self.client.get(response.url)
        self.assertContains(result, "You found: <strong>cruel</strong>", html=False)
        self.assertContains(result, "You didn&#x27;t find army.")

    def test_the_marker(self):
        kind = get_kind("word-search")
        self.assertTrue(kind.is_auto_marked)
        self.assertTrue(mark_response(kind, self.cruel, "cruel"))
        self.assertFalse(mark_response(kind, self.cruel, ""))
        self.assertEqual(feedback_for(kind, self.army, "", False), "You didn't find army.")
        self.assertEqual(kind.item_fields, ["hint", "answer"])
