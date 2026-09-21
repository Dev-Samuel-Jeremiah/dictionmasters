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

    def test_no_recording_means_no_tag(self):
        self.card()
        page = self.client.get(self.url())
        self.assertNotContains(page, "word-card__audio-tag")
