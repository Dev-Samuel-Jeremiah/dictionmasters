"""
Read-along timings: a recording added a moment ago must start following
the words on its own, without anyone reloading the page.

Nothing here reaches OpenAI or cloud storage — measuring is stood in for.
"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.echospell.models import Group, Level, Passage

from . import read_along
from .models import ReadAlongTiming

User = get_user_model()


class TimingHandoverTests(TestCase):
    """What the page is told while a recording is still being measured."""

    def setUp(self):
        level = Level.objects.create(name="Level 1", slug="level-1-test")
        group = Group.objects.create(level=level, number=1, slug="group-1-test")
        self.passage = Passage.objects.create(
            group=group, title="Test", body="The bus stopped at the gate.",
            audio_url="https://example.com/reading.mp3",
        )
        self.kind = ContentType.objects.get_for_model(Passage)
        self.user = User.objects.create_user(email="reader@example.com", password="pw-12345678",
                                             first_name="Ada", is_staff=True)
        self.client.force_login(self.user)

    def row(self, **fields):
        return ReadAlongTiming.objects.create(
            content_type=self.kind, object_id=self.passage.pk,
            fingerprint=read_along._fingerprint(self.passage), **fields,
        )

    def test_what_is_known_so_far_is_handed_over_while_measuring(self):
        """Where the voice speaks is worked out long before the words are,
        and is enough for the page to follow the reading meanwhile."""
        self.row(status=ReadAlongTiming.STATUS_WORKING, speech=[[0.0, 4.0], [4.8, 9.0]], duration=9.0)
        status, row = read_along.timing_for(self.passage, start=False)
        self.assertEqual(status, "pending")
        self.assertEqual(row.speech, [[0.0, 4.0], [4.8, 9.0]])

        reply = self.client.get(read_along.sync_url(self.passage)).json()
        self.assertEqual(reply["status"], "pending")
        self.assertEqual(reply["speech"], [[0.0, 4.0], [4.8, 9.0]])
        self.assertTrue(reply["retry"])       # the page is told to keep asking

    def test_the_finished_timings_are_handed_over(self):
        self.row(status=ReadAlongTiming.STATUS_READY, words=[["The", 0.0, 0.3]], duration=9.0, quality=1.0)
        reply = self.client.get(read_along.sync_url(self.passage)).json()
        self.assertEqual(reply["status"], "ready")
        self.assertEqual(reply["words"], [["The", 0.0, 0.3]])
        self.assertFalse(reply["retry"])      # nothing more to wait for

    @override_settings(TESTING=False)
    @mock.patch("apps.book.read_along.is_configured", return_value=True)
    @mock.patch("apps.book.read_along._queue")
    def test_measuring_starts_when_the_recording_is_saved(self, queue, _configured):
        """So the words are ready before a learner opens the lesson,
        instead of the measuring starting with the first visitor."""
        read_along.measure_when_saved(Passage, self.passage)
        self.assertEqual(queue.call_count, 1)

        # Already measured, and unchanged: nothing to do.
        queue.reset_mock()
        self.row(status=ReadAlongTiming.STATUS_READY, words=[["The", 0.0, 0.3]])
        read_along.measure_when_saved(Passage, self.passage)
        self.assertEqual(queue.call_count, 0)

        # The recording is swapped for another: measured again — and by
        # saving alone, which is what an admin does.
        self.passage.audio_url = "https://example.com/another.mp3"
        self.passage.save()
        self.assertEqual(queue.call_count, 1)

    @override_settings(TESTING=False)
    @mock.patch("apps.book.read_along.is_configured", return_value=True)
    @mock.patch("apps.book.read_along._queue", side_effect=RuntimeError("no"))
    def test_a_timing_never_breaks_saving(self, _queue, _configured):
        read_along.measure_when_saved(Passage, self.passage)      # must not raise

    def test_the_background_pool_still_runs_measurements(self):
        """The connection pool and the thread pool are different things —
        they shared a name once, and background measuring stopped."""
        self.assertTrue(hasattr(read_along._pool, "submit"))
        self.assertTrue(read_along._http is None or hasattr(read_along._http, "request"))

    def test_measuring_is_stale_after_long_enough(self):
        old = self.row(status=ReadAlongTiming.STATUS_WORKING)
        ReadAlongTiming.objects.filter(pk=old.pk).update(
            updated_at=timezone.now() - read_along.WORKING_FOR * 2)
        with mock.patch("apps.book.read_along.is_configured", return_value=True), \
                mock.patch("apps.book.read_along._queue") as queue:
            status, _row = read_along.timing_for(self.passage)
        self.assertEqual(status, "pending")
        self.assertEqual(queue.call_count, 1)      # started again rather than left stuck


class TabVideoTests(TestCase):
    """Any tab of a sound's lesson can carry several videos."""

    def setUp(self):
        from .models import Sound, SoundCategory

        category = SoundCategory.objects.create(name="Long vowels")
        self.sound = Sound.objects.create(category=category, symbol="uː", name="Long OO",
                                          slug="long-oo-test", is_published=True)
        self.user = User.objects.create_user(email="viewer@example.com", password="pw-12345678",
                                             first_name="Ada", is_staff=True)
        self.client.force_login(self.user)

    def video(self, section, order, caption):
        from .models import SectionVideo

        return SectionVideo.objects.create(sound=self.sound, section=section, order=order,
                                           video_caption=caption, video_url=f"https://example.com/{order}.mp4")

    def url(self, tab):
        return f"/book/44-academy/{self.sound.slug}/{tab}/"

    def test_a_tab_shows_all_its_videos_in_order(self):
        self.video("word-bank", 2, "Second")
        self.video("word-bank", 1, "First")
        body = self.client.get(self.url("word-bank")).content.decode()
        self.assertLess(body.index("First"), body.index("Second"))
        self.assertIn("1 of 2", body)

    def test_each_video_stays_on_its_own_tab(self):
        self.video("twisters", 1, "Twister drill")
        self.assertNotContains(self.client.get(self.url("word-bank")), "Twister drill")
        self.assertContains(self.client.get(self.url("twisters")), "Twister drill")

    def test_every_tab_can_take_videos(self):
        from .views import TABS

        for number, (slug, _label) in enumerate(TABS):
            self.video(slug, number, f"Video for {slug}")
        for slug, _label in TABS:
            self.assertContains(self.client.get(self.url(slug)), f"Video for {slug}", msg_prefix=slug)

    def test_lens_videos_are_enough_on_their_own(self):
        """A lens tab with videos but no written lesson yet shows the
        videos, not "being put together"."""
        self.video("lens", 1, "Mouth close-up")
        page = self.client.get(self.url("lens"))
        self.assertContains(page, "Mouth close-up")
        self.assertNotContains(page, "being put together")

    def test_videos_wait_until_played(self):
        """Several videos on a tab must not all start downloading at once
        on a phone."""
        self.video("passage", 1, "Reading aloud")
        body = self.client.get(self.url("passage")).content.decode()
        self.assertIn('preload="metadata"', body)
        self.assertNotIn('preload="auto"', body)


class TricksToSoundFluentTests(TestCase):
    """Tricks to Sound Fluent: its own programme, with every page 44 Academy
    has, and never mixed up with the 44 sounds."""

    def setUp(self):
        from .models import TRICKS, Sound, SoundCategory, WordBankEntry

        sounds = SoundCategory.objects.create(name="Long vowels")
        self.sound = Sound.objects.create(category=sounds, symbol="uː", name="Long OO",
                                          slug="long-oo-tricks", is_published=True)
        WordBankEntry.objects.create(sound=self.sound, word="moon")
        tricks = SoundCategory.objects.create(name="Linking", programme=TRICKS)
        self.trick = Sound.objects.create(category=tricks, symbol="⁀", name="Consonant to vowel",
                                          slug="consonant-to-vowel", is_published=True)
        WordBankEntry.objects.create(sound=self.trick, word="an apple")
        self.client.force_login(User.objects.create_user(
            email="fluent@example.com", password="pw-12345678", first_name="Ada", is_staff=True))

    def test_the_tabs_are_called_trick_and_word_list(self):
        page = self.client.get(f"/book/44-academy/{self.sound.slug}/lens/")
        self.assertContains(page, ">Sound</span></a>")
        self.assertContains(page, ">Word List</span></a>")
        self.assertNotContains(page, ">Lens<")
        self.assertNotContains(page, ">Word Bank<")

    def test_the_dashboard_card_opens_tricks(self):
        page = self.client.get("/accounts/dashboard/")
        self.assertContains(page, 'href="/tricks/"')
        self.assertContains(page, "Tricks to Sound Fluent")
        self.assertNotContains(page, "Coming soon")
        # Just the card: the sections live on the Tricks pages, not here.
        self.assertNotContains(page, 'href="/tricks/sections/')

    def test_the_etiquette_advantage_card_is_locked(self):
        # It has no lessons yet: shown on Learn as coming soon, not a link.
        page = self.client.get("/learning-tools/").content.decode()
        card = page[page.index("The Etiquette Advantage") - 400:page.index("The Etiquette Advantage") + 300]
        self.assertIn("is-locked", card)
        self.assertIn("Coming soon", card)
        self.assertNotIn("<a ", card[card.index("is-locked"):])

    def test_tricks_has_its_own_pages(self):
        home = self.client.get("/tricks/")
        self.assertContains(home, "Tricks to Sound Fluent")
        self.assertContains(home, "1 trick")
        listing = self.client.get("/tricks/lessons/")
        self.assertContains(listing, "Consonant to vowel")
        self.assertNotContains(listing, "Long OO")
        self.assertContains(listing, 'href="/tricks/lessons/consonant-to-vowel/"')
        for tab in ("lens", "word-bank", "sentence-practice", "passage", "conversations",
                    "twisters", "minimal-pairs", "external-links"):
            page = self.client.get(f"/tricks/lessons/consonant-to-vowel/{tab}/")
            self.assertEqual(page.status_code, 200, tab)
            self.assertContains(page, 'href="/tricks/lessons/consonant-to-vowel/passage/"')
            self.assertNotContains(page, "/book/44-academy/")
        self.assertContains(self.client.get("/tricks/lessons/consonant-to-vowel/word-bank/"), "an apple")

    def test_all_tricks_is_a_numbered_list_and_all_sounds_stays_as_tiles(self):
        tricks = self.client.get("/tricks/lessons/")
        self.assertContains(tricks, 'class="ui-numlist"')
        self.assertContains(tricks, '<span class="ui-numlist__num">1</span>')
        self.assertNotContains(tricks, 'class="ui-sound ')
        sounds = self.client.get("/book/44-academy/")
        self.assertContains(sounds, 'class="ui-sound ')
        self.assertNotContains(sounds, 'class="ui-numlist"')

    def test_the_programmes_never_cross(self):
        self.assertEqual(self.client.get(f"/tricks/lessons/{self.sound.slug}/").status_code, 404)
        self.assertEqual(self.client.get(f"/book/44-academy/{self.trick.slug}/").status_code, 404)
        academy = self.client.get("/book/44-academy/")
        self.assertContains(academy, "Long OO")
        self.assertNotContains(academy, "Consonant to vowel")
        self.assertNotContains(self.client.get("/book/phonemic-chart/"), "Consonant to vowel")

    def test_a_section_lists_the_tricks_and_leads_into_each(self):
        page = self.client.get("/tricks/sections/word-bank/")
        self.assertContains(page, "Word List")
        self.assertContains(page, 'href="/tricks/lessons/consonant-to-vowel/word-bank/"')
        self.assertNotContains(page, "Long OO")
        self.assertContains(page, "1 item")

    def test_an_unknown_section_or_tab_is_not_found(self):
        self.assertEqual(self.client.get("/tricks/sections/nonsense/").status_code, 404)
        self.assertEqual(self.client.get("/tricks/lessons/consonant-to-vowel/nonsense/").status_code, 404)

    def test_the_old_addresses_move_to_tricks(self):
        self.assertRedirects(self.client.get("/book/tricks/"), "/tricks/", fetch_redirect_response=False)
        self.assertRedirects(self.client.get("/book/tricks/twisters/"), "/tricks/sections/twisters/",
                             fetch_redirect_response=False)

    def test_the_control_room_keeps_them_apart(self):
        from .models import TRICKS, Sound, SoundCategory

        academy = self.client.get("/manage/sounds/")
        self.assertContains(academy, "Long OO")
        self.assertNotContains(academy, "Consonant to vowel")
        tricks = self.client.get("/manage/trick-sounds/")
        self.assertContains(tricks, "Consonant to vowel")
        self.assertNotContains(tricks, "Long OO")
        self.assertEqual(self.client.get(f"/manage/sounds/{self.trick.pk}/").status_code, 404)
        self.assertNotContains(self.client.get("/manage/trick-word-bank/"), "moon")

        # Tricks have no groups: there is no screen for them, and a trick is
        # added with just its name, landing at the end of the list.
        self.assertEqual(self.client.get("/manage/trick-sound-groups/").status_code, 404)
        form = self.client.get("/manage/trick-sounds/new/")
        self.assertContains(form, "Trick number")
        self.assertNotContains(form, 'name="category"')
        self.client.post("/manage/trick-sounds/new/", {"name": "-age Ending", "order": 0, "is_published": "on"})
        added = Sound.objects.get(name="-age Ending")
        self.assertEqual(added.category, SoundCategory.for_tricks())
        self.assertEqual(added.programme, TRICKS)
        self.assertEqual(added.order, self.trick.order + 1)
        # A sound, though, still needs its symbol for the phonemic chart.
        page = self.client.post("/manage/sounds/new/", {"name": "Short I", "category": self.sound.category.pk,
                                                        "order": 1, "is_published": "on"})
        self.assertContains(page, "A sound needs its symbol")
        self.assertFalse(Sound.objects.filter(name="Short I").exists())

    def test_a_trick_shows_its_number_not_a_group(self):
        from .models import Sound

        page = self.client.get(f"/tricks/lessons/{self.trick.slug}/")
        self.assertContains(page, "Trick 1")
        self.assertNotContains(page, "Linking")
        plain = Sound.objects.create(category=self.trick.category, name="-age Ending", is_published=True)
        page = self.client.get(f"/tricks/lessons/{plain.slug}/")
        self.assertContains(page, "Trick 2")
        self.assertContains(page, '<span class="ui-hero__symbol">2</span>')
        section = self.client.get("/tricks/sections/passage/")
        self.assertContains(section, 'class="ui-numlist"')
        self.assertNotContains(section, "ui-section__title")


class WordListTimingTests(TestCase):
    """A spelling card's Full recording is a lesson, not a reading. Built from
    a real one: "Number one … Today", "Number two … (Breakfast, which neither
    transcript caught) … Repeat that … Breakfast", and "Number three … How do
    you pronounce this word? … oven"."""

    ITEMS = ["Today", "Breakfast", "Oven"]
    RUNS = [(24.2, 24.8), (27.3, 28.1), (49.1, 49.8), (51.9, 52.7), (54.9, 55.6), (56.7, 57.6),
            (60.2, 61.4), (318.4, 319.0), (320.9, 322.5), (326.2, 326.9)]
    HINTED = [["Number", 23.2, 23.9], ["1", 24.6, 24.8], ["Today", 25.4, 25.9], ["Number", 47.6, 48.1],
              ["2", 49.4, 49.6], ["Breakfast", 49.8, 50.2], ["Repeat", 54.5, 54.9], ["that", 55.2, 55.5],
              ["Breakfast", 57.1, 57.6], ["Number", 318.0, 318.4], ["3", 318.7, 319.0], ["How", 321.0, 321.2],
              ["do", 321.2, 321.4], ["you", 321.4, 321.6], ["pronounce", 322.0, 322.4], ["oven", 326.4, 326.8]]
    PLAIN = [["Number", 23.0, 23.6], ["one", 25.0, 25.2], ["Today", 27.5, 28.0], ["Number", 48.0, 48.4],
             ["two", 49.0, 49.4], ["Repeat", 55.0, 55.3], ["that", 55.3, 55.6], ["Breakfast", 60.3, 61.0],
             ["Number", 318.2, 318.6], ["three", 318.8, 319.0], ["How", 321.0, 321.2], ["oven", 326.4, 326.8]]

    def test_each_word_starts_when_the_teacher_says_it(self):
        starts, placed = read_along.list_timing(self.ITEMS, [self.HINTED, self.PLAIN], self.RUNS)
        self.assertEqual(placed, 3)
        # Today: the voice after "number one", not the hinted 25.4 (a silence).
        self.assertAlmostEqual(starts[0], 27.3, places=1)
        # Breakfast: the untranscribed word right after "number two" — not
        # "Repeat that" (which sounds like "today") nor a later repeat.
        self.assertAlmostEqual(starts[1], 51.9, places=1)
        # Oven: after the teacher's question, when the word is said.
        self.assertAlmostEqual(starts[2], 326.2, places=1)

    def test_a_word_said_with_its_number_in_one_breath(self):
        # A quick run-through: "one, mirror" said in one breath, the
        # transcript's time for the word a little late.
        starts, _placed = read_along.list_timing(
            ["Mirror"], [[["1", 93.7, 94.2], ["Mirror", 95.2, 95.2]]], [(93.5, 95.0)])
        self.assertTrue(93.9 <= starts[0] <= 94.6, starts)
