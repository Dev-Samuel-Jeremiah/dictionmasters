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
