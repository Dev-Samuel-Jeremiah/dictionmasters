"""
Read-along timings: a recording added a moment ago must start following
the words on its own, without anyone reloading the page.

Nothing here reaches Groq or cloud storage — measuring is stood in for.
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
    """The lesson one section at a time, reached from the dashboard."""

    def setUp(self):
        from .models import Sound, SoundCategory, WordBankEntry

        category = SoundCategory.objects.create(name="Long vowels")
        self.sound = Sound.objects.create(category=category, symbol="uː", name="Long OO",
                                          slug="long-oo-tricks", is_published=True)
        WordBankEntry.objects.create(sound=self.sound, word="moon")
        self.client.force_login(User.objects.create_user(
            email="fluent@example.com", password="pw-12345678", first_name="Ada", is_staff=True))

    def test_the_tabs_are_called_trick_and_word_list(self):
        page = self.client.get(f"/book/44-academy/{self.sound.slug}/lens/")
        self.assertContains(page, ">Trick</a>")
        self.assertContains(page, ">Word List</a>")
        self.assertNotContains(page, ">Lens</a>")
        self.assertNotContains(page, ">Word Bank</a>")

    def test_the_dashboard_card_links_every_section(self):
        from .views import TABS

        page = self.client.get("/accounts/dashboard/")
        self.assertContains(page, 'href="/book/tricks/"')
        for slug, _label in TABS:
            self.assertContains(page, f'href="/book/tricks/{slug}/"', msg_prefix=slug)

    def test_a_section_lists_the_sounds_and_leads_into_each(self):
        page = self.client.get("/book/tricks/word-bank/")
        self.assertContains(page, "Word List")
        self.assertContains(page, f'href="/book/44-academy/{self.sound.slug}/word-bank/"')
        self.assertContains(page, "1 item")

    def test_an_unknown_section_is_not_found(self):
        self.assertEqual(self.client.get("/book/tricks/nonsense/").status_code, 404)
