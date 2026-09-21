import os
import unittest
from unittest.mock import patch

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("NOTION_TOKEN", "test-notion-token")
os.environ.setdefault("NOTION_DATABASE_ID", "test-notion-db")
os.environ.setdefault("ALLOWED_USER_ID", "1")

import config


class ConfigValidationTests(unittest.TestCase):
    def test_required_env_rejects_missing_or_blank_values(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Missing required environment variable: TELEGRAM_TOKEN"):
                config._required_env("TELEGRAM_TOKEN")

        with patch.dict(os.environ, {"TELEGRAM_TOKEN": "   "}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Missing required environment variable: TELEGRAM_TOKEN"):
                config._required_env("TELEGRAM_TOKEN")

    def test_required_int_rejects_non_integer_allowed_user_id(self):
        with patch.dict(os.environ, {"ALLOWED_USER_ID": "not-a-number"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "ALLOWED_USER_ID must be an integer"):
                config._required_int("ALLOWED_USER_ID")

    def test_timezone_rejects_invalid_iana_timezone(self):
        with patch.dict(os.environ, {"TIMEZONE": "Mars/Olympus"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "TIMEZONE must be a valid IANA timezone: Mars/Olympus"):
                config._timezone()

    def test_optional_env_empty_value_falls_back_to_default(self):
        # Mirrors how _Settings loads optional model overrides like OPENAI_ROAST_MODEL:
        # an empty or unset value must fall back to the built-in default.
        with patch.dict(os.environ, {"OPENAI_ROAST_MODEL": ""}, clear=True):
            self.assertEqual(config._optional_env("OPENAI_ROAST_MODEL", "gpt-5.4"), "gpt-5.4")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(config._optional_env("OPENAI_ROAST_MODEL", "gpt-5.4"), "gpt-5.4")

    def test_diary_day_start_hour_defaults_to_midnight(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(config._diary_day_start_hour(), 0)

    def test_diary_day_start_hour_accepts_custom_hour(self):
        with patch.dict(os.environ, {"DIARY_DAY_START_HOUR": "4"}, clear=True):
            self.assertEqual(config._diary_day_start_hour(), 4)

    def test_diary_day_start_hour_rejects_invalid_values(self):
        for value in ("not-a-number", "-1", "24"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"DIARY_DAY_START_HOUR": value}, clear=True):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "DIARY_DAY_START_HOUR must be an integer from 0 to 23",
                    ):
                        config._diary_day_start_hour()

    def test_optional_bool_defaults_when_unset_or_blank(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(config._optional_bool("SILENT_NOTIFICATIONS", True))
            self.assertFalse(config._optional_bool("SILENT_NOTIFICATIONS", False))
        with patch.dict(os.environ, {"SILENT_NOTIFICATIONS": "   "}, clear=True):
            self.assertTrue(config._optional_bool("SILENT_NOTIFICATIONS", True))

    def test_optional_bool_parses_truthy_and_falsy_values(self):
        for raw in ("1", "true", "TRUE", "Yes", "on"):
            with patch.dict(os.environ, {"SILENT_NOTIFICATIONS": raw}, clear=True):
                self.assertTrue(config._optional_bool("SILENT_NOTIFICATIONS", False))
        for raw in ("0", "false", "no", "off", "anything"):
            with patch.dict(os.environ, {"SILENT_NOTIFICATIONS": raw}, clear=True):
                self.assertFalse(config._optional_bool("SILENT_NOTIFICATIONS", True))

    def test_ai_provider_accepts_valid_providers(self):
        for provider in ("openai", "anthropic", "openrouter", "OPENROUTER", " Anthropic "):
            with self.subTest(provider=provider):
                with patch.dict(os.environ, {"AI_PROVIDER": provider}, clear=True):
                    self.assertEqual(config._ai_provider(), provider.strip().lower())

    def test_ai_provider_defaults_to_openai(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(config._ai_provider(), "openai")

    def test_ai_provider_rejects_invalid_provider(self):
        with patch.dict(os.environ, {"AI_PROVIDER": "cohere"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "AI_PROVIDER must be 'openai', 'anthropic', or 'openrouter'"):
                config._ai_provider()

    def test_openrouter_api_key_required_only_when_openrouter_provider(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(config._openrouter_api_key("openai"), "")
            self.assertEqual(config._openrouter_api_key("anthropic"), "")
            with self.assertRaisesRegex(RuntimeError, "OPENROUTER_API_KEY is required when AI_PROVIDER=openrouter"):
                config._openrouter_api_key("openrouter")

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=True):
            self.assertEqual(config._openrouter_api_key("openrouter"), "test-key")
