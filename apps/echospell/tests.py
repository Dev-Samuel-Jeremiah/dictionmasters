"""What a learner sees on an EchoSpell card."""

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from . import importer
from .models import CardLesson, Category, Group, Level

User = get_user_model()


class SpellingCardTests(TestCase):
    def setUp(self):
        self.level = Level.objects.create(name="Pre-Level", slug="pre-level-test")
        self.group = Group.objects.create(level=self.level, number=1, slug="group-1-test")
        # The card types ship with the site, so this is the real one.
        self.category, _made = Category.objects.get_or_create(
            slug="spelling", defaults={"name": "Spelling words", "kind": "words"})
        self.level.categories.add(self.category)      # this level uses this card type
        self.user = User.objects.create_user(email="speller@example.com", password="mango-river-47",
                                             first_name="Ada", is_staff=True)
        self.client.force_login(self.user)

    def card(self, **fields):
        return CardLesson.objects.create(
            group=self.group, category=self.category, word="Goat", **fields)

    def url(self):
        return f"/echospell/{self.level.slug}/{self.group.slug}/{self.category.slug}/"

    def test_the_words_recording_is_tagged_full(self):
        """The recording says the whole word straight through, and is
        labelled so, ready for any other recording of the same word."""
        self.card(audio_url="https://example.com/goat.mp3")
        page = self.client.get(self.url())
        self.assertContains(page, '<span class="word-card__audio-tag">Full</span>', html=False)
        self.assertContains(page, "https://example.com/goat.mp3")

    def test_both_recordings_of_the_same_words_are_tagged(self):
        """One card, one set of words, said two ways."""
        self.card(audio_url="https://example.com/goat.mp3",
                  quick_audio_url="https://example.com/goat-quick.mp3")
        page = self.client.get(self.url())
        body = page.content.decode()
        self.assertIn(">Full</span>", body)
        self.assertIn(">Quick</span>", body)
        self.assertIn("https://example.com/goat.mp3", body)
        self.assertIn("https://example.com/goat-quick.mp3", body)
        self.assertEqual(body.count("<audio controls"), 2)

    def test_a_card_can_have_the_quick_one_alone(self):
        self.card(quick_audio_url="https://example.com/goat-quick.mp3")
        body = self.client.get(self.url()).content.decode()
        self.assertIn(">Quick</span>", body)
        self.assertNotIn(">Full</span>", body)

    def test_no_recording_means_no_tag(self):
        self.card()
        page = self.client.get(self.url())
        self.assertNotContains(page, "word-card__audio-tag")

    def test_the_admin_uploading_sees_which_is_which(self):
        """Whoever uploads has to know if they are replacing the Full or
        the Quick one, so the fields carry those names."""
        card = self.card(audio_url="https://example.com/goat.mp3")
        boss = User.objects.create_superuser(email="boss@example.com", password="mango-river-47",
                                             first_name="Boss")
        self.client.force_login(boss)
        for url in [f"/manage/card-lessons/{card.pk}/", f"/admin/echospell/cardlesson/{card.pk}/change/"]:
            page = self.client.get(url)
            self.assertEqual(page.status_code, 200, url)
            body = page.content.decode()
            self.assertIn("Full recording", body, url)
            self.assertIn("Quick recording", body, url)


# A level of the book in miniature: the front matter that should be passed
# over, two groups laid out the two ways the book prints its words, and the
# vocabulary pages that are meant to be left for the learner.
BOOK = """About Echospell

Echospell is a tool for spelling sessions in schools.

                                        i

                              LEVEL 4 GROUP 1

   1. Harvest
   2. Lantern
   3. Copper
   4. Meadow

                                        2

                              The Lantern Maker

Ada carried the lantern through the meadow at harvest time, its copper handle
warm in her hand.

She set it down and waited for the others.

                            Conversation Group 1
1.     ADA: Did you bring the lantern?
2.     EMEKA: Yes! The copper one from the meadow shed.

                                        3

                            Vocabulary Group 1
1. Harvest: ______________________________________________________

                                        4

                              LEVEL 4 GROUP 2

  1. Pebble        3. Kettle       5. Ribbon
  2. Marble        4. Saddle       6. Tunnel

                                 The Kettle

The kettle sang on the fire while the rain drummed on the roof.

                            Conversation Group 2
1.     ADA: Put the kettle on.
2.     EMEKA: Already done.
"""


class ImportBookTests(TestCase):
    """A level of the book, read and written into the right cards."""

    def setUp(self):
        self.level = Level.objects.create(name="Level 4", slug="level-4-test")
        for slug, name, kind in [("spelling", "Spelling words", "words"),
                                 ("passage-reading", "Passage reading", "passage"),
                                 ("dialogue", "Dialogue", "dialogue")]:
            Category.objects.get_or_create(slug=slug, defaults={"name": name, "kind": kind})

    def test_it_reads_the_shape_of_the_book(self):
        found = importer.parse(BOOK)
        self.assertEqual(found["level"], "Level 4")
        self.assertEqual([group["number"] for group in found["groups"]], [1, 2])

        first = found["groups"][0]
        self.assertEqual(first["words"], ["Harvest", "Lantern", "Copper", "Meadow"])
        self.assertEqual(first["passage"]["title"], "The Lantern Maker")
        self.assertEqual(len(first["passage"]["body"].split("\n\n")), 2)
        self.assertIn("copper handle warm in her hand", first["passage"]["body"])
        self.assertEqual([line["speaker"] for line in first["dialogue"]], ["ADA", "EMEKA"])
        self.assertEqual(first["dialogue"][0]["text"], "Did you bring the lantern?")

        # The words print in columns too, and are still read in order.
        self.assertEqual(found["groups"][1]["words"],
                         ["Pebble", "Marble", "Kettle", "Saddle", "Ribbon", "Tunnel"])

    def test_the_vocabulary_pages_and_the_introduction_are_left_out(self):
        found = importer.parse(BOOK)
        everything = str(found)
        self.assertNotIn("Vocabulary", everything)
        self.assertNotIn("_____", everything)
        self.assertNotIn("spelling sessions in schools", everything)   # the book's own introduction

    def test_a_column_that_wraps_keeps_its_word(self):
        """The last column often wraps, leaving "17." on one line and its
        word alone on the next."""
        wrapped = "LEVEL 4 GROUP 3\n\n1. Anchor   9. Violet   17.\nWalnut\n\nThe Anchor\n\nA story.\n"
        words = importer.parse(wrapped)["groups"][0]["words"]
        self.assertEqual(words, ["Anchor", "Violet", "Walnut"])

    def test_it_fills_the_cards_in(self):
        report = importer.apply_import(importer.parse(BOOK), self.level)
        self.assertEqual(report["created"], 6)          # words, passage and conversation, twice

        group = Group.objects.get(level=self.level, number=1)
        card = CardLesson.objects.get(group=group, category__slug="spelling")
        self.assertEqual(card.word_list, ["Harvest", "Lantern", "Copper", "Meadow"])
        self.assertEqual(group.passage.title, "The Lantern Maker")
        self.assertEqual([line.speaker for line in group.dialogue.lines.all()], ["ADA", "EMEKA"])
        # The level now offers the card types its groups were given.
        self.assertEqual(self.level.categories.count(), 3)

    def test_importing_the_same_book_again_changes_nothing(self):
        found = importer.parse(BOOK)
        importer.apply_import(found, self.level)
        again = importer.apply_import(found, self.level)
        self.assertEqual((again["created"], again["updated"]), (0, 0))
        self.assertEqual(CardLesson.objects.filter(group__level=self.level).count(), 2)

    def test_rewriting_keeps_the_recordings(self):
        """An admin can refresh the text from a corrected book without
        losing the audio someone recorded for those words."""
        importer.apply_import(importer.parse(BOOK), self.level)
        group = Group.objects.get(level=self.level, number=1)
        card = CardLesson.objects.get(group=group, category__slug="spelling")
        card.audio_url = "https://example.com/full.mp3"
        card.quick_audio_url = "https://example.com/quick.mp3"
        card.save()

        changed = BOOK.replace("4. Meadow", "4. Orchard")
        report = importer.apply_import(importer.parse(changed), self.level, importer.REPLACE)
        card.refresh_from_db()
        self.assertEqual(card.word_list[-1], "Orchard")
        self.assertEqual(card.audio_url, "https://example.com/full.mp3")
        self.assertEqual(card.quick_audio_url, "https://example.com/quick.mp3")
        self.assertTrue(report["updated"])

    def test_the_plan_says_what_would_happen_before_anything_does(self):
        found = importer.parse(BOOK)
        plan = importer.describe_plan(found, self.level)
        self.assertIn("will be added", plan["plan"][0]["doing"][0])
        self.assertEqual(CardLesson.objects.count(), 0)      # nothing written by looking

        importer.apply_import(found, self.level)
        after = importer.describe_plan(found, self.level)
        self.assertIn("already there", after["plan"][0]["doing"][0])

    def test_a_file_that_is_not_the_book_is_refused(self):
        with self.assertRaises(importer.CannotRead):
            importer.parse("Just some notes, with no group headings at all.")


class ImportPageTests(TestCase):
    def setUp(self):
        self.level = Level.objects.create(name="Level 4", slug="level-4-page")
        for slug, name, kind in [("spelling", "Spelling words", "words"),
                                 ("passage-reading", "Passage reading", "passage"),
                                 ("dialogue", "Dialogue", "dialogue")]:
            Category.objects.get_or_create(slug=slug, defaults={"name": name, "kind": kind})
        self.boss = User.objects.create_superuser(email="boss2@example.com", password="mango-river-47",
                                                  first_name="Boss")

    def book(self):
        return SimpleUploadedFile("level-4.txt", BOOK.encode("utf-8"), content_type="text/plain")

    def test_only_staff_can_import(self):
        learner = User.objects.create_user(email="learner@example.com", password="mango-river-47",
                                           first_name="Ada", role=User.Role.INDIVIDUAL)
        self.client.force_login(learner)
        self.assertNotEqual(self.client.get("/manage/echospell-import/").status_code, 200)

    def test_upload_shows_a_preview_and_writes_nothing_until_agreed(self):
        self.client.force_login(self.boss)
        preview = self.client.post("/manage/echospell-import/", {"step": "read", "book": self.book()})
        self.assertContains(preview, "Harvest")
        self.assertContains(preview, "The Lantern Maker")
        self.assertContains(preview, "will be added")
        self.assertNotContains(preview, "Vocabulary Group")
        self.assertEqual(CardLesson.objects.count(), 0)      # still nothing saved

        saved = self.client.post("/manage/echospell-import/", {"step": "save", "mode": "fill"})
        self.assertContains(saved, "Done")
        self.assertEqual(CardLesson.objects.filter(group__level=self.level).count(), 2)
        self.assertEqual(Group.objects.filter(level=self.level).count(), 2)
