import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("NOTION_TOKEN", "test-notion-token")
os.environ.setdefault("NOTION_DATABASE_ID", "test-notion-db")
os.environ.setdefault("ALLOWED_USER_ID", "1")

from services import formatter, summary, whisper


class FormatterTests(unittest.IsolatedAsyncioTestCase):
    async def test_format_entry_uses_configured_model_and_json_response(self):
        fake_client = FakeChatClient('{"title":"Title","text":"Body","tags":["work"]}')

        with patch.object(formatter, "client", fake_client):
            result = await formatter.format_entry("raw")

        self.assertEqual(result, ("Title", "Body", ["work"]))
        kwargs = fake_client.chat.completions.calls[0]
        self.assertEqual(kwargs["model"], formatter.settings.openai_formatter_model)
        self.assertEqual(kwargs["max_completion_tokens"], 1024)
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})
        system_prompt = kwargs["messages"][0]["content"]
        self.assertIn("исходный текст с минимальной правкой", system_prompt)
        self.assertIn("не переписывай стиль", system_prompt)
        self.assertIn("смысловые абзацы", system_prompt)

    async def test_format_entry_uses_metadata_only_for_long_transcription(self):
        fake_client = FakeChatClient('{"title":"Long Title","tags":["work"]}')
        raw = "слово " * (formatter.LONG_TRANSCRIPTION_CHAR_LIMIT // 5 + 1)

        with patch.object(formatter, "client", fake_client):
            result = await formatter.format_entry(raw)

        self.assertEqual(result, ("Long Title", raw, ["work"]))
        kwargs = fake_client.chat.completions.calls[0]
        self.assertEqual(kwargs["max_completion_tokens"], formatter.METADATA_MAX_COMPLETION_TOKENS)
        self.assertIn("Не возвращай полный текст заметки", kwargs["messages"][0]["content"])

    async def test_format_entry_falls_back_when_json_is_truncated(self):
        fake_client = FakeChatClient('{"title":"Title","text":"unfinished')

        with patch.object(formatter, "client", fake_client):
            result = await formatter.format_entry("raw transcription text")

        self.assertEqual(result, ("raw transcription text", "raw transcription text", []))

    async def test_format_entry_injects_rules_into_prompt(self):
        fake_client = FakeChatClient('{"title":"Work Meeting","text":"Met with team","tags":["work"]}')

        with patch.object(formatter, "client", fake_client):
            result = await formatter.format_entry(
                "Met with team",
                rules=["always add tag work", "short title"],
            )

        self.assertEqual(result, ("Work Meeting", "Met with team", ["work"]))
        content = fake_client.chat.completions.calls[0]["messages"][0]["content"]
        self.assertIn("Правила автора:", content)
        self.assertIn("always add tag work", content)
        self.assertIn("short title", content)

    async def test_edit_entry_draft_updates_title_text_and_tags(self):
        fake_client = FakeChatClient('{"title":"New Title","text":"Updated text","tags":["work","important"]}')

        with patch.object(formatter, "client", fake_client):
            result = await formatter.edit_entry_draft(
                instruction="change title and add important tag",
                current_title="Old Title",
                current_text="Old text",
                current_tags=["work"],
                raw_text="Raw speech",
                rules=["keep formatting clean"],
            )

        self.assertEqual(result, ("New Title", "Updated text", ["work", "important"]))
        call = fake_client.chat.completions.calls[0]
        self.assertIn("Правила автора:", call["messages"][0]["content"])
        self.assertIn("keep formatting clean", call["messages"][0]["content"])
        self.assertIn("Old Title", call["messages"][1]["content"])
        self.assertIn("change title and add important tag", call["messages"][1]["content"])

    async def test_edit_entry_draft_preserves_current_values_on_partial_or_invalid_json(self):
        fake_client = FakeChatClient('{"title":"Only New Title"}')

        with patch.object(formatter, "client", fake_client):
            result = await formatter.edit_entry_draft(
                instruction="change title only",
                current_title="Old Title",
                current_text="Old text",
                current_tags=["work"],
            )

        self.assertEqual(result, ("Only New Title", "Old text", ["work"]))

        broken_client = FakeChatClient('invalid json{')
        with patch.object(formatter, "client", broken_client):
            fallback_result = await formatter.edit_entry_draft(
                instruction="break json",
                current_title="Old Title",
                current_text="Old text",
                current_tags=["work"],
            )

        self.assertEqual(fallback_result, ("Old Title", "Old text", ["work"]))


class WhisperTests(unittest.IsolatedAsyncioTestCase):
    async def test_transcribe_uses_configured_model_and_russian_language(self):
        fake_client = FakeAudioClient("recognized text")
        with tempfile.NamedTemporaryFile() as audio_file:
            audio_file.write(b"audio")
            audio_file.flush()

            with patch.object(whisper, "client", fake_client):
                result = await whisper.transcribe(audio_file.name)

        self.assertEqual(result, "recognized text")
        kwargs = fake_client.audio.transcriptions.calls[0]
        self.assertEqual(kwargs["model"], whisper.settings.openai_transcription_model)
        self.assertEqual(kwargs["language"], "ru")
        self.assertFalse(fake_client.audio.transcriptions.file_closed_during_call)


class SummaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_daily_summary_uses_all_today_pages(self):
        fake_client = FakeChatClient("daily summary")
        pages = [
            {
                "id": "page-1",
                "properties": {
                    "Name": {
                        "type": "title",
                        "title": [{"plain_text": "First"}],
                    }
                },
            },
            {
                "id": "page-2",
                "properties": {
                    "Name": {
                        "type": "title",
                        "title": [{"plain_text": "Second"}],
                    }
                },
            },
        ]

        async def fake_get_today_pages():
            return pages

        async def fake_fetch_page_text(page_id):
            return {
                "page-1": "First text",
                "page-2": "Second text",
            }[page_id]

        with (
            patch.object(summary, "openai_client", fake_client),
            patch.object(summary, "get_today_pages", fake_get_today_pages),
            patch.object(summary, "_fetch_page_text", fake_fetch_page_text),
        ):
            result = await summary.generate_daily_summary()

        self.assertEqual(
            result,
            "*Цифры дня*\n"
            "Записи: 2\n"
            "Аудио: 0 мин · 0 аудио\n\n"
            "daily summary",
        )
        kwargs = fake_client.chat.completions.calls[0]
        self.assertEqual(
            kwargs["messages"][1]["content"],
            "### First\nFirst text\n\n### Second\nSecond text",
        )

    async def test_generate_weekly_report_uses_page_titles_and_configured_model(self):
        fake_client = FakeChatClient("weekly report")
        pages = [
            {
                "id": "page-1",
                "properties": {
                    "Name": {
                        "type": "title",
                        "title": [{"plain_text": "4 June | Title"}],
                    }
                },
            }
        ]

        async def fake_get_week_pages():
            return pages

        async def fake_fetch_page_text(page_id):
            self.assertEqual(page_id, "page-1")
            return "Entry text"

        with (
            patch.object(summary, "openai_client", fake_client),
            patch.object(summary, "get_week_pages", fake_get_week_pages),
            patch.object(summary, "_fetch_page_text", fake_fetch_page_text),
        ):
            result = await summary.generate_weekly_report()

        self.assertEqual(
            result,
            "*Цифры недели*\n"
            "Записи: 1\n"
            "Аудио: 0 мин · 0 аудио\n\n"
            "weekly report",
        )
        kwargs = fake_client.chat.completions.calls[0]
        self.assertEqual(kwargs["model"], summary.settings.openai_summary_model)
        self.assertEqual(kwargs["max_completion_tokens"], 1024)
        self.assertEqual(kwargs["messages"][1]["content"], "### 4 June | Title\nEntry text")


class FakeChatClient:
    def __init__(self, content):
        self.chat = SimpleNamespace(completions=FakeChatCompletions(content))


class FakeChatCompletions:
    def __init__(self, content):
        self.content = content
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.content),
                )
            ]
        )


class FakeAudioClient:
    def __init__(self, text):
        self.audio = SimpleNamespace(transcriptions=FakeTranscriptions(text))


class FakeTranscriptions:
    def __init__(self, text):
        self.text = text
        self.calls = []
        self.file_closed_during_call = None

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        self.file_closed_during_call = kwargs["file"].closed
        return SimpleNamespace(text=self.text)
