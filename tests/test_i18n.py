import string
import unittest

from services.i18n import (
    DEFAULT_LANGUAGE,
    MESSAGES,
    SUPPORTED_LANGUAGES,
    ai_language,
    normalize_language,
    t,
)


def _fields(value: str) -> set[str]:
    return {
        field_name
        for _, field_name, _, _ in string.Formatter().parse(value)
        if field_name
    }


class I18nTests(unittest.TestCase):
    def test_catalogs_have_the_same_keys_and_format_fields(self):
        for key, translations in MESSAGES.items():
            with self.subTest(key=key):
                for lang in SUPPORTED_LANGUAGES:
                    self.assertIn(lang, translations)
                    self.assertTrue(translations[lang])
                self.assertEqual(_fields(translations["en"]), _fields(translations["ru"]))

    def test_runtime_translations(self):
        self.assertEqual(t("button.save", "ru"), "✓ Сохранить")
        self.assertEqual(t("button.save", "en"), "✓ Save")
        self.assertEqual(t("language.changed", "ru", language_name="Русский"), "Язык переключен на Русский.")
        self.assertEqual(t("language.changed", "en", language_name="English"), "Language switched to English.")

    def test_missing_key_falls_back_to_key(self):
        self.assertEqual(t("unknown.key", "en"), "unknown.key")
        self.assertEqual(t("unknown.key", "ru"), "unknown.key")

    def test_language_codes_normalize_to_supported_base_language(self):
        self.assertEqual(normalize_language("ru-RU"), "ru")
        self.assertEqual(normalize_language("ru_RU"), "ru")
        self.assertEqual(normalize_language("en-US"), "en")
        self.assertEqual(normalize_language("fr"), "en")
        self.assertEqual(normalize_language(None), DEFAULT_LANGUAGE)
        self.assertEqual(normalize_language(""), DEFAULT_LANGUAGE)

    def test_ai_language_names(self):
        self.assertEqual(ai_language("en"), "English")
        self.assertEqual(ai_language("ru"), "Russian")
        self.assertEqual(ai_language("unknown"), "English")
