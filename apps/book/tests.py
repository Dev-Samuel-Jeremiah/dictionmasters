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
