"""
The AI reading tutor: judging readings, levels, and the endpoints.

Nothing here reaches OpenAI, ElevenLabs or cloud storage — transcription,
the voice and the feedback are all stood in for.
"""

import os
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.billing.access import GATED_PREFIXES

from . import listen, pronounce, report
from .models import TutorPassage, TutorSession

User = get_user_model()

BODY = "I have a red hat. He gave me three ripe mangoes.\n\nThe soup is very hot."


def heard(text):
    return [(word, i * 0.3, i * 0.3 + 0.25) for i, word in enumerate(text.split())]


class JudgingTests(TestCase):
    def test_sentences_keep_paragraphs(self):
        parts = listen.sentences(BODY)
        self.assertEqual([p["text"] for p in parts],
                         ["I have a red hat.", "He gave me three ripe mangoes.", "The soup is very hot."])
        self.assertEqual([p["paragraph"] for p in parts], [0, 0, 1])

    def test_closing_quotes_stay_with_their_sentence(self):
        parts = listen.sentences('"Thank you," Tunde said. "This is the best soup!" She laughed.')
        self.assertEqual([p["text"] for p in parts],
                         ['"Thank you," Tunde said.', '"This is the best soup!"', "She laughed."])

    def test_long_sentence_is_split_at_a_comma(self):
        long = ("When the rain finally stopped after three long days of storms, " * 2).strip() + " we went out."
        self.assertEqual(len(listen.sentences(long)), 2)

    def test_same_word(self):
        self.assertTrue(listen.same_word("their", "there"))        # sounds the same
        self.assertTrue(listen.same_word("3", "three"))            # numbers
        self.assertTrue(listen.same_word("Timi", "Timmy"))         # a name, spelt another way
        self.assertFalse(listen.same_word("three", "tree"))
        self.assertFalse(listen.same_word("bag", "back"))

    def test_a_misreading_is_caught_and_named(self):
        words = listen.sentences(BODY)[1]["words"]
        result = listen.judge_sentence(words, heard("He gave me tree ripe mangoes."))
        wrong = [w for w in result["words"] if w["status"] == "wrong"]
        self.assertEqual(len(wrong), 1)
        self.assertEqual(words[wrong[0]["i"]]["text"], "three")
        self.assertIn("/θ/", wrong[0]["tips"][0])
        self.assertEqual(wrong[0]["patterns"], [["θ", "t"]])
        self.assertEqual(result["model"], [wrong[0]["i"]])
        self.assertFalse(result["again"])

    def test_a_correction_and_a_filler_are_forgiven(self):
        words = listen.sentences("Timi and his brother ran to the market.")[0]["words"]
        result = listen.judge_sentence(words, heard("Timmy and his brother run to the uh the market"))
        flagged = [words[w["i"]]["text"] for w in result["words"] if w["status"] != "ok"]
        self.assertEqual(flagged, ["ran"])

    def test_a_dropped_small_word_is_counted_but_not_modelled(self):
        words = listen.sentences("He gave me the ball.")[0]["words"]
        result = listen.judge_sentence(words, heard("He gave me ball."))
        self.assertEqual(result["right"], 4)
        self.assertEqual(result["model"], [])

    def test_mostly_wrong_means_hear_it_again(self):
        words = listen.sentences("Timi and his brother ran to the market.")[0]["words"]
        self.assertTrue(listen.judge_sentence(words, heard("Tim and"))["again"])

    def test_everything_is_judged_in_british_english(self):
        # The R at the end of a word is silent in British English…
        self.assertEqual(pronounce.transcription("car"), "/kɑː/")
        self.assertEqual(pronounce.transcription("water"), "/wɔːtə/")
        # …which makes these two words the same word to a British listener.
        self.assertTrue(pronounce.sound_alike("father", "farther"))
        # The R inside a word is still a sound the reader has to make.
        self.assertIn("r", [change["expected"] for change in pronounce.sound_changes("brother", "bother")])

    def test_words_an_american_says_differently(self):
        for word, kind in [("dance", "bath"), ("class", "bath"), ("water", "flap"),
                           ("new", "yod"), ("tomato", "lexical")]:
            self.assertEqual(pronounce.american_difference(word)["kind"], kind, word)
        self.assertEqual(pronounce.american_difference("dance")["british"], "/dɑːns/")
        self.assertEqual(pronounce.american_difference("dance")["american"], "/dæns/")
        # The accent's own system — the sounded R, the American O — is
        # taught as a pattern, not marked on every other word.
        for word in ["car", "market", "mother", "go", "hot", "the", "stories"]:
            self.assertIsNone(pronounce.american_difference(word), word)

    def test_one_word_again(self):
        self.assertTrue(listen.judge_word("three", heard("Three."))["ok"])
        self.assertFalse(listen.judge_word("three", heard("Tree."))["ok"])


class BritishTests(TestCase):
    def test_feedback_is_written_in_british_spelling(self):
        self.assertEqual(report.in_british_spelling("Practice saying it"), "Practise saying it")
        self.assertEqual(report.in_british_spelling("memorize the color"), "memorise the colour")
        # …without touching the noun, or words that only look American.
        self.assertEqual(report.in_british_spelling("Good practice, the size of the prize"),
                         "Good practice, the size of the prize")

    def test_the_reading_page_marks_words_americans_say_differently(self):
        user = User.objects.create_user(email="rp@example.com", password="pw-12345678",
                                        first_name="Ada", is_staff=True)
        passage = TutorPassage.objects.create(title="RP", level="Level 2",
                                              body="My brother asked for a glass of water.")
        self.client.force_login(user)
        page = self.client.get(f"/tutor/read/{passage.pk}/")
        self.assertContains(page, 'data-british="bath"')     # asked, glass
        self.assertContains(page, 'data-british="flap"')     # water
        self.assertContains(page, "British English")


class LevelTests(TestCase):
    def test_bands(self):
        self.assertEqual(report.band_for(0.97), TutorSession.BAND_INDEPENDENT)
        self.assertEqual(report.band_for(0.92), TutorSession.BAND_INSTRUCTIONAL)
        self.assertEqual(report.band_for(0.80), TutorSession.BAND_FRUSTRATION)

    def test_levels_stay_near_the_passage(self):
        # Fluent and accurate on Level 3: at most two levels above it.
        self.assertEqual(report.level_for("Level 3", TutorSession.BAND_INDEPENDENT, 200), "Level 5")
        # Accurate but slow: fluency decides.
        self.assertEqual(report.level_for("Level 3", TutorSession.BAND_INDEPENDENT, 95), "Level 2")
        # Right level to learn from.
        self.assertEqual(report.level_for("Level 3", TutorSession.BAND_INSTRUCTIONAL, 200), "Level 3")
        # Too hard: below the passage, never below Pre-Level.
        self.assertEqual(report.level_for("Level 3", TutorSession.BAND_FRUSTRATION, 200), "Level 2")
        self.assertEqual(report.level_for("Pre-Level", TutorSession.BAND_FRUSTRATION, 10), "Pre-Level")


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage",
                "OPTIONS": {"location": tempfile.mkdtemp(prefix="tutor-test-media-")}},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class EndpointTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="reader@example.com", password="pw-12345678", first_name="Ada",
                                             is_staff=True)
        # An ordinary learner, on the free trial every account starts with.
        self.other = User.objects.create_user(email="other@example.com", password="pw-12345678", first_name="Obi",
                                              role=User.Role.INDIVIDUAL)
        self.passage = TutorPassage.objects.create(title="Test", level="Level 2", body=BODY)
        self.client.force_login(self.user)

    def clip(self):
        return SimpleUploadedFile("clip.webm", b"\x1a\x45\xdf\xa3fake", content_type="audio/webm")

    def start(self):
        return self.client.post(f"/tutor/read/{self.passage.pk}/start/").json()["session"]

    def test_the_tutor_is_behind_the_subscription(self):
        self.assertIn("/tutor/", GATED_PREFIXES)

    def test_pages(self):
        self.assertEqual(self.client.get("/tutor/").status_code, 200)
        page = self.client.get(f"/tutor/read/{self.passage.pk}/")
        self.assertContains(page, 'data-s="1"')
        self.assertContains(page, "three")

    @mock.patch("apps.tutor.report._ask", side_effect=ValueError("offline"))
    @mock.patch("apps.tutor.listen.transcribe")
    def test_a_whole_reading(self, transcribe, _ask):
        session = self.start()
        check = f"/tutor/session/{session}/check/"

        transcribe.return_value = heard("I have a red hat.")
        first = self.client.post(check, {"sentence": 0, "audio": self.clip()}).json()["sentence"]
        self.assertEqual(first["model"], [])

        transcribe.return_value = heard("He gave me tree ripe mangoes.")
        second = self.client.post(check, {"sentence": 1, "audio": self.clip()}).json()["sentence"]
        self.assertEqual(second["model"], [3])

        transcribe.return_value = heard("three")
        again = self.client.post(check, {"sentence": 1, "word": 3, "audio": self.clip()}).json()
        self.assertTrue(again["word"]["ok"])

        # A second reading of a sentence is practice; the first is scored.
        transcribe.return_value = heard("He gave me three ripe mangoes.")
        self.client.post(check, {"sentence": 1, "audio": self.clip()})

        transcribe.return_value = heard("The soup is very hot.")
        self.client.post(check, {"sentence": 2, "audio": self.clip()})

        done = self.client.post(f"/tutor/session/{session}/finish/").json()
        reading = TutorSession.objects.get(pk=session)
        self.assertEqual(done["report"], f"/tutor/session/{session}/")
        self.assertEqual(reading.status, TutorSession.STATUS_DONE)
        self.assertEqual((reading.words_correct, reading.words_total), (15, 16))
        self.assertEqual(reading.band, TutorSession.BAND_INSTRUCTIONAL)   # 15/16 = 94%
        self.assertEqual(reading.practised, {"three": {"tries": 1, "ok": True}})
        self.assertEqual(reading.patterns[0]["words"], ["three"])
        self.assertEqual(reading.feedback["source"], "rules")
        page = self.client.get(done["report"])
        self.assertContains(page, "Words to practise")
        self.assertContains(page, "You said “tree”")

    @mock.patch("apps.tutor.listen.transcribe_file")
    def test_a_recording_sent_while_it_is_spoken(self, transcribe_file):
        """The page sends the reading in pieces as it is read, then names it
        in the check — so when the reader stops, nothing is left to upload."""
        session = self.start()
        sent = self.client.post(f"/tutor/session/{session}/piece/",
                                {"clip": "abc123", "piece": 0, "audio": self.clip()})
        self.assertEqual(sent.status_code, 200)
        joined = {}

        def read_it(path, *args, **kwargs):
            with open(path, "rb") as handle:
                joined["bytes"] = handle.read()
            return heard("I have a red hat.")

        transcribe_file.side_effect = read_it
        reply = self.client.post(f"/tutor/session/{session}/check/",
                                 {"sentence": 0, "clip": "abc123", "piece": 1, "audio": self.clip()})
        self.assertEqual(reply.json()["sentence"]["right"], 5)
        # Both pieces were joined, in order, into the one recording.
        self.assertEqual(joined["bytes"], self.clip().read() * 2)
        # And the pieces are cleared away afterwards.
        self.assertFalse(os.path.isdir(listen.clip_folder(session, "abc123")))

    @mock.patch("apps.tutor.listen.transcribe", side_effect=listen.NotHeard("quiet"))
    def test_silence_is_not_a_mistake(self, _transcribe):
        session = self.start()
        reply = self.client.post(f"/tutor/session/{session}/check/", {"sentence": 0, "audio": self.clip()}).json()
        self.assertEqual(reply, {"heard": False})
        self.assertEqual(TutorSession.objects.get(pk=session).sentences, {})

    def test_someone_elses_reading_is_private(self):
        session = self.start()
        other = self.client_class()
        other.force_login(self.other)
        self.assertEqual(other.get("/tutor/").status_code, 200)   # they can use the tutor…
        self.assertEqual(other.get(f"/tutor/session/{session}/say/", {"sentence": 0}).status_code, 404)
        self.assertEqual(other.post(f"/tutor/session/{session}/finish/").status_code, 404)

    @mock.patch("apps.tutor.voice.keep_later")
    @mock.patch("apps.tutor.voice.make", return_value=b"ID3" + b"\x00" * 3000)
    def test_the_voice_only_says_words_from_the_passage(self, make, keep_later):
        session = self.start()
        say = f"/tutor/session/{session}/say/"
        reply = self.client.get(say, {"sentence": 1, "word": 3})
        self.assertEqual(reply.status_code, 200)
        self.assertEqual(reply["Content-Type"], "audio/mpeg")
        make.assert_called_with("three", single_word=True, chosen=mock.ANY)
        keep_later.assert_called_once()
        # Safari asks for a byte range.
        part = self.client.get(say, {"sentence": 1, "word": 3}, HTTP_RANGE="bytes=0-1")
        self.assertEqual(part.status_code, 206)
        self.assertEqual(part.content, b"ID")
        # Nothing outside the passage can be spoken.
        self.assertEqual(self.client.get(say, {"sentence": 9}).status_code, 404)
        self.assertEqual(self.client.get(say, {"sentence": 1, "word": 99}).status_code, 404)

    @mock.patch("apps.tutor.voice.make", return_value=None)
    def test_no_voice_means_the_browser_speaks(self, _make):
        session = self.start()
        self.assertEqual(self.client.get(f"/tutor/session/{session}/say/", {"sentence": 0}).status_code, 204)

    def test_finishing_needs_a_sentence(self):
        session = self.start()
        self.assertEqual(self.client.post(f"/tutor/session/{session}/finish/").status_code, 400)


class TutorVoiceTests(TestCase):
    """Choosing who reads with you: the voice, and the face that speaks."""

    def setUp(self):
        from apps.tutor.models import TutorVoice

        self.user = User.objects.create_user(email="pick@example.com", password="pw-12345678", first_name="Ada")
        self.client.force_login(self.user)
        self.yela = TutorVoice.objects.filter(name="Yela").first() or TutorVoice.objects.create(
            name="Yela", gender="female", avatar="yela", is_default=True)
        self.kayode = TutorVoice.objects.filter(name="Kayode").first() or TutorVoice.objects.create(
            name="Kayode", gender="male", avatar="kayode")

    def test_the_hub_offers_every_voice_with_its_face(self):
        page = self.client.get("/tutor/")
        self.assertContains(page, "Who reads with you")
        self.assertContains(page, "Yela")
        self.assertContains(page, "Kayode")
        self.assertContains(page, 'class="av av--kayode"')
        self.assertContains(page, "data-gender=\"male\"")
        self.assertContains(page, f'/tutor/voice/{self.kayode.pk}/sample/')

    def test_a_learner_chooses_and_it_is_remembered(self):
        from apps.tutor.models import TutorChoice
        from apps.tutor.voice import for_user

        self.assertEqual(for_user(self.user), self.yela)           # the default to begin with
        self.client.post("/tutor/voice/", {"voice": self.kayode.pk})
        self.assertEqual(TutorChoice.objects.get(user=self.user).voice, self.kayode)
        self.assertEqual(for_user(self.user), self.kayode)
        passage = TutorPassage.objects.filter(is_published=True).first()
        if passage:
            page = self.client.get(f"/tutor/read/{passage.pk}/")
            self.assertContains(page, "av--kayode")
            self.assertContains(page, "Kayode")

    def test_a_voice_that_is_off_is_not_offered_or_chosen(self):
        self.kayode.is_active = False
        self.kayode.save()
        self.assertNotContains(self.client.get("/tutor/"), "av--kayode")
        self.client.post("/tutor/voice/", {"voice": self.kayode.pk})
        from apps.tutor.voice import for_user

        self.assertEqual(for_user(self.user), self.yela)

    def test_each_voice_keeps_its_own_recordings(self):
        from apps.tutor.models import TutorSpeech

        one = TutorSpeech.key_for("the village", "voice-a")
        two = TutorSpeech.key_for("the village", "voice-b")
        self.assertNotEqual(one, two)
        self.assertEqual(one, TutorSpeech.key_for("The  Village", "voice-a"))

    def test_only_one_voice_is_the_default(self):
        from apps.tutor.models import TutorVoice

        self.kayode.is_default = True
        self.kayode.save()
        self.yela.refresh_from_db()
        self.assertFalse(self.yela.is_default)
        self.assertEqual(TutorVoice.objects.filter(is_default=True).count(), 1)

    def test_staff_manage_voices_in_the_control_room(self):
        staff = User.objects.create_user(email="sam@example.com", password="pw-12345678", first_name="Sam",
                                         is_staff=True, is_superuser=True)
        self.client.force_login(staff)
        listing = self.client.get("/manage/tutor-voices/")
        self.assertContains(listing, "Yela")
        form = self.client.get("/manage/tutor-voices/new/")
        self.assertContains(form, "ElevenLabs voice id")


class StoryFirstTests(TestCase):
    """The tutor reads the whole story before the learner tries it."""

    def setUp(self):
        self.user = User.objects.create_user(email="listen@example.com", password="pw-12345678", first_name="Ada")
        self.client.force_login(self.user)
        self.passage = TutorPassage.objects.filter(is_published=True).first() or TutorPassage.objects.create(
            title="My Red Hat", level="Pre-Level", body="I have a red hat. My hat is on the bed.")

    def test_the_reading_page_offers_it(self):
        page = self.client.get(f"/tutor/read/{self.passage.pk}/")
        self.assertContains(page, "Hear the story first")
        self.assertContains(page, f"/tutor/read/{self.passage.pk}/hear/")

    @mock.patch("apps.tutor.voice.keep_later")
    @mock.patch("apps.tutor.voice.make", return_value=b"ID3" + b"\x00" * 900)
    def test_each_sentence_can_be_heard_before_starting(self, make, keep_later):
        url = f"/tutor/read/{self.passage.pk}/hear/"
        answer = self.client.get(url, {"sentence": 0})
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer["Content-Type"], "audio/mpeg")
        spoken = make.call_args.args[0]
        self.assertIn(spoken.split(".")[0], self.passage.body)
        # Nothing outside the passage, and nobody else's passage.
        self.assertEqual(self.client.get(url, {"sentence": 99}).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(url, {"sentence": 0}).status_code, 302)


class AvatarTests(TestCase):
    """The face: drawn by default, or a portrait an admin uploads."""

    def setUp(self):
        self.user = User.objects.create_user(email="face@example.com", password="pw-12345678", first_name="Ada")
        self.client.force_login(self.user)

    @override_settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
                                 "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
    def test_a_portrait_is_shown_instead_of_the_drawn_face(self):
        from apps.tutor.models import TutorVoice

        one_pixel = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
                     b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00"
                     b"\x00\x00IEND\xaeB`\x82")
        voice = TutorVoice.objects.create(
            name="Zara", gender="female", avatar="yela", is_default=True,
            portrait=SimpleUploadedFile("zara.png", one_pixel, content_type="image/png"))
        self.assertTrue(voice.face)
        page = self.client.get("/tutor/")
        self.assertContains(page, "av--photo")
        self.assertContains(page, "av__photo")
        self.assertContains(page, 'alt="Zara"')

    def test_the_drawn_face_is_used_when_there_is_no_portrait(self):
        from apps.tutor.models import TutorVoice

        TutorVoice.objects.create(name="Plain", gender="male", avatar="tobi", is_default=True)
        page = self.client.get("/tutor/")
        self.assertContains(page, "av--tobi")
        self.assertNotContains(page, "av__photo")
        # Shaded, not flat: the face is drawn with light and shadow.
        self.assertContains(page, "av-skin-tobi")
        self.assertContains(page, "av__rim")
