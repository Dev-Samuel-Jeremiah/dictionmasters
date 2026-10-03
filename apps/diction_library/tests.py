"""Reading a library book aloud: only the main content, and word timings
that match the page exactly. Nothing here reaches ElevenLabs."""

from django.test import SimpleTestCase

from . import narration


class MainContentTests(SimpleTestCase):
    STORY = "Far away from the noisy cities there was a small peaceful village. " * 5

    def test_the_contents_pages_are_skipped(self):
        paragraphs = [
            "THE MAGIC TALKING DRUM", "CHAPTERS",
            "Chapter 1 – Ayo and the Small Village", "Chapter 2 – The Strange Sound",
            "Chapter 1 – Ayo and the Small Village", self.STORY, "Ayo smiled.",
            "Chapter 2 – The Strange Sound", self.STORY,
            "The End.", "About the Author", "She lives in Lagos.",
        ]
        chapters = narration.main_chapters(paragraphs, "THE MAGIC TALKING DRUM")
        self.assertEqual([title for title, _ in chapters],
                         ["Chapter 1 – Ayo and the Small Village", "Chapter 2 – The Strange Sound"])
        self.assertEqual(chapters[0][1][1], self.STORY)            # straight into the story
        self.assertEqual(chapters[-1][1][-1], "The End.")           # nothing after it
        self.assertNotIn("CHAPTERS", " ".join(p for _t, ps in chapters for p in ps))

    def test_a_story_without_chapters_starts_at_its_first_paragraph(self):
        paragraphs = ["THE KITE", "Contents", "Morning", "Evening", "Morning", self.STORY, "The End."]
        chapters = narration.main_chapters(paragraphs, "THE KITE")
        self.assertEqual(len(chapters), 1)
        self.assertEqual(chapters[0][1][0], "Morning")               # its heading, just above the story
        self.assertEqual(chapters[0][1][1], self.STORY)


class VoiceTimingTests(SimpleTestCase):
    def test_letter_timings_become_the_page_words(self):
        text = "“Look!” she said."
        alignment = {
            "characters": list(text),
            "character_start_times_seconds": [i * 0.1 for i in range(len(text))],
            "character_end_times_seconds": [i * 0.1 + 0.08 for i in range(len(text))],
        }
        words = narration._words(alignment, offset=10.0)
        self.assertEqual([w for w, _a, _b in words], text.split())
        self.assertAlmostEqual(words[0][1], 10.0)
        self.assertAlmostEqual(words[1][1], 10.8)                   # "she" starts at letter 8

    def test_the_pieces_rebuild_the_chapter_exactly(self):
        paragraphs = ["Chapter 1 – Start", "word " * 700, "Short one.", ("Long sentence here. " * 200).strip()]
        pieces = narration._pieces(paragraphs)
        self.assertTrue(all(len(text) <= narration.CHUNK_CHARS + 200 for text, _g in pieces))
        rebuilt = "".join(text + glue for text, glue in pieces)
        self.assertEqual(rebuilt.split(), "\n\n".join(paragraphs).split())


from unittest import mock

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

STORAGE = {"default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
           "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


class RecordingNameTests(SimpleTestCase):
    def test_names_say_which_chapter_or_pages(self):
        cases = {"Chapter five": ("chapter", 5), "Chapter 4": ("chapter", 4), "chapter_one": ("chapter", 1),
                 "Chapter Twenty-One": ("chapter", 21), "CHAPTER XII": ("chapter", 12),
                 "Page 121 to 124": ("pages", 121, 124), "Pages 7-9": ("pages", 7, 9), "Introduction": ("other",)}
        for name, part in cases.items():
            self.assertEqual(narration.recording_part(name), part, name)


@override_settings(STORAGES=STORAGE)
@mock.patch("apps.book.read_along.measure_in_background")
class ManyRecordingsTests(TestCase):
    STORY = "Ayo walked to the village square where the drummers played every evening. " * 4

    def setUp(self):
        from .models import LibraryItem

        self.item = LibraryItem.objects.create(
            title="The Talking Drum", kind="book",
            description="\n\n".join(["Chapter 1 – The Village", self.STORY, "Chapter 2 – The Sound", self.STORY,
                                     "Chapter 5 – Home Again", self.STORY]))

    def add(self, *names):
        from .models import LibraryRecording

        for name in names:
            LibraryRecording.objects.create(item=self.item, name=name, audio_file=ContentFile(b"ID3", name=f"{name}.mp3"))

    def test_each_recording_is_a_chapter_in_order_with_its_words(self, measure):
        self.add("Chapter five", "Chapter 1", "Chapter two", "Afterword")
        narration.narrate(self.item)
        chapters = list(self.item.chapters.order_by("order"))
        self.assertEqual([c.title for c in chapters],
                         ["Chapter 1 – The Village", "Chapter 2 – The Sound", "Chapter 5 – Home Again", "Afterword"])
        self.assertIn("Ayo walked", chapters[2].text)
        self.assertEqual(chapters[3].text, "")                      # no matching words: plays without highlight
        self.assertTrue(all(not c.generated for c in chapters))
        self.assertEqual(measure.call_count, 3)
        self.item.refresh_from_db()
        self.assertEqual(self.item.narration_status, "ready")

    def test_page_ranges_take_the_words_on_those_pages(self, _measure):
        self.add("Page 121 to 124", "Page 7 to 9")
        with mock.patch.object(narration, "_page_text", side_effect=lambda item, a, b, folder: [f"Words of pages {a}-{b}."]) as pages:
            narration.narrate(self.item)
        self.assertEqual([c.title for c in self.item.chapters.order_by("order")], ["Pages 7–9", "Pages 121–124"])
        self.assertEqual(self.item.chapters.get(order=1).text, "Words of pages 121-124.")
        self.assertEqual(pages.call_count, 2)

    def test_removing_a_recording_removes_its_chapter(self, _measure):
        self.add("Chapter 1", "Chapter 2")
        narration.narrate(self.item)
        self.item.recordings.get(name="Chapter 2").delete()
        narration.narrate(self.item)
        self.assertEqual([c.title for c in self.item.chapters.all()], ["Chapter 1 – The Village"])

    def test_the_control_room_takes_many_recordings_at_once(self, _measure):
        from apps.accounts.models import User

        staff = User.objects.create_user("s@example.com", "pw-12345678", first_name="Sam", is_staff=True)
        self.client.force_login(staff)
        url = f"/manage/diction-library-items/{self.item.pk}/"
        form = self.client.get(url)
        self.assertContains(form, "Narration recordings")
        self.assertContains(form, "multiple")
        files = [SimpleUploadedFile(n, b"ID3", content_type="audio/mpeg") for n in ("chapter_five.mp3", "Chapter 1.mp3")]
        data = {"title": self.item.title, "kind": "book", "description": self.item.description,
                "is_published": "on", "order": 0, "recordings": files}
        response = self.client.post(url, data, follow=True)
        self.assertContains(response, "2 recordings added")
        self.assertEqual(sorted(self.item.recordings.values_list("name", flat=True)), ["Chapter 1", "chapter five"])
        # Listed in reading order, ready to tick off.
        listed = self.client.get(url).content.decode()
        self.assertLess(listed.index("Chapter 1</strong>"), listed.index("Chapter 5</strong>"))
        first = self.item.recordings.get(name="Chapter 1")
        self.client.post(url, {**{k: v for k, v in data.items() if k != "recordings"}, "remove_recordings": [first.pk]})
        self.assertEqual(list(self.item.recordings.values_list("name", flat=True)), ["chapter five"])
