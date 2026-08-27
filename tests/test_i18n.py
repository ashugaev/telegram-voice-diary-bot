import string
import unittest
from pathlib import Path

from services.i18n import SUPPORTED_LANGUAGES, normalize_language, t


LOCALE_DIR = Path("services/locale")


def _po_unquote(value: str) -> str:
    return value.strip()[1:-1].encode("utf-8").decode("unicode_escape")


def _messages(language: str) -> dict[str, str]:
    text = (LOCALE_DIR / language / "LC_MESSAGES" / "bot.po").read_text(encoding="utf-8")
    messages = {}
    key = None
    value = None
    section = None
    for line in text.splitlines() + [""]:
        if line.startswith("msgid "):
            if key:
                messages[key] = value or ""
            key = _po_unquote(line.removeprefix("msgid "))
            value = ""
            section = "msgid"
        elif line.startswith("msgstr "):
            value = _po_unquote(line.removeprefix("msgstr "))
            section = "msgstr"
        elif line.startswith('"') and section == "msgid":
            key = (key or "") + _po_unquote(line)
        elif line.startswith('"') and section == "msgstr":
            value = (value or "") + _po_unquote(line)
        elif not line and key:
            messages[key] = value or ""
            key = None
            value = None
            section = None
    return {key: value for key, value in messages.items() if key}


def _fields(value: str) -> set[str]:
    return {
        field_name
        for _, field_name, _, _ in string.Formatter().parse(value)
        if field_name
    }


class I18nTests(unittest.TestCase):
    def test_catalogs_have_the_same_keys_and_format_fields(self):
        catalogs = {language: _messages(language) for language in SUPPORTED_LANGUAGES}
        keys = {language: set(messages) for language, messages in catalogs.items()}
        self.assertEqual(keys["en"], keys["ru"])

        for key in keys["en"]:
            with self.subTest(key=key):
                self.assertEqual(_fields(catalogs["en"][key]), _fields(catalogs["ru"][key]))

    def test_runtime_uses_compiled_catalogs(self):
        self.assertEqual(t("button.save", "ru"), "✓ Сохранить")
        self.assertEqual(t("button.save", "en"), "✓ Save")
        self.assertEqual(t("language.changed", "ru", language_name="Русский"), "Язык переключен на Русский.")

    def test_language_codes_normalize_to_supported_base_language(self):
        self.assertEqual(normalize_language("ru-RU"), "ru")
        self.assertEqual(normalize_language("en-US"), "en")
        self.assertEqual(normalize_language("fr"), "en")
