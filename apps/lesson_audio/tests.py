"""Lesson Notes to Audio. Nothing here reaches OpenAI or ElevenLabs."""

import json
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.accounts.models import User
from apps.book.models import ReadAlongTiming

from . import services
from .models import Job, KeyWord, LessonNote, spoken_text

STORAGE = {"default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
           "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}
NOTE = "Topic: Photosynthesis\n\nObjectives\n- Define photosynthesis.\n\nPlants make food using chlorophyll."


@override_settings(STORAGES=STORAGE, LESSON_AUDIO_SYNC=True, OPENAI_API_KEY="test", ELEVENLABS_API_KEY="test",
                   ELEVENLABS_VOICE_ID="voice", SUBSCRIPTION_REQUIRED=False)
class LessonAudioTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user("t@example.com", "pw-12345678", first_name="Ada", role="teacher")
        self.client.force_login(self.teacher)

    def note(self, **extra):
        return LessonNote.objects.create(owner=self.teacher, title="Photosynthesis", body=NOTE, **extra)

    # -- who can use it ---------------------------------------------------
    def test_students_are_turned_away(self):
        student = User.objects.create_user("s@example.com", "pw-12345678", first_name="Bo", role="student")
        self.client.force_login(student)
        self.assertEqual(self.client.get("/lesson-audio/").status_code, 403)

    def test_a_teacher_cannot_open_someone_elses_note(self):
        other = User.objects.create_user("o@example.com", "pw-12345678", first_name="Oti", role="teacher")
        note = LessonNote.objects.create(owner=other, title="Theirs", body=NOTE)
        self.assertEqual(self.client.get(f"/lesson-audio/{note.pk}/").status_code, 404)

    # -- making a note ----------------------------------------------------
    @mock.patch.object(services, "start_keywords")
    def test_a_typed_note_is_saved_and_its_key_words_started(self, start_keywords):
        response = self.client.post("/lesson-audio/new/", {"mode": "typed", "title": "Photosynthesis", "body": NOTE})
        note = LessonNote.objects.get()
        self.assertRedirects(response, f"/lesson-audio/{note.pk}/", fetch_redirect_response=False)
        self.assertEqual(note.source, "typed")
        start_keywords.assert_called_once()

    @mock.patch.object(services, "start_keywords")
    @mock.patch.object(services, "_ask", return_value={"title": "Nouns", "body": "Topic: Nouns\n\n" + "A noun names a thing. " * 40})
    def test_ai_writes_a_note(self, _ask, _start):
        self.client.post("/lesson-audio/new/", {"mode": "ai", "topic": "Nouns", "class_level": "Primary 3"})
        note = LessonNote.objects.get()
        self.assertEqual((note.title, note.source), ("Nouns", "ai"))
        self.assertIn("Class: Primary 3", _ask.call_args.args[1])

    @mock.patch.object(services, "start_keywords")
    def test_an_old_word_file_is_explained(self, _start):
        upload = SimpleUploadedFile("note.doc", b"binary")
        response = self.client.post("/lesson-audio/new/", {"mode": "upload", "files": [upload]}, follow=True)
        self.assertContains(response, "Old Word files (.doc)")
        self.assertFalse(LessonNote.objects.exists())

    @mock.patch.object(services, "start_keywords")
    def test_a_text_file_is_read(self, _start):
        upload = SimpleUploadedFile("week-3-nouns.txt", b"Topic: Nouns\n\nA noun is a naming word.")
        self.client.post("/lesson-audio/new/", {"mode": "upload", "files": [upload]})
        note = LessonNote.objects.get()
        self.assertEqual(note.title, "Nouns")
        self.assertIn("naming word", note.body)

    # -- the voice --------------------------------------------------------
    def test_the_voice_reads_without_bullets_and_markdown(self):
        self.assertEqual(spoken_text("## Objectives\n- Define it.\n* **Name** them."),
                         "Objectives\n\nDefine it.\n\nName them.")

    @mock.patch("apps.diction_library.narration.read_chapter",
                return_value=(b"ID3mp3", [["Topic:", 0.0, 0.4], ["Photosynthesis", 0.5, 1.2]], 1.5))
    def test_audio_is_made_with_exact_timings(self, read_chapter):
        note = self.note()
        response = self.client.post(f"/lesson-audio/{note.pk}/audio/", {"voice": "JBFqnCBsd6RMkjVDRZzb"},
                                    HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.json()["audio"], Job.READY)
        note.refresh_from_db()
        self.assertTrue(note.audio_is_current)
        self.assertEqual(read_chapter.call_args.kwargs["voice"], "JBFqnCBsd6RMkjVDRZzb")
        self.assertEqual(read_chapter.call_args.args[0][2], "Define photosynthesis.")
        timing = ReadAlongTiming.objects.get(object_id=note.pk)
        self.assertEqual((timing.engine, len(timing.words)), ("voice", 2))
        # Editing the note leaves the audio, marked out of date.
        note.body += "\n\nAssignment"
        note.save()
        self.assertFalse(note.audio_is_current)

    def test_a_note_too_long_for_one_recording_is_refused(self):
        note = self.note()
        note.body = "word " * 6000
        note.save()
        with override_settings(LESSON_AUDIO_MAX_CHARS=1000):
            response = self.client.post(f"/lesson-audio/{note.pk}/audio/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Split it into two notes", response.json()["error"])

    def test_the_daily_audio_allowance(self):
        note = self.note()
        services.record(self.teacher, "audio", 59990)
        with self.assertRaises(services.LessonAudioError):
            services.start_audio(note)

    # -- key words --------------------------------------------------------
    @mock.patch.object(services, "_word_audio", return_value=b"ID3")
    @mock.patch.object(services, "_ask", return_value={"words": [
        {"word": "chlorophyll", "meaning": "The green colouring in leaves.", "ipa": "/ˈklɒrəfɪl/", "syllables": "CHLOR·o·phyll", "tip": ""},
        {"word": "banana", "meaning": "Not in the note.", "ipa": "/bəˈnɑːnə/", "syllables": "ba·NA·na", "tip": ""},
    ]})
    def test_key_words_must_come_from_the_note(self, _ask, _audio):
        note = self.note()
        services.start_keywords(note)
        note.refresh_from_db()
        self.assertEqual(note.keywords_status, Job.READY)
        self.assertEqual([w.word for w in note.keywords.all()], ["chlorophyll"])
        self.assertTrue(note.keywords.get().audio_file)

    def test_a_dictionary_ipa_that_stresses_another_syllable_is_not_used(self):
        self.assertEqual(services._stressed_syllable_in_ipa("/ˌklɔːrəʊˈfɪl/"), 2)
        self.assertEqual(services._stressed_syllable_in_spelling("CHLOR·o·phyll"), 0)
        self.assertEqual(services._stressed_syllable_in_spelling("pho·to·SYN·the·sis"), 2)

    @mock.patch("apps.tutor.listen.transcribe", return_value=[("chlorophyll", 0.1, 0.8)])
    def test_practising_a_word(self, _transcribe):
        note = self.note()
        word = KeyWord.objects.create(note=note, word="chlorophyll")
        audio = SimpleUploadedFile("word.webm", b"x" * 2000, content_type="audio/webm")
        result = self.client.post(f"/lesson-audio/{note.pk}/words/{word.pk}/practise/", {"audio": audio}).json()
        self.assertTrue(result["ok"])
        self.assertEqual((result["mastered_total"], result["total"]), (1, 1))

    def test_deleting_a_note_removes_its_words(self):
        note = self.note()
        KeyWord.objects.create(note=note, word="chlorophyll")
        self.client.post(f"/lesson-audio/{note.pk}/delete/")
        self.assertFalse(LessonNote.objects.exists())
        self.assertFalse(KeyWord.objects.exists())


@override_settings(STORAGES=STORAGE, LESSON_AUDIO_SYNC=True, OPENAI_API_KEY="test", ELEVENLABS_API_KEY="test",
                   ELEVENLABS_VOICE_ID="voice")
class SchoolLibraryTests(TestCase):
    def setUp(self):
        from apps.schools.models import School

        self.school = School.objects.create(name="Unity School", email="unity@example.com")
        self.author = User.objects.create_user("a@example.com", "pw-12345678", first_name="Ada", last_name="Obi",
                                               role="teacher", school=self.school)
        self.colleague = User.objects.create_user("c@example.com", "pw-12345678", first_name="Chi", role="teacher",
                                                  school=self.school)
        self.note = LessonNote.objects.create(owner=self.author, school=self.school, title="Photosynthesis",
                                              subject="Basic Science", body=NOTE, audio_file="lesson_audio/p.mp3",
                                              audio_text=spoken_text(NOTE), audio_status=Job.READY)
        self.word = KeyWord.objects.create(note=self.note, word="chlorophyll", ipa="/ˈklɒrəfɪl/",
                                           audio_file="lesson_audio/words/chlorophyll.mp3")
        self.client.force_login(self.colleague)

    def test_colleagues_find_the_note_by_searching(self):
        response = self.client.get("/lesson-audio/?q=photosynthesis")
        self.assertContains(response, "From the Unity School library")
        self.assertContains(response, "By Ada Obi")

    def test_other_schools_cannot_see_it(self):
        from apps.schools.models import School

        outsider = User.objects.create_user("o@example.com", "pw-12345678", first_name="Oti", role="teacher",
                                            school=School.objects.create(name="Elsewhere", email="e@example.com"))
        self.client.force_login(outsider)
        self.assertNotContains(self.client.get("/lesson-audio/?q=photosynthesis"), "By Ada Obi")
        self.assertEqual(self.client.get(f"/lesson-audio/{self.note.pk}/").status_code, 404)

    def test_a_colleague_reads_listens_and_downloads_but_does_not_edit(self):
        page = self.client.get(f"/lesson-audio/{self.note.pk}/")
        self.assertContains(page, "Make my own copy")
        self.assertContains(page, "data-offline-keep")                 # Save for offline
        self.assertNotContains(page, "data-la-edit-form")
        self.assertNotContains(page, "p.mp3")                           # the file's address is never shown
        self.client.post(f"/lesson-audio/{self.note.pk}/save/", {"body": "Changed"})
        self.note.refresh_from_db()
        self.assertEqual(self.note.body, NOTE)
        word = self.client.get(f"/lesson-audio/{self.note.pk}/download/")
        self.assertEqual(word["Content-Type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertIn("photosynthesis.docx", word["Content-Disposition"])
        self.assertEqual(self.client.get(f"/lesson-audio/{self.note.pk}/download/?text=1")["Content-Type"],
                         word["Content-Type"])                          # no MP3 or plain text any more

    @mock.patch("apps.tutor.listen.transcribe", return_value=[("chlorophyll", 0.1, 0.8)])
    def test_a_colleagues_practice_does_not_change_the_authors_progress(self, _hear):
        audio = SimpleUploadedFile("w.webm", b"x" * 2000, content_type="audio/webm")
        result = self.client.post(f"/lesson-audio/{self.note.pk}/words/{self.word.pk}/practise/", {"audio": audio}).json()
        self.assertTrue(result["ok"])
        self.word.refresh_from_db()
        self.assertEqual((self.word.attempts, self.word.mastered), (0, False))

    def test_a_copy_shares_the_recordings_and_deleting_it_keeps_them(self):
        response = self.client.post(f"/lesson-audio/{self.note.pk}/copy/")
        copy = LessonNote.objects.exclude(pk=self.note.pk).get()
        self.assertRedirects(response, f"/lesson-audio/{copy.pk}/", fetch_redirect_response=False)
        self.assertEqual((copy.owner, copy.audio_file.name, copy.keywords.get().audio_file.name),
                         (self.colleague, self.note.audio_file.name, self.word.audio_file.name))
        with mock.patch("django.core.files.storage.InMemoryStorage.delete") as delete:
            services.delete_note(copy)
        delete.assert_not_called()                                       # the original still uses them

    def test_notes_are_saved_to_the_school_and_autosave_answers_json(self):
        self.client.force_login(self.author)
        response = self.client.post(f"/lesson-audio/{self.note.pk}/save/", {"title": "Photosynthesis", "body": NOTE + "\n\nAssignment"},
                                    HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertFalse(response.json()["audio_current"])
        with mock.patch.object(services, "start_keywords"):
            self.client.post("/lesson-audio/new/", {"mode": "typed", "title": "Nouns", "body": "A noun names things."})
        self.assertEqual(LessonNote.objects.get(title="Nouns").school, self.school)


@override_settings(OPENAI_API_KEY="test", ELEVENLABS_API_KEY="test", ELEVENLABS_VOICE_ID="site-voice")
class KeyWordVoiceTests(TestCase):
    def test_words_use_the_site_voice_and_the_accurate_model_first(self):
        with mock.patch("apps.quick_words.speech.urllib.request.urlopen") as urlopen, \
                mock.patch.object(services, "heard_right", return_value=True):
            urlopen.return_value.__enter__.return_value.read.return_value = b"ID3" + b"x" * 3000
            services._word_audio("hyperbole")
        request = urlopen.call_args.args[0]
        body = json.loads(request.data)
        self.assertIn("/site-voice", request.full_url)                 # strictly ELEVENLABS_VOICE_ID
        self.assertEqual((body["model_id"], body["text"]), ("eleven_turbo_v2_5", "hyperbole."))
        self.assertTrue(body["voice_settings"]["use_speaker_boost"])

    def test_a_misheard_word_is_made_again_with_the_next_model(self):
        said = {"eleven_turbo_v2_5": b"A", "eleven_v3": b"B", "eleven_multilingual_v2": b"C"}
        with mock.patch.object(services, "_say", side_effect=lambda w, m: said[m]), \
                mock.patch.object(services, "heard_right", side_effect=lambda w, a: a == b"B"):
            self.assertEqual(services._word_audio("quinoa"), b"B")

    def test_when_every_model_is_misheard_the_best_models_recording_is_kept(self):
        with mock.patch.object(services, "_say", side_effect=lambda w, m: m.encode()), \
                mock.patch.object(services, "heard_right", return_value=False):
            self.assertEqual(services._word_audio("quay"), b"eleven_turbo_v2_5")
