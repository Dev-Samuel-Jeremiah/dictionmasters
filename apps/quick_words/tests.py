import json
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from . import british_ipa
from .british_ipa import get_british_ipa, normalize_british_ipa, normalize_word
from .ipa_dict import load_ipa_dict
from .models import QuickWord


class BritishIPADatasetTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        british_ipa.load_britfone.cache_clear()
        load_ipa_dict.cache_clear()
        super().tearDownClass()

    def test_britfone_target_words_and_variants(self):
        expected = {
            "conversation": "/ˌkɒnvəˈseɪʃən/",
            "computer": "/kəmˈpjuːtə/",
            "teacher": "/ˈtiːtʃə/",
            "student": "/ˈstjuːdənt/",
        }
        for word, ipa in expected.items():
            with self.subTest(word=word):
                result = get_british_ipa(word, allow_ai=False)
                self.assertEqual(result["ipa"], ipa)
                self.assertEqual(result["source"], "britfone")
                self.assertEqual(result["confidence"], "dictionary")
                self.assertFalse(result["review_required"])

        for word in ("schedule", "advertisement", "garage"):
            with self.subTest(word=word):
                result = get_british_ipa(word, allow_ai=False)
                self.assertEqual(result["source"], "britfone")
                self.assertGreaterEqual(len(result["pronunciations"]), 2)

    def test_conductor_uses_ipa_dict_without_ai(self):
        with mock.patch(
            "apps.quick_words.lookup.lookup_ipa_with_openai",
            side_effect=AssertionError("AI should not be called for dictionary IPA"),
        ):
            result = get_british_ipa("conductor")
        self.assertEqual(result["ipa"], "/kənˈdʌktə/")
        self.assertEqual(result["source"], "ipa_dict")
        self.assertEqual(result["confidence"], "dictionary")
        self.assertFalse(result["review_required"])

    def test_normalizes_case_and_surrounding_whitespace(self):
        for word in ("CONDUCTOR", "Conductor", " conductor "):
            with self.subTest(word=word):
                self.assertEqual(get_british_ipa(word, allow_ai=False)["word"], "conductor")
        self.assertEqual(normalize_word("  DON’T  "), "don’t")
        self.assertTrue(normalize_word("e\u0301cole").startswith("é"))

    def test_normalizer_preserves_phonetic_distinctions_and_structure(self):
        ipa = " [ ˈɹ ɛ ɐ ʌ . ɜː ] "
        self.assertEqual(normalize_british_ipa(ipa), "/ˈɹ ɛ ɐ ʌ . ɜː/")

    def test_documented_source_symbols_and_stress_style_are_normalized(self):
        self.assertEqual(
            normalize_british_ipa("/ɐ ɹ ɛ ɜː/", source="britfone"),
            "/ʌ r e ɜː/",
        )
        self.assertEqual(
            normalize_british_ipa("/kəndˈʌktɐ/", source="ipa_dict"),
            "/kənˈdʌktə/",
        )

    def test_dataset_is_loaded_once_per_process(self):
        british_ipa.load_britfone.cache_clear()
        from unittest.mock import mock_open

        reader = mock_open(read_data="CACHEWORD, k ˈæ ʃ\n")
        with mock.patch("builtins.open", reader):
            first = get_british_ipa("cacheword", allow_ai=False)
            second = get_british_ipa("CACHEWORD", allow_ai=False)
        self.assertEqual(first["ipa"], "/ˈkæʃ/")
        self.assertEqual(second["ipa"], first["ipa"])
        reader.assert_called_once()
        british_ipa.load_britfone.cache_clear()


class BritishIPAPriorityTests(TestCase):
    def setUp(self):
        cache.clear()

    def make_word(self, **kwargs):
        defaults = {
            "word": "testword",
            "slug": "testword",
            "ipa": "/ˈtɛstwɜːd/",
            "ipa_accent": "en-GB",
            "ipa_source": "database",
            "ipa_confidence": "verified",
            "ipa_review_required": False,
            "definition": "A word used for testing.",
        }
        defaults.update(kwargs)
        return QuickWord.objects.create(**defaults)

    def test_britfone_precedes_ipa_dict_database_and_ai(self):
        self.make_word()
        with (
            mock.patch("apps.quick_words.british_ipa.load_britfone", return_value={
                "testword": ("/ˈtɛstwɜːd/",),
            }),
            mock.patch("apps.quick_words.british_ipa.load_ipa_dict", return_value={
                "testword": ("/tɛst/",),
            }),
            mock.patch(
                "apps.quick_words.lookup.lookup_ipa_with_openai",
                side_effect=AssertionError("AI must be last"),
            ),
        ):
            result = get_british_ipa("testword")
        self.assertEqual(result["source"], "britfone")

    def test_ipa_dict_precedes_database_and_ai(self):
        self.make_word()
        with (
            mock.patch("apps.quick_words.british_ipa.load_britfone", return_value={}),
            mock.patch("apps.quick_words.british_ipa.load_ipa_dict", return_value={
                "testword": ("/tɛst/",),
            }),
            mock.patch(
                "apps.quick_words.lookup.lookup_ipa_with_openai",
                side_effect=AssertionError("AI must be last"),
            ),
        ):
            result = get_british_ipa("testword")
        self.assertEqual(result["ipa"], "/test/")
        self.assertEqual(result["source"], "ipa_dict")

    def test_verified_database_is_used_before_ai(self):
        self.make_word()
        with (
            mock.patch("apps.quick_words.british_ipa.load_britfone", return_value={}),
            mock.patch("apps.quick_words.british_ipa.load_ipa_dict", return_value={}),
            mock.patch(
                "apps.quick_words.lookup.lookup_ipa_with_openai",
                side_effect=AssertionError("saved IPA must precede AI"),
            ),
        ):
            result = get_british_ipa("testword")
        self.assertEqual(result["source"], "database")
        self.assertEqual(result["confidence"], "verified")
        self.assertFalse(result["review_required"])

    def test_ai_fallback_is_marked_for_review(self):
        with (
            mock.patch("apps.quick_words.british_ipa.load_britfone", return_value={}),
            mock.patch("apps.quick_words.british_ipa.load_ipa_dict", return_value={}),
            mock.patch(
                "apps.quick_words.lookup.lookup_ipa_with_openai",
                return_value="/ˈnɒn.wɜːd/",
            ) as ai,
        ):
            result = get_british_ipa("unknown-word")
        ai.assert_called_once_with("unknown-word")
        self.assertEqual(result["source"], "openai")
        self.assertEqual(result["confidence"], "ai")
        self.assertTrue(result["review_required"])

    def test_invalid_ai_prose_is_rejected(self):
        with (
            mock.patch("apps.quick_words.british_ipa.load_britfone", return_value={}),
            mock.patch("apps.quick_words.british_ipa.load_ipa_dict", return_value={}),
            mock.patch(
                "apps.quick_words.lookup.lookup_ipa_with_openai",
                return_value="The British pronunciation is /ˈwɜːd/.",
            ),
        ):
            result = get_british_ipa("unknown-word")
        self.assertIsNone(result["ipa"])
        self.assertIsNone(result["source"])
        self.assertTrue(result["review_required"])

    def test_malformed_ai_stress_marks_are_rejected(self):
        with (
            mock.patch("apps.quick_words.british_ipa.load_britfone", return_value={}),
            mock.patch("apps.quick_words.british_ipa.load_ipa_dict", return_value={}),
            mock.patch(
                "apps.quick_words.lookup.lookup_ipa_with_openai",
                return_value="/ˈˌwɜːd/",
            ),
        ):
            result = get_british_ipa("unknown-word")
        self.assertIsNone(result["ipa"])
        self.assertTrue(result["review_required"])

    def test_missing_pronunciation_has_structured_empty_result(self):
        with (
            mock.patch("apps.quick_words.british_ipa.load_britfone", return_value={}),
            mock.patch("apps.quick_words.british_ipa.load_ipa_dict", return_value={}),
        ):
            result = get_british_ipa("unknown-word", allow_ai=False)
        self.assertEqual(result["word"], "unknown-word")
        self.assertIsNone(result["ipa"])
        self.assertIsNone(result["source"])
        self.assertIsNone(result["confidence"])
        self.assertTrue(result["review_required"])


class QuickWordLookupIntegrationTests(TestCase):
    def test_existing_openai_details_use_dictionary_ipa_and_metadata(self):
        from . import lookup as lookup_module

        details = {
            "is_word": True,
            "word": "conductor",
            "definition": "A person who directs an orchestra or train.",
            "example_sentence": "The conductor raised her baton.",
            "synonyms": "director",
            "level": "Level 6",
        }
        with (
            mock.patch.object(lookup_module, "_ask_openai", return_value=details),
            mock.patch.object(
                lookup_module,
                "lookup_ipa_with_openai",
                side_effect=AssertionError("dictionary pronunciation should prevent AI IPA"),
            ),
        ):
            result = lookup_module.lookup("conductor")
        self.assertEqual(result["ipa"], "/kənˈdʌktə/")
        self.assertEqual(result["ipa_source"], "ipa_dict")
        self.assertEqual(result["ipa_confidence"], "dictionary")
        self.assertFalse(result["ipa_review_required"])
        self.assertEqual(result["definition"], details["definition"])

    def test_api_response_keeps_existing_fields_and_adds_ipa_metadata(self):
        from django.test import RequestFactory

        from .views import _lookup_response

        word = QuickWord.objects.create(
            word="schedule",
            slug="schedule",
            ipa="/ˈʃedʒuːl/, /ˈskedʒuːl/",
            ipa_source="britfone",
            ipa_confidence="dictionary",
            ipa_review_required=False,
            definition="A plan of activities.",
        )
        request = RequestFactory().post(
            "/quick-words/lookup/", HTTP_ACCEPT="application/json"
        )
        response = _lookup_response(request, 201, word=word, created=True)
        payload = json.loads(response.content)
        self.assertEqual(payload["word"], "schedule")
        self.assertTrue(payload["created"])
        self.assertEqual(payload["ipa"], word.ipa)
        self.assertEqual(payload["ipa_source"], "britfone")
        self.assertEqual(payload["ipa_confidence"], "dictionary")
        self.assertFalse(payload["ipa_review_required"])
        self.assertEqual(payload["ipa_accent"], "en-GB")

    def test_saved_ai_ipa_is_refreshed_from_a_trusted_dictionary(self):
        from .views import _refresh_trusted_ipa

        word = QuickWord.objects.create(
            word="conductor",
            slug="conductor",
            ipa="/ˈkəndʌktə/",
            ipa_source="openai",
            ipa_confidence="ai",
            ipa_review_required=True,
            definition="A person who directs an orchestra.",
        )
        refreshed = _refresh_trusted_ipa(word)
        self.assertEqual(refreshed.ipa, "/kənˈdʌktə/")
        self.assertEqual(refreshed.ipa_source, "ipa_dict")
        self.assertEqual(refreshed.ipa_confidence, "dictionary")
        self.assertFalse(refreshed.ipa_review_required)
