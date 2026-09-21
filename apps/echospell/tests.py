"""What a learner sees on an EchoSpell card."""

from django.contrib.auth import get_user_model
from django.test import TestCase

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
