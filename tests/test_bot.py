import asyncio
import os
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.ext import CommandHandler

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("NOTION_TOKEN", "test-notion-token")
os.environ.setdefault("NOTION_DATABASE_ID", "test-notion-db")
os.environ.setdefault("ALLOWED_USER_ID", "1")

import bot


class ApplicationSetupTests(unittest.TestCase):
    def _build_defaults(self, silent):
        builder = FakeApplicationBuilder(FakePollingApplication())
        with patch.object(bot, "ApplicationBuilder", return_value=builder), \
                patch.object(bot.settings, "silent_notifications", silent):
            bot.main()
        return builder.defaults_value

    def test_main_wires_silent_notifications_into_defaults(self):
        defaults = self._build_defaults(True)
        self.assertTrue(defaults.disable_notification)

    def test_main_respects_disabled_silent_notifications(self):
        defaults = self._build_defaults(False)
        self.assertFalse(defaults.disable_notification)


class PreviewRenderingTests(unittest.TestCase):
    def test_preview_text_combines_title_body_and_tags_with_html_escaping(self):
        entry_date = bot._default_entry_date()
        preview = bot._preview_text("Title <x>", "Body & notes", ["Daily", "work & life"], entry_date)

        self.assertEqual(
            preview,
            "<b>Title &lt;x&gt;</b>\n\n"
            "Body &amp; notes\n\n"
            f"Date: <code>{bot._entry_date_label(entry_date)}</code>\n\n"
            "<code>Daily</code> <code>work &amp; life</code>",
        )

    def test_preview_text_truncates_body_to_telegram_message_limit(self):
        entry_date = bot._default_entry_date()
        body = "x" * (bot.TELEGRAM_MESSAGE_LIMIT + 500)

        preview = bot._preview_text("Long voice transcript", body, [], entry_date)

        self.assertLessEqual(len(preview), bot.TELEGRAM_MESSAGE_LIMIT)
        self.assertIn("Preview truncated", preview)
        self.assertIn("Page 1/", preview)
        self.assertIn("Full text is kept", preview)
        self.assertNotEqual(preview, body)

    def test_preview_text_can_render_later_truncated_pages(self):
        entry_date = bot._default_entry_date()
        body = "\n".join(f"line {i:03d} " + "x" * 80 for i in range(120))

        first_page = bot._render_preview("Long voice transcript", body, [], entry_date, page=0)
        second_page = bot._render_preview("Long voice transcript", body, [], entry_date, page=1)

        self.assertTrue(first_page.truncated)
        self.assertGreater(first_page.page_count, 1)
        self.assertEqual(second_page.page, 1)
        self.assertEqual(second_page.page_count, first_page.page_count)
        self.assertLessEqual(len(second_page.text), bot.TELEGRAM_MESSAGE_LIMIT)
        self.assertIn(f"Page 2/{second_page.page_count}", second_page.text)
        self.assertNotEqual(first_page.text, second_page.text)

    def test_preview_keyboard_scopes_every_callback_to_entry_id(self):
        keyboard = bot._preview_keyboard(
            "entry-1",
            highlighted=True,
            entry_date=bot._default_entry_date(),
            show_format=True,
        )
        callback_data = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]

        self.assertEqual(
            callback_data,
            [
                "edit_title:entry-1",
                "edit_text:entry-1",
                "edit_tags:entry-1",
                "format:entry-1",
                "pick_date:entry-1",
                "toggle_highlight:entry-1",
                "roast:entry-1",
                "save:entry-1",
                "cancel:entry-1",
            ],
        )

    def test_preview_keyboard_adds_top_pagination_row_only_when_truncated(self):
        keyboard = bot._preview_keyboard(
            "entry-1",
            entry_date=bot._default_entry_date(),
            show_pagination=True,
            preview_page=1,
            page_count=3,
        )
        callback_data = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]

        self.assertEqual(
            callback_data[:2],
            ["preview_page:entry-1:0", "preview_page:entry-1:2"],
        )

    def test_date_picker_keyboard_lists_last_seven_days_with_exit_paths(self):
        keyboard = bot._date_picker_keyboard("entry-1", selected_date=bot._default_entry_date())
        callback_data = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]

        self.assertEqual(
            [data for data in callback_data if data.startswith("set_date:entry-1:")],
            [f"set_date:entry-1:{entry_date}" for entry_date in bot._entry_date_options()],
        )
        self.assertEqual(callback_data[-2:], ["back_to_preview:entry-1", "cancel:entry-1"])

    def test_entry_date_options_use_configured_diary_day(self):
        with patch.object(bot, "diary_today", return_value=date(2026, 6, 21)):
            self.assertEqual(bot._default_entry_date(), "2026-06-21")
            self.assertEqual(
                bot._entry_date_options(),
                [
                    "2026-06-21",
                    "2026-06-20",
                    "2026-06-19",
                    "2026-06-18",
                    "2026-06-17",
                    "2026-06-16",
                    "2026-06-15",
                ],
            )

    def test_duplicate_voice_keyboard_scopes_actions_to_message_key(self):
        keyboard = bot._duplicate_voice_keyboard("123:10")
        callback_data = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]

        self.assertEqual(callback_data, ["add_duplicate:123:10", "cancel_duplicate:123:10"])

    def test_retry_processing_keyboard_scopes_action_to_message_key(self):
        keyboard = bot._retry_processing_keyboard("123:10")
        callback_data = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]

        self.assertEqual(callback_data, ["retry_process:123:10"])

    def test_callback_payload_parses_action_and_entry_id(self):
        update = SimpleNamespace(callback_query=SimpleNamespace(data="save:entry-1"))

        self.assertEqual(bot._callback_payload(update), ("save", "entry-1"))

    def test_callback_payload_ignores_date_value_when_parsing_entry_id(self):
        update = SimpleNamespace(callback_query=SimpleNamespace(data="set_date:entry-1:2026-06-08"))

        self.assertEqual(bot._callback_payload(update), ("set_date", "entry-1"))
        self.assertEqual(bot._callback_value(update), "2026-06-08")

    def test_callback_payload_rejects_unscoped_data(self):
        update = SimpleNamespace(callback_query=SimpleNamespace(data="save"))

        self.assertEqual(bot._callback_payload(update), (None, None))

    def test_telegram_message_url_prefers_native_message_link(self):
        message = SimpleNamespace(
            chat_id=-100123,
            message_id=10,
            link="https://t.me/c/123/10",
        )

        self.assertEqual(bot._telegram_message_url(message), "https://t.me/c/123/10")

    def test_telegram_message_url_builds_clickable_bot_deeplink_for_private_chat(self):
        message = SimpleNamespace(chat_id=123, message_id=10)

        self.assertEqual(
            bot._telegram_message_url(message, "diary_bot"),
            "https://t.me/diary_bot?start=src_123_10",
        )

    def test_telegram_message_url_falls_back_to_private_chat_protocol_link_without_bot_username(self):
        self.assertEqual(
            bot._telegram_message_url_from_ids(123, 10),
            "tg://openmessage?user_id=123&message_id=10",
        )

    def test_telegram_message_url_builds_private_supergroup_web_link_from_chat_id(self):
        self.assertEqual(
            bot._telegram_message_url_from_ids(-1009876543210, 77),
            "https://t.me/c/9876543210/77",
        )

    def test_entry_metadata_uses_voice_file_facts_for_deduplication(self):
        metadata = bot._entry_metadata({
            "kind": "voice",
            "chat_id": 123,
            "message_id": 10,
            "source_message_url": "tg://openmessage?user_id=123&message_id=10",
            "file_unique_id": "voice-unique",
            "duration": 42,
            "file_size": 1000,
        }, "transcribed text")

        self.assertEqual(metadata, {
            "source": "voice",
            "telegram_chat_id": 123,
            "telegram_message_id": 10,
            "source_message_url": "tg://openmessage?user_id=123&message_id=10",
            "voice_file_unique_id": "voice-unique",
            "audio_duration": 42,
            "audio_file_size": 1000,
        })

    def test_entry_metadata_hashes_manual_text_for_exact_deduplication(self):
        metadata = bot._entry_metadata({
            "kind": "text",
            "chat_id": 123,
            "message_id": 10,
        }, "exact text")

        self.assertEqual(metadata["source"], "text")
        self.assertEqual(metadata["telegram_chat_id"], 123)
        self.assertEqual(metadata["telegram_message_id"], 10)
        self.assertEqual(metadata["source_message_url"], "tg://openmessage?user_id=123&message_id=10")
        self.assertEqual(metadata["source_text_hash"], bot._source_text_hash("exact text"))

    def test_entry_metadata_uses_bot_deeplink_for_private_chat_when_username_is_available(self):
        metadata = bot._entry_metadata({
            "kind": "text",
            "chat_id": 123,
            "message_id": 10,
        }, "exact text", bot_username="@diary_bot")

        self.assertEqual(metadata["source_message_url"], "https://t.me/diary_bot?start=src_123_10")

    def test_entry_metadata_upgrades_stored_protocol_link_when_bot_username_is_available(self):
        metadata = bot._entry_metadata({
            "kind": "text",
            "chat_id": 123,
            "message_id": 10,
            "source_message_url": "tg://openmessage?user_id=123&message_id=10",
        }, "exact text", bot_username="diary_bot")

        self.assertEqual(metadata["source_message_url"], "https://t.me/diary_bot?start=src_123_10")


class ReplyToSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_reply_to_source_uses_reply_parameters_for_stored_message(self):
        fake_bot = FakeSendBot()
        message_ref = bot.StoredMessageRef(fake_bot, chat_id=123, message_id=456)

        message = await bot._reply_to_source(message_ref, "Processing", parse_mode="HTML")

        self.assertEqual(message.message_id, 999)
        self.assertEqual(fake_bot.sent_messages[0]["chat_id"], 123)
        self.assertEqual(fake_bot.sent_messages[0]["text"], "Processing")
        self.assertEqual(fake_bot.sent_messages[0]["parse_mode"], "HTML")
        reply_parameters = fake_bot.sent_messages[0]["reply_parameters"]
        self.assertEqual(reply_parameters.message_id, 456)
        self.assertTrue(reply_parameters.allow_sending_without_reply)

    async def test_start_source_deeplink_sends_reply_to_original_message(self):
        fake_bot = FakeSendBot()
        source_message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(effective_message=source_message)
        fake_context = SimpleNamespace(bot=fake_bot, args=["src_123_456"])

        await bot.handle_start(update, fake_context)

        self.assertEqual(len(fake_bot.sent_messages), 1)
        sent = fake_bot.sent_messages[0]
        self.assertEqual(sent["chat_id"], 123)
        self.assertEqual(sent["text"], "Source message")
        self.assertEqual(sent["reply_parameters"].message_id, 456)
        self.assertFalse(sent["reply_parameters"].allow_sending_without_reply)
        source_message.reply_text.assert_not_awaited()


class CreatePreviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_preview_edits_existing_processing_reply_and_persists_draft(self):
        fake_state_store = FakeStateStore()
        fake_context = SimpleNamespace(
            bot=FakeEditBot(),
            user_data={},
            application=FakeApplication(close_coroutines=True),
        )
        source_message = SimpleNamespace(chat_id=123, message_id=10)
        processing_message = SimpleNamespace(chat_id=123, message_id=20)
        fake_state_store.messages["123:10"] = {
            "kind": "voice",
            "chat_id": 123,
            "message_id": 10,
            "file_unique_id": "voice-unique",
            "duration": 12,
            "file_size": 345,
        }

        fake_formatter = AsyncMock(return_value=("Title", "Body", ["work"]))
        with (
            patch.object(bot, "format_entry", new=fake_formatter),
            patch.object(bot, "_new_entry_id", return_value="entry-1"),
            patch.object(bot, "state_store", fake_state_store),
            patch.object(bot, "_update_profile_points", new=AsyncMock()),
        ):
            await bot._create_preview(
                source_message,
                fake_context,
                "raw transcription",
                message_key="123:10",
                preview_message=processing_message,
            )

        entry_date = bot._default_entry_date()
        fake_formatter.assert_awaited_once_with("raw transcription")
        self.assertEqual(len(fake_context.bot.edits), 1)
        edit = fake_context.bot.edits[0]
        self.assertEqual(edit["chat_id"], 123)
        self.assertEqual(edit["message_id"], 20)
        self.assertEqual(edit["text"], bot._preview_text("Title", "raw transcription", ["work"], entry_date))
        self.assertEqual(edit["parse_mode"], "HTML")
        self.assertEqual(fake_state_store.marked_drafted, [("123:10", "entry-1")])
        self.assertEqual(fake_state_store.saved_drafts[0]["preview_msg_id"], 20)
        self.assertEqual(fake_state_store.saved_drafts[0]["entry_date"], entry_date)
        self.assertEqual(fake_state_store.saved_drafts[0]["raw_text"], "raw transcription")
        self.assertEqual(fake_state_store.saved_drafts[0]["formatted_text"], "Body")
        self.assertFalse(fake_state_store.saved_drafts[0]["formatted"])
        self.assertEqual(
            fake_state_store.saved_drafts[0]["metadata"]["source_message_url"],
            "https://t.me/diary_bot?start=src_123_10",
        )
        self.assertEqual(fake_state_store.saved_drafts[0]["metadata"]["voice_file_unique_id"], "voice-unique")
        self.assertFalse(fake_state_store.saved_drafts[0]["allow_duplicate"])
        self.assertIn("entry-1", fake_context.user_data[bot.DRAFTS_KEY])

    async def test_create_preview_sends_new_reply_when_no_processing_message_exists(self):
        fake_state_store = FakeStateStore()
        fake_context = SimpleNamespace(
            bot=FakeSendBot(),
            user_data={},
            application=FakeApplication(close_coroutines=True),
        )
        source_message = SimpleNamespace(
            chat_id=123,
            message_id=10,
            get_bot=lambda: fake_context.bot,
        )

        fake_formatter = AsyncMock(return_value=("Title", "Body", []))
        with (
            patch.object(bot, "format_entry", new=fake_formatter),
            patch.object(bot, "_new_entry_id", return_value="entry-2"),
            patch.object(bot, "state_store", fake_state_store),
            patch.object(bot, "_update_profile_points", new=AsyncMock()),
        ):
            await bot._create_preview(source_message, fake_context, "plain text")

        fake_formatter.assert_awaited_once_with("plain text")
        self.assertEqual(len(fake_context.bot.sent_messages), 1)
        reply_parameters = fake_context.bot.sent_messages[0]["reply_parameters"]
        self.assertEqual(reply_parameters.message_id, 10)
        self.assertTrue(reply_parameters.allow_sending_without_reply)
        self.assertEqual(fake_state_store.saved_drafts[0]["preview_msg_id"], 999)

    async def test_create_preview_keeps_full_text_when_telegram_preview_is_truncated(self):
        fake_state_store = FakeStateStore()
        fake_context = SimpleNamespace(
            bot=FakeEditBot(),
            user_data={},
            application=FakeApplication(close_coroutines=True),
        )
        source_message = SimpleNamespace(chat_id=123, message_id=10)
        processing_message = SimpleNamespace(chat_id=123, message_id=20)
        long_text = "x" * (bot.TELEGRAM_MESSAGE_LIMIT + 500)
        fake_formatter = AsyncMock(return_value=("Title", "Formatted", []))

        with (
            patch.object(bot, "format_entry", new=fake_formatter),
            patch.object(bot, "_new_entry_id", return_value="entry-long"),
            patch.object(bot, "state_store", fake_state_store),
            patch.object(bot, "_update_profile_points", new=AsyncMock()),
        ):
            await bot._create_preview(
                source_message,
                fake_context,
                long_text,
                message_key="123:10",
                preview_message=processing_message,
            )

        edit_text = fake_context.bot.edits[0]["text"]
        keyboard = fake_context.bot.edits[0]["reply_markup"]
        callback_data = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]
        self.assertLessEqual(len(edit_text), bot.TELEGRAM_MESSAGE_LIMIT)
        self.assertIn("Preview truncated", edit_text)
        self.assertIn("Page 1/", edit_text)
        self.assertEqual(callback_data[:2], ["preview_page:entry-long:0", "preview_page:entry-long:1"])
        self.assertEqual(fake_state_store.saved_drafts[0]["text"], long_text)
        self.assertEqual(fake_state_store.saved_drafts[0]["raw_text"], long_text)
        self.assertEqual(fake_state_store.saved_drafts[0]["formatted_text"], "Formatted")
        self.assertEqual(fake_state_store.saved_drafts[0]["preview_page"], 0)

    async def test_create_preview_shows_format_when_formatted_text_matches_raw_text(self):
        fake_state_store = FakeStateStore()
        fake_context = SimpleNamespace(
            bot=FakeEditBot(),
            user_data={},
            application=FakeApplication(close_coroutines=True),
        )
        source_message = SimpleNamespace(chat_id=123, message_id=10)
        processing_message = SimpleNamespace(chat_id=123, message_id=20)
        fake_formatter = AsyncMock(return_value=("Title", "raw transcription", []))

        with (
            patch.object(bot, "format_entry", new=fake_formatter),
            patch.object(bot, "_new_entry_id", return_value="entry-raw"),
            patch.object(bot, "state_store", fake_state_store),
            patch.object(bot, "_update_profile_points", new=AsyncMock()),
        ):
            await bot._create_preview(
                source_message,
                fake_context,
                "raw transcription",
                message_key="123:10",
                preview_message=processing_message,
            )

        keyboard = fake_context.bot.edits[0]["reply_markup"]
        callback_data = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]
        self.assertIn("format:entry-raw", callback_data)

    async def test_create_preview_schedules_profile_refresh(self):
        fake_state_store = FakeStateStore()
        fake_context = SimpleNamespace(
            bot=FakeEditBot(),
            user_data={},
            application=FakeApplication(close_coroutines=True),
        )
        source_message = SimpleNamespace(chat_id=123, message_id=10)
        processing_message = SimpleNamespace(chat_id=123, message_id=20)
        fake_formatter = AsyncMock(return_value=("Title", "Body", []))

        with (
            patch.object(bot, "format_entry", new=fake_formatter),
            patch.object(bot, "_new_entry_id", return_value="entry-refresh"),
            patch.object(bot, "state_store", fake_state_store),
            patch.object(bot, "_update_profile_points", new=AsyncMock()) as fake_update,
        ):
            await bot._create_preview(
                source_message,
                fake_context,
                "plain text",
                message_key="123:10",
                preview_message=processing_message,
            )

        self.assertEqual(len(fake_context.application.created_tasks), 1)
        # The preview message carries the note about whatever the entry taught.
        fake_update.assert_called_once_with("plain text", processing_message)


class DuplicateVoiceFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_handle_voice_warns_and_waits_when_voice_was_already_saved(self):
        fake_state_store = FakeStateStore()
        fake_state_store.duplicate_voice = {"key": "123:10", "status": "saved"}
        fake_context = SimpleNamespace(
            bot=FakeSendBot(),
            application=FakeApplication(),
            user_data={},
        )
        voice = SimpleNamespace(
            file_id="file-2",
            file_unique_id="voice-unique",
            duration=42,
            file_size=1000,
        )
        message = SimpleNamespace(
            chat_id=123,
            message_id=11,
            voice=voice,
            date=None,
            get_bot=lambda: fake_context.bot,
        )
        update = SimpleNamespace(effective_message=message)

        with patch.object(bot, "state_store", fake_state_store):
            await bot.handle_voice(update, fake_context)

        self.assertEqual(fake_state_store.marked_duplicate_pending, [("123:11", "123:10")])
        self.assertEqual(fake_context.application.created_tasks, [])
        self.assertIn("already been added", fake_context.bot.sent_messages[0]["text"])
        keyboard = fake_context.bot.sent_messages[0]["reply_markup"]
        self.assertEqual(keyboard.inline_keyboard[0][0].callback_data, "add_duplicate:123:11")

    async def test_duplicate_callback_confirms_and_starts_processing(self):
        fake_state_store = FakeStateStore()
        fake_state_store.messages["123:11"] = {
            "key": "123:11",
            "kind": "voice",
            "chat_id": 123,
            "message_id": 11,
        }
        fake_context = SimpleNamespace(
            bot=FakeSendBot(),
            application=FakeApplication(close_coroutines=True),
            user_data={},
        )
        fake_query = FakeQuery(data="add_duplicate:123:11")
        update = SimpleNamespace(callback_query=fake_query)

        with (
            patch.object(bot, "state_store", fake_state_store),
            patch.object(bot, "_process_message_record", new=AsyncMock()),
        ):
            await bot.duplicate_callback(update, fake_context)

        self.assertEqual(fake_state_store.marked_duplicate_confirmed, ["123:11"])
        self.assertEqual(fake_query.edits[0]["text"], "Adding this voice message anyway...")
        self.assertEqual(len(fake_context.application.created_tasks), 1)


class RetryProcessingFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_text_processing_shows_retry_button(self):
        fake_state_store = FakeStateStore()
        fake_state_store.messages["123:10"] = {
            "key": "123:10",
            "kind": "text",
            "chat_id": 123,
            "message_id": 10,
            "text": "raw text",
        }
        fake_context = SimpleNamespace(bot=FakeEditBot(), user_data={})
        status_message = SimpleNamespace(chat_id=123, message_id=20)

        with (
            patch.object(bot, "format_entry", new=AsyncMock(side_effect=RuntimeError("formatter failed"))),
            patch.object(bot, "state_store", fake_state_store),
            patch.object(bot.logger, "exception"),
        ):
            await bot._process_text_record(
                fake_state_store.messages["123:10"],
                SimpleNamespace(chat_id=123, message_id=10),
                fake_context,
                status_message=status_message,
            )

        self.assertEqual(fake_state_store.marked_failed, [("123:10", "formatter failed")])
        self.assertEqual(fake_context.bot.edits[0]["text"], "Preparing preview...")
        self.assertIn("Error: formatter failed", fake_context.bot.edits[1]["text"])
        keyboard = fake_context.bot.edits[1]["reply_markup"]
        self.assertEqual(keyboard.inline_keyboard[0][0].callback_data, "retry_process:123:10")

    async def test_retry_processing_callback_restarts_message_processing(self):
        fake_state_store = FakeStateStore()
        fake_state_store.messages["123:10"] = {
            "key": "123:10",
            "kind": "text",
            "status": "failed",
            "chat_id": 123,
            "message_id": 10,
            "text": "raw text",
        }
        fake_context = SimpleNamespace(
            bot=FakeSendBot(),
            application=FakeApplication(close_coroutines=True),
            user_data={},
        )
        fake_query = FakeQuery(data="retry_process:123:10")
        update = SimpleNamespace(callback_query=fake_query)
        fake_processor = AsyncMock()

        with (
            patch.object(bot, "state_store", fake_state_store),
            patch.object(bot, "_process_message_record", new=fake_processor),
        ):
            await bot.retry_processing_callback(update, fake_context)

        self.assertEqual(fake_query.edits[0]["text"], "Retrying...")
        self.assertEqual(len(fake_context.application.created_tasks), 1)
        fake_processor.assert_called_once()
        args, kwargs = fake_processor.call_args
        self.assertEqual(args[0], "123:10")
        self.assertEqual(args[1].chat_id, 123)
        self.assertEqual(args[1].message_id, 10)
        self.assertIs(args[2], fake_context)
        self.assertIs(kwargs["status_message"], fake_query.message)


class FormatDraftFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_format_draft_applies_stored_formatted_text_only(self):
        fake_state_store = FakeStateStore()
        fake_context = SimpleNamespace(bot=FakeEditBot(), user_data={})
        fake_query = FakeQuery()
        draft = {
            "id": "entry-1",
            "title": "Title",
            "text": "raw transcription",
            "raw_text": "raw transcription",
            "formatted_text": "formatted body",
            "formatted": False,
            "tags": ["work"],
            "chat_id": 123,
            "preview_msg_id": 20,
            "entry_date": bot._default_entry_date(),
        }
        fake_formatter = AsyncMock(return_value=("Other", "Other body", []))

        with (
            patch.object(bot, "format_entry", new=fake_formatter),
            patch.object(bot, "state_store", fake_state_store),
        ):
            await bot._format_draft(fake_query, fake_context, draft)

        fake_formatter.assert_not_awaited()
        self.assertEqual(draft["title"], "Title")
        self.assertEqual(draft["text"], "formatted body")
        self.assertEqual(draft["tags"], ["work"])
        self.assertTrue(draft["formatted"])
        self.assertEqual(fake_state_store.saved_drafts[-1]["raw_text"], "raw transcription")
        self.assertEqual(
            fake_context.bot.edits[0]["text"],
            bot._preview_text("Title", "formatted body", ["work"], draft["entry_date"]),
        )

    async def test_formatted_draft_keyboard_offers_original_instead_of_format(self):
        draft = {
            "id": "entry-1",
            "title": "Title",
            "text": "formatted body",
            "raw_text": "raw transcription",
            "formatted_text": "formatted body",
            "formatted": True,
            "tags": ["work"],
            "entry_date": bot._default_entry_date(),
        }

        keyboard = bot._preview_keyboard_for_draft(draft)
        callback_data = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]

        self.assertIn("unformat:entry-1", callback_data)
        self.assertNotIn("format:entry-1", callback_data)

    async def test_unformatted_draft_keyboard_hides_format_without_formatted_text(self):
        draft = {
            "id": "entry-1",
            "title": "Title",
            "text": "raw transcription",
            "raw_text": "raw transcription",
            "formatted_text": "",
            "formatted": False,
            "tags": ["work"],
            "entry_date": bot._default_entry_date(),
        }

        keyboard = bot._preview_keyboard_for_draft(draft)
        callback_data = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]

        self.assertNotIn("format:entry-1", callback_data)
        self.assertNotIn("unformat:entry-1", callback_data)

    async def test_format_then_unformat_round_trip_toggles_buttons(self):
        fake_state_store = FakeStateStore()
        fake_context = SimpleNamespace(bot=FakeEditBot(), user_data={})
        fake_query = FakeQuery()
        draft = {
            "id": "entry-1",
            "title": "Title",
            "text": "raw transcription",
            "raw_text": "raw transcription",
            "formatted_text": "formatted body",
            "formatted": False,
            "tags": ["work"],
            "chat_id": 123,
            "preview_msg_id": 20,
            "entry_date": bot._default_entry_date(),
        }

        def callbacks():
            keyboard = bot._preview_keyboard_for_draft(draft)
            return [
                button.callback_data
                for row in keyboard.inline_keyboard
                for button in row
            ]

        with patch.object(bot, "state_store", fake_state_store):
            self.assertIn("format:entry-1", callbacks())
            await bot._format_draft(fake_query, fake_context, draft)
            self.assertEqual(draft["text"], "formatted body")
            self.assertIn("unformat:entry-1", callbacks())

            await bot._unformat_draft(fake_query, fake_context, draft)
            self.assertEqual(draft["text"], "raw transcription")
            self.assertIn("format:entry-1", callbacks())

            await bot._format_draft(fake_query, fake_context, draft)
            self.assertEqual(draft["text"], "formatted body")
            self.assertTrue(draft["formatted"])

    async def test_unformat_draft_warns_when_already_original(self):
        fake_state_store = FakeStateStore()
        fake_context = SimpleNamespace(bot=FakeEditBot(), user_data={})
        fake_query = FakeQuery()
        draft = {
            "id": "entry-1",
            "title": "Title",
            "text": "raw transcription",
            "raw_text": "raw transcription",
            "formatted_text": "formatted body",
            "formatted": False,
            "tags": ["work"],
            "chat_id": 123,
            "preview_msg_id": 20,
            "entry_date": bot._default_entry_date(),
        }

        with patch.object(bot, "state_store", fake_state_store):
            await bot._unformat_draft(fake_query, fake_context, draft)

        fake_query.message.reply_text.assert_awaited_once()
        self.assertEqual(fake_context.bot.edits, [])
        self.assertEqual(fake_state_store.saved_drafts, [])

    async def test_unformat_draft_restores_raw_text(self):
        fake_state_store = FakeStateStore()
        fake_context = SimpleNamespace(bot=FakeEditBot(), user_data={})
        fake_query = FakeQuery()
        draft = {
            "id": "entry-1",
            "title": "Title",
            "text": "formatted body",
            "raw_text": "raw transcription",
            "formatted_text": "formatted body",
            "formatted": True,
            "tags": ["work"],
            "chat_id": 123,
            "preview_msg_id": 20,
            "entry_date": bot._default_entry_date(),
        }

        with patch.object(bot, "state_store", fake_state_store):
            await bot._unformat_draft(fake_query, fake_context, draft)

        self.assertEqual(draft["text"], "raw transcription")
        self.assertFalse(draft["formatted"])
        self.assertEqual(draft["preview_page"], 0)
        self.assertEqual(fake_state_store.saved_drafts[-1]["text"], "raw transcription")
        self.assertEqual(
            fake_context.bot.edits[0]["text"],
            bot._preview_text("Title", "raw transcription", ["work"], draft["entry_date"]),
        )


class DatePickerFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_set_entry_date_persists_and_returns_to_preview(self):
        fake_state_store = FakeStateStore()
        fake_context = SimpleNamespace(bot=FakeEditBot(), user_data={})
        selected_date = bot._entry_date_options()[1]
        draft = {
            "id": "entry-1",
            "title": "Title",
            "text": "Text",
            "tags": ["work"],
            "chat_id": 123,
            "preview_msg_id": 20,
            "entry_date": bot._default_entry_date(),
        }
        update = SimpleNamespace(
            callback_query=SimpleNamespace(data=f"set_date:entry-1:{selected_date}")
        )

        with patch.object(bot, "state_store", fake_state_store):
            await bot._set_entry_date(update, fake_context, draft)

        self.assertEqual(draft["entry_date"], selected_date)
        self.assertEqual(fake_state_store.saved_drafts[-1]["entry_date"], selected_date)
        self.assertEqual(fake_context.bot.edits[0]["text"], bot._preview_text("Title", "Text", ["work"], selected_date))


class PreviewPageFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_set_preview_page_persists_and_edits_same_preview_message(self):
        fake_state_store = FakeStateStore()
        fake_context = SimpleNamespace(bot=FakeEditBot(), user_data={})
        entry_date = bot._default_entry_date()
        draft = {
            "id": "entry-1",
            "title": "Title",
            "text": "\n".join(f"line {i:03d} " + "x" * 80 for i in range(120)),
            "tags": ["work"],
            "chat_id": 123,
            "preview_msg_id": 20,
            "entry_date": entry_date,
            "preview_page": 0,
        }
        update = SimpleNamespace(callback_query=SimpleNamespace(data="preview_page:entry-1:1"))

        with patch.object(bot, "state_store", fake_state_store):
            await bot._set_preview_page(update, fake_context, draft)

        self.assertEqual(draft["preview_page"], 1)
        self.assertEqual(fake_state_store.saved_drafts[-1]["preview_page"], 1)
        self.assertEqual(fake_context.bot.edits[0]["message_id"], 20)
        self.assertIn("Page 2/", fake_context.bot.edits[0]["text"])


class CancelDraftTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_draft_removes_persisted_and_in_memory_draft(self):
        fake_state_store = FakeStateStore()
        fake_query = FakeQuery()
        fake_context = SimpleNamespace(user_data={
            bot.DRAFTS_KEY: {
                "entry-1": {
                    "id": "entry-1",
                    "message_key": "123:10",
                }
            }
        })
        draft = fake_context.user_data[bot.DRAFTS_KEY]["entry-1"]

        with patch.object(bot, "state_store", fake_state_store):
            await bot._cancel_draft(fake_query, fake_context, "entry-1", draft)

        self.assertNotIn("entry-1", fake_context.user_data[bot.DRAFTS_KEY])
        self.assertEqual(fake_state_store.marked_cancelled, ["123:10"])
        self.assertEqual(fake_state_store.removed_drafts, ["entry-1"])
        self.assertEqual(fake_query.edits[0]["text"], "Cancelled.")


class SaveDraftTests(unittest.IsolatedAsyncioTestCase):
    async def test_save_draft_keeps_draft_and_retry_button_when_notion_save_fails(self):
        fake_state_store = FakeStateStore()
        fake_query = FakeQuery()
        fake_context = SimpleNamespace(user_data={bot.DRAFTS_KEY: {}})
        draft = {
            "id": "entry-1",
            "title": "Title",
            "text": "Text",
            "tags": ["work"],
            "entry_date": bot._default_entry_date(),
            "message_key": "123:10",
            "saving": False,
        }
        calls = []

        async def failing_save_entry(title, text, tags, metadata=None, entry_date=None, allow_duplicate=False):
            calls.append((title, text, tags, metadata, entry_date, allow_duplicate))
            raise RuntimeError("notion timeout")

        with (
            patch.object(bot, "save_entry", new=failing_save_entry),
            patch.object(bot, "state_store", fake_state_store),
            patch.object(bot.logger, "exception"),
        ):
            await bot._save_draft(fake_query, fake_context, "entry-1", draft)

        self.assertFalse(draft["saving"])
        self.assertEqual(calls[0][-2], draft["entry_date"])
        self.assertFalse(calls[0][-1])
        self.assertEqual(fake_state_store.saved_drafts[-1]["id"], "entry-1")
        self.assertEqual(fake_query.edits[0]["text"], "Saving to Notion...")
        self.assertIn("Not saved to Notion: notion timeout", fake_query.edits[1]["text"])
        self.assertIn("Press Save to retry", fake_query.edits[1]["text"])
        self.assertIsNotNone(fake_query.edits[1].get("reply_markup"))

    async def test_save_draft_keeps_draft_and_offers_add_anyway_when_duplicate_found(self):
        fake_state_store = FakeStateStore()
        fake_query = FakeQuery()
        fake_context = SimpleNamespace(user_data={bot.DRAFTS_KEY: {}})
        draft = {
            "id": "entry-1",
            "title": "Title",
            "text": "Text",
            "tags": ["work"],
            "entry_date": bot._default_entry_date(),
            "metadata": {"source": "voice"},
            "message_key": "123:10",
            "saving": False,
        }

        async def duplicate_save_entry(title, text, tags, metadata=None, entry_date=None, allow_duplicate=False):
            return SimpleNamespace(created=False)

        with (
            patch.object(bot, "save_entry", new=duplicate_save_entry),
            patch.object(bot, "state_store", fake_state_store),
        ):
            await bot._save_draft(fake_query, fake_context, "entry-1", draft)

        self.assertFalse(draft["saving"])
        self.assertEqual(fake_state_store.saved_drafts[-1]["id"], "entry-1")
        self.assertIn("voice message has already been added", fake_query.edits[1]["text"])
        keyboard = fake_query.edits[1]["reply_markup"]
        self.assertEqual(keyboard.inline_keyboard[0][0].callback_data, "save_anyway:entry-1")

    async def test_save_draft_passes_allow_duplicate_when_confirmed(self):
        fake_state_store = FakeStateStore()
        fake_query = FakeQuery()
        fake_context = SimpleNamespace(user_data={bot.DRAFTS_KEY: {"entry-1": {}}})
        draft = {
            "id": "entry-1",
            "title": "Title",
            "text": "Text",
            "tags": ["work"],
            "entry_date": bot._default_entry_date(),
            "message_key": "123:10",
            "saving": False,
            "allow_duplicate": True,
        }
        calls = []

        async def successful_save_entry(title, text, tags, metadata=None, entry_date=None, allow_duplicate=False):
            calls.append((title, text, tags, metadata, entry_date, allow_duplicate))
            return SimpleNamespace(created=True)

        with (
            patch.object(bot, "save_entry", new=successful_save_entry),
            patch.object(bot, "state_store", fake_state_store),
        ):
            await bot._save_draft(fake_query, fake_context, "entry-1", draft)

        self.assertTrue(calls[0][-1])
        self.assertEqual(fake_state_store.marked_saved, ["123:10"])

    async def test_save_draft_enriches_old_draft_metadata_with_clickable_source_url(self):
        fake_state_store = FakeStateStore()
        fake_state_store.messages["123:10"] = {
            "key": "123:10",
            "kind": "text",
            "chat_id": 123,
            "message_id": 10,
        }
        fake_query = FakeQuery()
        fake_context = SimpleNamespace(bot=FakeSendBot(), user_data={bot.DRAFTS_KEY: {"entry-1": {}}})
        draft = {
            "id": "entry-1",
            "title": "Title",
            "text": "Text",
            "tags": ["work"],
            "entry_date": bot._default_entry_date(),
            "message_key": "123:10",
            "saving": False,
        }
        calls = []

        async def successful_save_entry(title, text, tags, metadata=None, entry_date=None, allow_duplicate=False):
            calls.append((title, text, tags, metadata, entry_date, allow_duplicate))
            return SimpleNamespace(created=True)

        with (
            patch.object(bot, "save_entry", new=successful_save_entry),
            patch.object(bot, "state_store", fake_state_store),
        ):
            await bot._save_draft(fake_query, fake_context, "entry-1", draft)

        self.assertEqual(calls[0][3]["source_message_url"], "https://t.me/diary_bot?start=src_123_10")
        self.assertEqual(calls[0][3]["source_text_hash"], bot._source_text_hash("Text"))


class StatCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_handle_stat_sends_formatted_audio_stats(self):
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(effective_message=message)

        async def fake_build_audio_stats():
            return "stats"

        with (
            patch.object(bot, "build_audio_stats", fake_build_audio_stats),
            patch.object(bot, "format_audio_stats", return_value="*Аудио статистика*"),
        ):
            await bot.handle_stat(update, SimpleNamespace())

        self.assertEqual(message.reply_text.await_args_list[0].args, ("Counting saved audio stats...",))
        self.assertEqual(message.reply_text.await_args_list[1].args, ("*Аудио статистика*",))
        self.assertEqual(message.reply_text.await_args_list[1].kwargs, {"parse_mode": "Markdown"})


class MainRegistrationTests(unittest.TestCase):
    def test_main_restricts_all_commands_to_allowed_user(self):
        fake_app = FakePollingApplication()

        with patch.object(bot, "ApplicationBuilder", return_value=FakeApplicationBuilder(fake_app)):
            bot.main()

        command_handlers = [
            handler for handler in fake_app.handlers
            if isinstance(handler, CommandHandler)
        ]
        command_filters = {
            next(iter(handler.commands)): handler.filters
            for handler in command_handlers
        }

        self.assertEqual(set(command_filters), {"start", "help", "weekly", "stat", "memory", "rules"})
        self.assertEqual(set(command_filters), {name for name, _ in bot.COMMANDS})
        for command, command_filter in command_filters.items():
            with self.subTest(command=command):
                self.assertEqual(command_filter.user_ids, frozenset({bot.settings.allowed_user_id}))

    def test_help_text_lists_every_command(self):
        for name, description in bot.COMMANDS:
            with self.subTest(command=name):
                self.assertIn(f"/{name} — {description}", bot.HELP_TEXT)


class PostInitTests(unittest.IsolatedAsyncioTestCase):
    def _application(self):
        bot_api = SimpleNamespace(published=None)

        async def set_my_commands(commands):
            bot_api.published = commands

        bot_api.set_my_commands = set_my_commands
        return SimpleNamespace(bot=bot_api)

    async def test_post_init_publishes_menu_ensures_memory_pages_then_replays(self):
        application = self._application()
        replayed = []

        with patch.object(bot.notion_memory, "ensure_memory_pages", new=AsyncMock()) as ensure, \
                patch.object(bot, "replay_unprocessed_messages", new=AsyncMock(side_effect=replayed.append)):
            await bot.post_init(application)

        self.assertEqual(
            [(command.command, command.description) for command in application.bot.published],
            [(name, description) for name, description in bot.COMMANDS],
        )
        ensure.assert_awaited_once_with()
        self.assertEqual(replayed, [application])

    async def test_post_init_still_replays_when_notion_is_unreachable(self):
        application = self._application()
        replayed = []

        with patch.object(
                    bot.notion_memory,
                    "ensure_memory_pages",
                    new=AsyncMock(side_effect=RuntimeError("notion down")),
                ), \
                patch.object(bot.logger, "exception"), \
                patch.object(bot, "replay_unprocessed_messages", new=AsyncMock(side_effect=replayed.append)):
            await bot.post_init(application)

        self.assertEqual(replayed, [application])


class FakeSendBot:
    def __init__(self):
        self.sent_messages = []
        self.username = "diary_bot"

    async def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)
        return SimpleNamespace(
            chat_id=kwargs["chat_id"],
            message_id=999,
            get_bot=lambda: self,
        )


class FakeEditBot:
    def __init__(self):
        self.edits = []
        self.username = "diary_bot"

    async def edit_message_text(self, **kwargs):
        self.edits.append(kwargs)
        return SimpleNamespace(
            chat_id=kwargs["chat_id"],
            message_id=kwargs["message_id"],
            get_bot=lambda: self,
        )


class FakeQuery:
    def __init__(self, data=None):
        self.edits = []
        self.data = data
        self.message = SimpleNamespace(chat_id=123, message_id=20, reply_text=AsyncMock())

    async def answer(self):
        pass

    async def edit_message_text(self, text, **kwargs):
        self.edits.append({"text": text, **kwargs})


class FakeApplication:
    def __init__(self, close_coroutines=False):
        self.created_tasks = []
        self.close_coroutines = close_coroutines

    def create_task(self, coroutine, **kwargs):
        self.created_tasks.append((coroutine, kwargs))
        if self.close_coroutines:
            coroutine.close()


class FakePollingApplication:
    def __init__(self):
        self.handlers = []
        self.job_queue = FakeJobQueue()
        self.polling_started = False

    def add_handler(self, handler):
        self.handlers.append(handler)

    def run_polling(self):
        self.polling_started = True


class FakeJobQueue:
    def __init__(self):
        self.daily_jobs = []

    def run_daily(self, *args, **kwargs):
        self.daily_jobs.append((args, kwargs))


class FakeApplicationBuilder:
    def __init__(self, app):
        self.app = app
        self.token_value = None
        self.defaults_value = None
        self.concurrent_updates_value = None
        self.post_init_callback = None

    def token(self, value):
        self.token_value = value
        return self

    def defaults(self, value):
        self.defaults_value = value
        return self

    def concurrent_updates(self, value):
        self.concurrent_updates_value = value
        return self

    def post_init(self, callback):
        self.post_init_callback = callback
        return self

    def build(self):
        return self.app


class FakeStateStore:
    def __init__(self):
        self.messages = {}
        self.saved_drafts = []
        self.marked_processing = []
        self.marked_failed = []
        self.marked_drafted = []
        self.marked_cancelled = []
        self.marked_duplicate_pending = []
        self.marked_duplicate_confirmed = []
        self.marked_saved = []
        self.removed_drafts = []
        self.duplicate_voice = None

    def record_voice(
        self,
        chat_id,
        message_id,
        file_id,
        date,
        file_unique_id=None,
        duration=None,
        file_size=None,
        source_message_url=None,
    ):
        key = f"{chat_id}:{message_id}"
        self.messages[key] = {
            "key": key,
            "kind": "voice",
            "chat_id": chat_id,
            "message_id": message_id,
            "file_id": file_id,
            "file_unique_id": file_unique_id,
            "duration": duration,
            "file_size": file_size,
            "source_message_url": source_message_url,
            "date": date,
        }
        return key

    def find_duplicate_voice(self, file_unique_id, duration=None, file_size=None, exclude_key=None):
        return self.duplicate_voice

    def get_message(self, key):
        return self.messages.get(key)

    def save_draft(self, draft):
        self.saved_drafts.append(dict(draft))

    def mark_message_processing(self, key):
        self.marked_processing.append(key)
        self.messages[key]["status"] = "processing"

    def mark_message_failed(self, key, error):
        self.marked_failed.append((key, error))
        self.messages[key]["status"] = "failed"
        self.messages[key]["error"] = error

    def mark_message_drafted(self, key, entry_id):
        self.marked_drafted.append((key, entry_id))

    def mark_message_duplicate_pending(self, key, duplicate_key):
        self.marked_duplicate_pending.append((key, duplicate_key))

    def mark_message_duplicate_confirmed(self, key):
        self.marked_duplicate_confirmed.append(key)
        self.messages[key]["allow_duplicate"] = True

    def mark_message_saved(self, key):
        self.marked_saved.append(key)

    def mark_message_cancelled(self, key):
        self.marked_cancelled.append(key)

    def remove_draft(self, entry_id):
        self.removed_drafts.append(entry_id)


class FakeRoastBot:
    def __init__(self):
        self.sent = []
        self.edits = []
        self.username = "diary_bot"
        self._counter = 1000

    async def send_message(self, **kwargs):
        self._counter += 1
        self.sent.append(kwargs)
        return SimpleNamespace(
            chat_id=kwargs["chat_id"],
            message_id=self._counter,
            get_bot=lambda: self,
        )

    async def edit_message_text(self, **kwargs):
        self.edits.append(kwargs)
        return SimpleNamespace(
            chat_id=kwargs["chat_id"],
            message_id=kwargs["message_id"],
            get_bot=lambda: self,
        )


class MemoryNoteTests(unittest.TestCase):
    def test_note_carries_both_blocks(self):
        note = bot._render_memory_note(
            (bot.PROFILE_BLOCK_LABEL, ["+ играет в пинг-понг"]),
            (bot.RULES_BLOCK_LABEL, ["+ пиши коротко", "− будь мягче"]),
        )
        self.assertEqual(note, (
            "🧠 Memory updated\n"
            "About you:\n+ играет в пинг-понг\n"
            "Rules:\n+ пиши коротко\n− будь мягче"
        ))

    def test_empty_block_is_dropped(self):
        note = bot._render_memory_note(
            (bot.PROFILE_BLOCK_LABEL, []),
            (bot.RULES_BLOCK_LABEL, ["+ пиши коротко"]),
        )
        self.assertEqual(note, "🧠 Memory updated\nRules:\n+ пиши коротко")

    def test_nothing_changed_means_no_note(self):
        self.assertIsNone(
            bot._render_memory_note(
                (bot.PROFILE_BLOCK_LABEL, []), (bot.RULES_BLOCK_LABEL, [])
            )
        )

    def test_diff_lines_read_a_rewrite_as_gained_and_lost(self):
        lines = bot._memory_diff_lines(
            _items("любит кофе", "живёт в Лиссабоне"),
            _items("живёт в Паттайе", "любит кофе"),
        )
        self.assertEqual(lines, ["+ живёт в Паттайе", "− живёт в Лиссабоне"])


class SplitMessageTests(unittest.TestCase):
    def test_short_text_is_a_single_chunk(self):
        self.assertEqual(bot._split_message("short"), ["short"])

    def test_long_text_splits_into_chunks_within_limit(self):
        text = "x" * (bot.TELEGRAM_MESSAGE_LIMIT * 2 + 10)
        chunks = bot._split_message(text)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= bot.TELEGRAM_MESSAGE_LIMIT for chunk in chunks))
        self.assertEqual("".join(chunks), text)

    def test_prefers_newline_then_space_boundaries(self):
        first = "a" * (bot.TELEGRAM_MESSAGE_LIMIT - 5)
        text = f"{first}\nsecond part"
        chunks = bot._split_message(text)

        self.assertEqual(chunks[0], first)
        self.assertEqual(chunks[1], "second part")


class RoastKeyboardTests(unittest.TestCase):
    def test_roast_button_appears_just_before_save_when_configured(self):
        with patch.object(bot.roast, "is_configured", lambda: True):
            keyboard = bot._preview_keyboard("entry-1", entry_date=bot._default_entry_date())
        callback_data = [b.callback_data for row in keyboard.inline_keyboard for b in row]

        self.assertIn("roast:entry-1", callback_data)
        self.assertEqual(callback_data.index("roast:entry-1"), callback_data.index("save:entry-1") - 1)

    def test_roast_button_hidden_when_not_configured(self):
        with patch.object(bot.roast, "is_configured", lambda: False):
            keyboard = bot._preview_keyboard("entry-1", entry_date=bot._default_entry_date())
        callback_data = [b.callback_data for row in keyboard.inline_keyboard for b in row]

        self.assertNotIn("roast:entry-1", callback_data)


def _items(*texts):
    """Stored memory as the bot holds it: text plus the id the model addresses."""
    return [bot.memory.MemoryItem(str(index), text) for index, text in enumerate(texts, 1)]


def _roast_reply(text, rules_ops=None):
    return bot.roast.RoastReply(text, rules_ops)


class RulesCommandTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, rules):
        reply_text = AsyncMock()
        update = SimpleNamespace(effective_message=SimpleNamespace(reply_text=reply_text))
        with patch.object(bot.state_store, "get_rules", return_value=rules):
            await bot.handle_rules(update, SimpleNamespace())
        return reply_text.await_args.args[0]

    async def test_rules_command_numbers_the_stored_rules(self):
        text = await self._run(_items("не задавай вопросов", "пиши коротко"))
        self.assertEqual(text, "🧠 Rules\n1. не задавай вопросов\n2. пиши коротко")

    async def test_rules_command_explains_an_empty_list(self):
        self.assertIn("No rules yet", await self._run([]))


class RoastFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        bot._roast_chains.clear()

    def tearDown(self):
        bot._roast_chains.clear()

    async def test_roast_button_sends_reply_and_stores_chain(self):
        fake_bot = FakeRoastBot()
        query = SimpleNamespace(
            message=SimpleNamespace(chat_id=123, message_id=20, get_bot=lambda: fake_bot, reply_text=AsyncMock()),
        )
        context = SimpleNamespace(bot=fake_bot, user_data={})
        draft = {"id": "entry-1", "text": "got nothing done today", "chat_id": 123}

        captured = []
        captured_points = []
        captured_rules = []

        async def fake_roast(messages, points=None, rules=None):
            captured.append([dict(m) for m in messages])
            captured_points.append(points)
            captured_rules.append(rules)
            return _roast_reply("Roast ready.")

        with patch.object(bot.roast, "is_configured", lambda: True), \
                patch.object(bot.roast, "roast", new=fake_roast), \
                patch.object(bot.state_store, "get_profile_points", return_value=_items("knows guitar")), \
                patch.object(bot.state_store, "get_rules", return_value=_items("будь короче")), \
                patch.object(bot.state_store, "set_rules") as save_rules, \
                patch.object(bot, "_sync_memory", new=AsyncMock()) as pulled, \
                patch.object(bot, "_update_profile_points", new=AsyncMock()) as fake_update:
            await bot._roast_draft(query, context, draft)

        # Memory is pulled from Notion before it is read, so a hand-edited page
        # steers the very next roast.
        pulled.assert_awaited_once()
        # Stored profile points ride along as context; roast no longer triggers a profile refresh
        # (extraction happens once at message ingestion).
        self.assertEqual(captured_points, [_items("knows guitar")])
        # Behavior rules ride along too, and an answer without ops saves nothing.
        self.assertEqual(captured_rules, [_items("будь короче")])
        save_rules.assert_not_called()
        fake_update.assert_not_awaited()
        self.assertEqual(captured, [[{"role": "user", "content": "got nothing done today"}]])
        # Status message (id 1001) was edited into the answer.
        self.assertEqual(fake_bot.edits[-1]["text"], "Roast ready.")
        stored = bot._roast_chains["123:1001"]
        self.assertEqual(stored, [
            {"role": "user", "content": "got nothing done today"},
            {"role": "assistant", "content": "Roast ready."},
        ])

    async def _roast_with_ops(self, ops, stored_rules, save_rules):
        fake_bot = FakeRoastBot()
        query = SimpleNamespace(
            message=SimpleNamespace(chat_id=123, message_id=20, get_bot=lambda: fake_bot, reply_text=AsyncMock()),
        )
        context = SimpleNamespace(bot=fake_bot, user_data={})

        with patch.object(bot.roast, "is_configured", lambda: True), \
                patch.object(bot.roast, "roast", new=AsyncMock(return_value=_roast_reply("Roast ready.", ops))), \
                patch.object(bot.state_store, "get_profile_points", return_value=[]), \
                patch.object(bot.state_store, "get_rules", return_value=stored_rules), \
                patch.object(bot.state_store, "set_rules", save_rules), \
                patch.object(bot, "_sync_memory", new=AsyncMock()), \
                patch.object(bot, "_sync_bot_memory", new=AsyncMock()) as self.mirror, \
                patch.object(bot, "_update_profile_points", new=AsyncMock()):
            await bot._roast_draft(query, context, {"id": "e", "text": "entry", "chat_id": 123})
        return fake_bot

    async def test_rule_ops_in_a_reply_are_applied_saved_and_announced(self):
        save_rules = MagicMock()
        ops = [
            {"action": "delete", "id": "1"},
            {"action": "create", "text": "не задавай вопросов"},
        ]

        fake_bot = await self._roast_with_ops(ops, _items("будь мягче", "пиши коротко"), save_rules)

        # The surviving rule keeps its id; the new one gets a fresh one.
        save_rules.assert_called_once_with([
            bot.memory.MemoryItem("2", "пиши коротко"),
            bot.memory.MemoryItem("3", "не задавай вопросов"),
        ])
        # A saved change is mirrored to the Notion rules page.
        self.mirror.assert_awaited_once()
        note = fake_bot.sent[-1]["text"]
        self.assertEqual(
            note,
            "🧠 Memory updated\nRules:\n+ не задавай вопросов\n− будь мягче",
        )
        # The roast text itself stays clean of protocol chatter.
        self.assertEqual(fake_bot.edits[-1]["text"], "Roast ready.")

    async def test_reply_without_rule_ops_never_rewrites_the_list(self):
        save_rules = MagicMock()

        fake_bot = await self._roast_with_ops(None, _items("пиши коротко"), save_rules)

        save_rules.assert_not_called()
        self.mirror.assert_not_awaited()
        self.assertEqual(len(fake_bot.sent), 1)  # status message only, no note

    async def test_ops_that_change_nothing_never_rewrite_the_list(self):
        # A redundant create, or one aimed at an id that does not exist, must not
        # touch stored rules.
        for ops in ([{"action": "create", "text": "пиши коротко"}],
                    [{"action": "delete", "id": "99"}],
                    [{"action": "modify", "id": "99", "text": "orphan"}]):
            with self.subTest(ops=ops):
                save_rules = MagicMock()
                fake_bot = await self._roast_with_ops(ops, _items("пиши коротко"), save_rules)
                save_rules.assert_not_called()
                self.assertEqual(len(fake_bot.sent), 1)

    async def test_rules_note_keeps_the_conversation_replyable(self):
        save_rules = MagicMock()

        await self._roast_with_ops([{"action": "create", "text": "будь резче"}], [], save_rules)

        # Note is sent as message 1002 after the status edit (1001); replying to
        # either continues the same chain.
        self.assertEqual(bot._roast_chains["123:1002"], bot._roast_chains["123:1001"])

    async def test_failure_to_save_rules_never_breaks_the_roast(self):
        save_rules = MagicMock(side_effect=RuntimeError("disk on fire"))

        fake_bot = await self._roast_with_ops(
            [{"action": "create", "text": "будь резче"}], [], save_rules
        )

        self.assertEqual(fake_bot.edits[-1]["text"], "Roast ready.")

    async def test_roast_button_warns_when_not_configured(self):
        reply_text = AsyncMock()
        query = SimpleNamespace(message=SimpleNamespace(reply_text=reply_text))
        context = SimpleNamespace(bot=FakeRoastBot(), user_data={})

        with patch.object(bot.roast, "is_configured", lambda: False):
            await bot._roast_draft(query, context, {"id": "e", "text": "x", "chat_id": 1})

        reply_text.assert_awaited_once()
        self.assertIn("ANTHROPIC_API_KEY", reply_text.await_args.args[0])

    async def test_update_profile_points_extracts_persists_and_mirrors(self):
        with patch.object(bot.state_store, "get_profile_points", return_value=_items("old fact")), \
                patch.object(bot.roast, "extract_profile_points", new=AsyncMock(return_value=_items("fresh fact"))) as extract, \
                patch.object(bot, "_sync_author_memory", new=AsyncMock()) as pull, \
                patch.object(bot, "_sync_author_memory_held", new=AsyncMock()) as push, \
                patch.object(bot.state_store, "set_profile_points") as save:
            await bot._update_profile_points("today's entry")

        extract.assert_awaited_once_with("today's entry", _items("old fact"))
        save.assert_called_once_with(_items("fresh fact"))
        # Pull hand edits before extracting, push the merged profile after.
        pull.assert_awaited_once()
        push.assert_awaited_once()

    async def test_a_profile_moved_while_extracting_drops_the_pass(self):
        # A hand edit adopted mid-extraction must not be overwritten by a list
        # merged from the stale read.
        moved = [_items("old fact"), _items("typed by hand")]

        with patch.object(bot.state_store, "get_profile_points", side_effect=moved), \
                patch.object(bot.roast, "extract_profile_points", new=AsyncMock(return_value=_items("fresh fact"))), \
                patch.object(bot, "_sync_author_memory", new=AsyncMock()), \
                patch.object(bot, "_sync_author_memory_held", new=AsyncMock()) as push, \
                patch.object(bot.state_store, "set_profile_points") as save:
            await bot._update_profile_points("today's entry")

        save.assert_not_called()
        push.assert_not_awaited()

    async def _extract_with_note(self, before, after):
        fake_bot = FakeRoastBot()
        target = SimpleNamespace(chat_id=123, message_id=20, get_bot=lambda: fake_bot)

        with patch.object(bot.state_store, "get_profile_points", return_value=before), \
                patch.object(bot.roast, "extract_profile_points", new=AsyncMock(return_value=after)), \
                patch.object(bot, "_sync_author_memory", new=AsyncMock()), \
                patch.object(bot, "_sync_author_memory_held", new=AsyncMock()), \
                patch.object(bot.state_store, "set_profile_points"):
            await bot._update_profile_points("today's entry", target)
        return fake_bot

    async def test_new_facts_are_announced(self):
        fake_bot = await self._extract_with_note(
            _items("любит кофе"), _items("любит кофе", "играет в пинг-понг")
        )

        self.assertEqual(
            fake_bot.sent[-1]["text"],
            "🧠 Memory updated\nAbout you:\n+ играет в пинг-понг",
        )

    async def test_profile_note_starts_a_replyable_conversation(self):
        fake_bot = await self._extract_with_note(
            _items("любит кофе"), _items("любит кофе", "играет в пинг-понг")
        )

        self.assertEqual(bot._roast_chains["123:1001"], [
            {"role": "user", "content": "today's entry"},
            {"role": "assistant", "content": "🧠 Memory updated\nAbout you:\n+ играет в пинг-понг"},
        ])

    async def test_reply_to_profile_note_continues_its_conversation(self):
        fake_bot = await self._extract_with_note(
            _items("любит кофе"), _items("любит кофе", "играет в пинг-понг")
        )
        user_msg = SimpleNamespace(
            text="that needs an edit",
            reply_to_message=SimpleNamespace(message_id=1001),
            chat_id=123,
            message_id=30,
            get_bot=lambda: fake_bot,
        )
        update = SimpleNamespace(effective_message=user_msg, effective_chat=SimpleNamespace(id=123))
        context = SimpleNamespace(bot=fake_bot, user_data={})
        captured = []

        async def fake_roast(messages, points=None, rules=None):
            captured.append([dict(message) for message in messages])
            return _roast_reply("updated")

        with patch.object(bot.roast, "roast", new=fake_roast), \
                patch.object(bot.state_store, "get_profile_points", return_value=[]), \
                patch.object(bot.state_store, "get_rules", return_value=[]), \
                patch.object(bot, "_sync_memory", new=AsyncMock()) as sync_memory:
            await bot.receive_edit_reply(update, context)

        sync_memory.assert_awaited_once()
        self.assertEqual(captured, [[
            {"role": "user", "content": "today's entry"},
            {"role": "assistant", "content": "🧠 Memory updated\nAbout you:\n+ играет в пинг-понг"},
            {"role": "user", "content": "that needs an edit"},
        ]])

    async def test_long_profile_note_maps_every_chunk_to_its_full_context(self):
        long_fact = "x" * (bot.TELEGRAM_MESSAGE_LIMIT + 100)
        fake_bot = await self._extract_with_note([], _items(long_fact))

        expected = [
            {"role": "user", "content": "today's entry"},
            {"role": "assistant", "content": f"🧠 Memory updated\nAbout you:\n+ {long_fact}"},
        ]
        self.assertEqual(bot._roast_chains["123:1001"], expected)
        self.assertEqual(bot._roast_chains["123:1002"], expected)

    async def test_an_entry_that_taught_nothing_sends_nothing(self):
        fake_bot = await self._extract_with_note(_items("любит кофе"), _items("любит кофе"))

        self.assertEqual(fake_bot.sent, [])
        self.assertEqual(bot._roast_chains, {})

    async def test_update_profile_points_swallows_failures(self):
        with patch.object(bot.state_store, "get_profile_points", return_value=[]), \
                patch.object(bot.roast, "extract_profile_points", new=AsyncMock(side_effect=RuntimeError("boom"))), \
                patch.object(bot, "_sync_author_memory", new=AsyncMock()), \
                patch.object(bot.state_store, "set_profile_points") as save:
            await bot._update_profile_points("entry")

        save.assert_not_called()



    async def test_reply_to_roast_message_continues_conversation(self):
        fake_bot = FakeRoastBot()
        bot._roast_chains["123:50"] = [
            {"role": "user", "content": "original entry"},
            {"role": "assistant", "content": "first roast"},
        ]
        user_msg = SimpleNamespace(
            text="why is that?",
            reply_to_message=SimpleNamespace(message_id=50),
            chat_id=123,
            message_id=60,
            get_bot=lambda: fake_bot,
            reply_text=AsyncMock(),
        )
        update = SimpleNamespace(
            effective_message=user_msg,
            effective_chat=SimpleNamespace(id=123),
        )
        context = SimpleNamespace(bot=fake_bot, user_data={})

        captured = []

        async def fake_roast(messages, points=None, rules=None):
            captured.append([dict(m) for m in messages])
            return _roast_reply("answer to the question")

        with patch.object(bot.roast, "roast", new=fake_roast), \
                patch.object(bot.state_store, "get_profile_points", return_value=[]), \
                patch.object(bot.state_store, "get_rules", return_value=[]), \
                patch.object(bot, "_sync_memory", new=AsyncMock()) as sync_memory, \
                patch.object(bot, "handle_text", new=AsyncMock()) as fake_handle_text:
            await bot.receive_edit_reply(update, context)

        sync_memory.assert_awaited_once()
        fake_handle_text.assert_not_awaited()
        self.assertEqual(captured, [[
            {"role": "user", "content": "original entry"},
            {"role": "assistant", "content": "first roast"},
            {"role": "user", "content": "why is that?"},
        ]])
        # New assistant turn appended and stored under the freshly sent message id.
        self.assertEqual(bot._roast_chains["123:1001"], [
            {"role": "user", "content": "original entry"},
            {"role": "assistant", "content": "first roast"},
            {"role": "user", "content": "why is that?"},
            {"role": "assistant", "content": "answer to the question"},
        ])

    async def test_long_roast_answer_splits_and_maps_every_chunk_to_chain(self):
        fake_bot = FakeRoastBot()
        query = SimpleNamespace(
            message=SimpleNamespace(chat_id=123, message_id=20, get_bot=lambda: fake_bot, reply_text=AsyncMock()),
        )
        context = SimpleNamespace(bot=fake_bot, user_data={})
        draft = {"id": "entry-1", "text": "a reason", "chat_id": 123}
        long_answer = "a" * (bot.TELEGRAM_MESSAGE_LIMIT + 500)

        with patch.object(bot.roast, "is_configured", lambda: True), \
                patch.object(bot.roast, "roast", new=AsyncMock(return_value=_roast_reply(long_answer))), \
                patch.object(bot.state_store, "get_profile_points", return_value=[]), \
                patch.object(bot.state_store, "get_rules", return_value=[]), \
                patch.object(bot, "_sync_memory", new=AsyncMock()) as sync_memory, \
                patch.object(bot, "_update_profile_points", new=AsyncMock()):
            await bot._roast_draft(query, context, draft)

        sync_memory.assert_awaited_once()
        # Answer split into 2 chunks: status edit (id 1001) + one new reply (id 1002).
        self.assertEqual(len(fake_bot.edits), 1)
        self.assertEqual(len(fake_bot.sent), 2)  # status reply + second chunk
        expected_chain = [
            {"role": "user", "content": "a reason"},
            {"role": "assistant", "content": long_answer},
        ]
        self.assertEqual(bot._roast_chains["123:1001"], expected_chain)
        self.assertEqual(bot._roast_chains["123:1002"], expected_chain)

    async def test_reply_to_unrelated_message_falls_through_to_handle_text(self):
        user_msg = SimpleNamespace(
            text="just a normal note",
            reply_to_message=SimpleNamespace(message_id=999),
            chat_id=123,
            message_id=60,
        )
        update = SimpleNamespace(
            effective_message=user_msg,
            effective_chat=SimpleNamespace(id=123),
        )
        context = SimpleNamespace(bot=FakeRoastBot(), user_data={})

        with patch.object(bot, "handle_text", new=AsyncMock()) as fake_handle_text:
            await bot.receive_edit_reply(update, context)

        fake_handle_text.assert_awaited_once()

    @staticmethod
    def _voice_reply_update(fake_bot, replied_to=50):
        user_msg = SimpleNamespace(
            voice=SimpleNamespace(file_id="voice-file-1"),
            reply_to_message=SimpleNamespace(message_id=replied_to),
            chat_id=123,
            message_id=60,
            get_bot=lambda: fake_bot,
            reply_text=AsyncMock(),
        )
        return SimpleNamespace(
            effective_message=user_msg,
            effective_chat=SimpleNamespace(id=123),
        )

    async def test_voice_reply_to_roast_message_continues_conversation(self):
        fake_bot = FakeRoastBot()
        bot._roast_chains["123:50"] = [
            {"role": "user", "content": "original entry"},
            {"role": "assistant", "content": "first roast"},
        ]
        update = self._voice_reply_update(fake_bot)
        context = SimpleNamespace(bot=fake_bot, user_data={})

        captured = []

        async def fake_roast(messages, points=None, rules=None):
            captured.append([dict(m) for m in messages])
            return _roast_reply("answer to the spoken question")

        with patch.object(bot, "_transcribe_voice_file", new=AsyncMock(return_value="why is that?")) as fake_transcribe, \
                patch.object(bot.roast, "roast", new=fake_roast), \
                patch.object(bot.state_store, "get_profile_points", return_value=[]), \
                patch.object(bot.state_store, "get_rules", return_value=[]), \
                patch.object(bot, "_sync_memory", new=AsyncMock()) as sync_memory, \
                patch.object(bot.state_store, "record_voice") as record_voice:
            await bot.handle_voice(update, context)

        # Voice reply never enters the diary flow.
        record_voice.assert_not_called()
        fake_transcribe.assert_awaited_once_with(context, "voice-file-1")
        sync_memory.assert_awaited_once()
        self.assertEqual(captured, [[
            {"role": "user", "content": "original entry"},
            {"role": "assistant", "content": "first roast"},
            {"role": "user", "content": "why is that?"},
        ]])
        self.assertEqual(bot._roast_chains["123:1001"], [
            {"role": "user", "content": "original entry"},
            {"role": "assistant", "content": "first roast"},
            {"role": "user", "content": "why is that?"},
            {"role": "assistant", "content": "answer to the spoken question"},
        ])

    async def test_voice_reply_with_empty_transcription_reports_and_stops(self):
        fake_bot = FakeRoastBot()
        bot._roast_chains["123:50"] = [{"role": "assistant", "content": "first roast"}]
        update = self._voice_reply_update(fake_bot)
        context = SimpleNamespace(bot=fake_bot, user_data={})

        with patch.object(bot, "_transcribe_voice_file", new=AsyncMock(return_value="")), \
                patch.object(bot.roast, "roast", new=AsyncMock()) as fake_roast:
            await bot.handle_voice(update, context)

        fake_roast.assert_not_awaited()
        self.assertIn("did not recognize any speech", fake_bot.edits[-1]["text"])

    async def test_voice_reply_transcription_failure_reports_error(self):
        fake_bot = FakeRoastBot()
        bot._roast_chains["123:50"] = [{"role": "assistant", "content": "first roast"}]
        update = self._voice_reply_update(fake_bot)
        context = SimpleNamespace(bot=fake_bot, user_data={})

        with patch.object(bot, "_transcribe_voice_file", new=AsyncMock(side_effect=RuntimeError("boom"))), \
                patch.object(bot.roast, "roast", new=AsyncMock()) as fake_roast:
            await bot.handle_voice(update, context)

        fake_roast.assert_not_awaited()
        self.assertEqual(fake_bot.edits[-1]["text"], "Error: boom")

    async def test_voice_reply_to_unrelated_message_stays_in_diary_flow(self):
        fake_bot = FakeRoastBot()
        update = self._voice_reply_update(fake_bot, replied_to=999)
        context = SimpleNamespace(
            bot=fake_bot,
            user_data={},
            application=SimpleNamespace(create_task=lambda coro, update=None: coro.close()),
        )

        with patch.object(bot.state_store, "record_voice", return_value="key-1") as record_voice, \
                patch.object(bot.state_store, "find_duplicate_voice", return_value=None), \
                patch.object(bot, "_transcribe_voice_file", new=AsyncMock()) as fake_transcribe:
            await bot.handle_voice(update, context)

        record_voice.assert_called_once()
        fake_transcribe.assert_not_awaited()


class TranscribeVoiceFileTests(unittest.IsolatedAsyncioTestCase):
    async def test_downloads_transcribes_and_removes_temp_file(self):
        downloaded = []

        async def fake_download(path):
            downloaded.append(path)

        fake_bot = SimpleNamespace(
            get_file=AsyncMock(return_value=SimpleNamespace(download_to_drive=fake_download)),
        )
        context = SimpleNamespace(bot=fake_bot)

        with patch.object(bot, "transcribe", new=AsyncMock(return_value="  spoken words  ")):
            result = await bot._transcribe_voice_file(context, "file-9")

        self.assertEqual(result, "spoken words")
        fake_bot.get_file.assert_awaited_once_with("file-9")
        self.assertEqual(len(downloaded), 1)
        self.assertFalse(os.path.exists(downloaded[0]))

    async def test_removes_temp_file_when_transcription_fails(self):
        downloaded = []

        async def fake_download(path):
            downloaded.append(path)

        fake_bot = SimpleNamespace(
            get_file=AsyncMock(return_value=SimpleNamespace(download_to_drive=fake_download)),
        )
        context = SimpleNamespace(bot=fake_bot)

        with patch.object(bot, "transcribe", new=AsyncMock(side_effect=RuntimeError("nope"))):
            with self.assertRaises(RuntimeError):
                await bot._transcribe_voice_file(context, "file-9")

        self.assertFalse(os.path.exists(downloaded[0]))


def _memory_progress(handled, total, points, skipped=0, failed=0, aborted_reason=None):
    return bot.profile_rebuild.RebuildProgress(
        total=total,
        processed=handled - skipped - failed,
        skipped=skipped,
        failed=failed,
        points=list(points),
        aborted_reason=aborted_reason,
    )


class MemoryCommandTests(unittest.IsolatedAsyncioTestCase):
    def _update(self, fake_bot, text="/memory"):
        message = SimpleNamespace(
            text=text,
            chat_id=123,
            message_id=50,
            reply_text=AsyncMock(return_value=SimpleNamespace(chat_id=123, message_id=51)),
        )
        return SimpleNamespace(
            effective_message=message,
            effective_chat=SimpleNamespace(id=123),
        ), message

    async def test_command_asks_for_focus_and_registers_the_prompt(self):
        context = SimpleNamespace(bot=FakeEditBot(), user_data={})
        update, message = self._update(context.bot)

        with patch.object(bot.roast, "is_configured", return_value=True), \
                patch.object(bot.state_store, "get_profile_points", return_value=["known fact"]), \
                patch.object(bot.profile_rebuild, "is_running", return_value=False):
            await bot.handle_memory(update, context)

        kwargs = message.reply_text.await_args.kwargs
        text = message.reply_text.await_args.args[0]
        self.assertIn("Long-term memory rebuild", text)
        self.assertIn("1 fact(s)", text)
        self.assertIn("Send - to rebuild without extra focus", text)
        self.assertIsInstance(kwargs["reply_markup"], bot.ForceReply)
        # The prompt is registered so the reply is treated as focus, not as a note.
        self.assertEqual(bot._memory_prompts(context), {"123:51": True})

    async def test_command_says_profile_is_empty_when_nothing_is_stored(self):
        context = SimpleNamespace(bot=FakeEditBot(), user_data={})
        update, message = self._update(context.bot)

        with patch.object(bot.roast, "is_configured", return_value=True), \
                patch.object(bot.state_store, "get_profile_points", return_value=[]), \
                patch.object(bot.profile_rebuild, "is_running", return_value=False):
            await bot.handle_memory(update, context)

        self.assertIn("built from scratch", message.reply_text.await_args.args[0])

    async def test_command_refuses_without_a_configured_provider(self):
        context = SimpleNamespace(bot=FakeEditBot(), user_data={})
        update, message = self._update(context.bot)

        with patch.object(bot.roast, "is_configured", return_value=False):
            await bot.handle_memory(update, context)

        message.reply_text.assert_awaited_once_with("AI provider API key is not configured.")
        self.assertEqual(bot._memory_prompts(context), {})

    async def test_command_refuses_while_a_rebuild_is_running(self):
        context = SimpleNamespace(bot=FakeEditBot(), user_data={})
        update, message = self._update(context.bot)

        with patch.object(bot.roast, "is_configured", return_value=True), \
                patch.object(bot.profile_rebuild, "is_running", return_value=True):
            await bot.handle_memory(update, context)

        self.assertIn("already running", message.reply_text.await_args.args[0])
        self.assertEqual(bot._memory_prompts(context), {})


class MemoryFocusReplyTests(unittest.IsolatedAsyncioTestCase):
    def _reply_update(self, text):
        user_msg = SimpleNamespace(
            text=text,
            reply_to_message=SimpleNamespace(message_id=51),
            chat_id=123,
            message_id=60,
            reply_text=AsyncMock(),
        )
        return SimpleNamespace(
            effective_message=user_msg,
            effective_chat=SimpleNamespace(id=123),
        ), user_msg

    def _context(self):
        return SimpleNamespace(
            bot=FakeEditBot(),
            user_data={bot.MEMORY_PROMPTS_KEY: {"123:51": True}},
        )

    async def test_focus_reply_shows_confirmation_and_never_becomes_a_note(self):
        context = self._context()
        update, user_msg = self._reply_update("  focus on   work and health  ")

        with patch.object(bot.state_store, "get_profile_points", return_value=["a", "b"]), \
                patch.object(bot, "handle_text", new=AsyncMock()) as fake_handle_text:
            await bot.receive_edit_reply(update, context)

        fake_handle_text.assert_not_awaited()
        text = user_msg.reply_text.await_args.args[0]
        self.assertIn("Ready to rebuild", text)
        self.assertIn("Focus: focus on work and health", text)
        self.assertIn("2 fact(s)", text)

        keyboard = user_msg.reply_text.await_args.kwargs["reply_markup"]
        confirm, cancel = keyboard.inline_keyboard[0]
        request_id = confirm.callback_data.removeprefix("memory_confirm:")
        self.assertEqual(cancel.callback_data, f"memory_cancel:{request_id}")
        self.assertEqual(
            bot._memory_requests(context)[request_id],
            {"focus": "focus on work and health"},
        )
        # The prompt is consumed, so a later unrelated reply is not read as focus.
        self.assertEqual(bot._memory_prompts(context), {})

    async def test_skip_tokens_mean_no_focus(self):
        for token in ["-", "  SKIP ", "none", "—"]:
            with self.subTest(token=token):
                context = self._context()
                update, user_msg = self._reply_update(token)

                with patch.object(bot.state_store, "get_profile_points", return_value=[]):
                    await bot.receive_edit_reply(update, context)

                self.assertIn("Focus: none", user_msg.reply_text.await_args.args[0])
                request = next(iter(bot._memory_requests(context).values()))
                self.assertEqual(request, {"focus": ""})

    async def test_unrelated_reply_still_falls_through_to_handle_text(self):
        context = self._context()
        update, _ = self._reply_update("just a normal note")
        update.effective_message.reply_to_message = SimpleNamespace(message_id=999)

        with patch.object(bot, "handle_text", new=AsyncMock()) as fake_handle_text:
            await bot.receive_edit_reply(update, context)

        fake_handle_text.assert_awaited_once()
        self.assertEqual(bot._memory_prompts(context), {"123:51": True})

    async def test_voice_reply_is_transcribed_into_focus_and_never_saved(self):
        fake_bot = FakeRoastBot()
        context = SimpleNamespace(
            bot=fake_bot,
            user_data={bot.MEMORY_PROMPTS_KEY: {"123:51": True}},
        )
        user_msg = SimpleNamespace(
            voice=SimpleNamespace(file_id="voice-file-1"),
            reply_to_message=SimpleNamespace(message_id=51),
            chat_id=123,
            message_id=60,
            reply_text=AsyncMock(),
            get_bot=lambda: fake_bot,
        )
        update = SimpleNamespace(
            effective_message=user_msg,
            effective_chat=SimpleNamespace(id=123),
        )

        with patch.object(bot, "_transcribe_voice_file", new=AsyncMock(return_value="keep the work stuff")), \
                patch.object(bot.state_store, "get_profile_points", return_value=[]), \
                patch.object(bot.state_store, "record_voice") as record_voice:
            await bot.handle_voice(update, context)

        record_voice.assert_not_called()
        self.assertIn("keep the work stuff", fake_bot.edits[-1]["text"])
        request = next(iter(bot._memory_requests(context).values()))
        self.assertEqual(request, {"focus": "keep the work stuff"})

    async def test_voice_reply_without_speech_reports_and_starts_no_request(self):
        fake_bot = FakeRoastBot()
        context = SimpleNamespace(
            bot=fake_bot,
            user_data={bot.MEMORY_PROMPTS_KEY: {"123:51": True}},
        )
        user_msg = SimpleNamespace(
            voice=SimpleNamespace(file_id="voice-file-1"),
            reply_to_message=SimpleNamespace(message_id=51),
            chat_id=123,
            message_id=60,
            get_bot=lambda: fake_bot,
        )
        update = SimpleNamespace(
            effective_message=user_msg,
            effective_chat=SimpleNamespace(id=123),
        )

        with patch.object(bot, "_transcribe_voice_file", new=AsyncMock(return_value="")), \
                patch.object(bot.state_store, "record_voice") as record_voice:
            await bot.handle_voice(update, context)

        record_voice.assert_not_called()
        self.assertIn("did not recognize any speech", fake_bot.edits[-1]["text"])
        self.assertEqual(bot._memory_requests(context), {})


class MemoryCallbackTests(unittest.IsolatedAsyncioTestCase):
    def _context(self, requests):
        return SimpleNamespace(
            bot=FakeEditBot(),
            application=FakeApplication(close_coroutines=True),
            user_data={bot.MEMORY_REQUESTS_KEY: requests},
        )

    async def test_confirm_starts_the_rebuild_task(self):
        context = self._context({"req-1": {"focus": "work"}})
        query = FakeQuery(data="memory_confirm:req-1")
        update = SimpleNamespace(callback_query=query)

        with patch.object(bot.profile_rebuild, "is_running", return_value=False):
            await bot.memory_callback(update, context)

        self.assertIn("Starting the long-term memory rebuild", query.edits[0]["text"])
        self.assertEqual(len(context.application.created_tasks), 1)
        # The request is consumed, so the same button cannot start a second pass.
        self.assertEqual(bot._memory_requests(context), {})

    async def test_cancel_drops_the_request_without_running(self):
        context = self._context({"req-1": {"focus": "work"}})
        query = FakeQuery(data="memory_cancel:req-1")
        update = SimpleNamespace(callback_query=query)

        await bot.memory_callback(update, context)

        self.assertEqual(query.edits[0]["text"], "Memory rebuild cancelled.")
        self.assertEqual(context.application.created_tasks, [])
        self.assertEqual(bot._memory_requests(context), {})

    async def test_stale_request_is_reported(self):
        context = self._context({})
        query = FakeQuery(data="memory_confirm:gone")
        update = SimpleNamespace(callback_query=query)

        await bot.memory_callback(update, context)

        self.assertIn("no longer available", query.edits[0]["text"])
        self.assertEqual(context.application.created_tasks, [])

    async def test_confirm_refuses_while_another_pass_is_running(self):
        context = self._context({"req-1": {"focus": ""}})
        query = FakeQuery(data="memory_confirm:req-1")
        update = SimpleNamespace(callback_query=query)

        with patch.object(bot.profile_rebuild, "is_running", return_value=True):
            await bot.memory_callback(update, context)

        self.assertIn("already running", query.edits[0]["text"])
        self.assertEqual(context.application.created_tasks, [])


class MemoryRebuildRunnerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.context = SimpleNamespace(bot=FakeEditBot(), user_data={})
        self.status_message = SimpleNamespace(chat_id=123, message_id=20)

    async def _run(self, fake_rebuild, before=None):
        with patch.object(bot.state_store, "get_profile_points", return_value=_items(*(before or []))), \
                patch.object(bot.state_store, "set_profile_points") as saved, \
                patch.object(bot, "_sync_author_memory", new=AsyncMock()) as self.mirror, \
                patch.object(bot.profile_rebuild, "rebuild_profile", new=fake_rebuild):
            await bot._run_memory_rebuild(self.context, self.status_message, "work")
        return saved

    async def test_progress_is_persisted_per_note_and_edits_are_throttled(self):
        async def fake_rebuild(focus, existing, on_progress):
            self.assertEqual(focus, "work")
            self.assertEqual(existing, _items("old"))
            for handled in range(7):
                await on_progress(_memory_progress(handled, 6, _items("old", *(f"f{i}" for i in range(handled)))))
            return _memory_progress(6, 6, _items("old", *(f"f{i}" for i in range(6))))

        saved = await self._run(fake_rebuild, before=["old"])

        # Every note persists, so an abort or a restart never loses the pass.
        self.assertEqual(saved.call_count, 7)
        self.assertEqual(saved.call_args_list[3].args[0], _items("old", "f0", "f1", "f2"))

        # One pull before the pass and one write after it, not one per note.
        self.assertEqual(self.mirror.await_count, 2)

        # Only every 5th note refreshes the message, plus the final result.
        progress_edits = [edit["text"] for edit in self.context.bot.edits[:-1]]
        self.assertEqual(len(progress_edits), 2)
        self.assertIn("0/6 notes", progress_edits[0])
        self.assertIn("5/6 notes", progress_edits[1])
        for text in progress_edits:
            self.assertIn("Rebuilding long-term memory", text)
            self.assertIn("Focus: work", text)

    async def test_final_message_reports_the_delta(self):
        async def fake_rebuild(focus, existing, on_progress):
            return _memory_progress(5, 5, ["a", "b", "c"], skipped=1, failed=1)

        await self._run(fake_rebuild, before=["a"])

        text = self.context.bot.edits[-1]["text"]
        self.assertIn("✅ Long-term memory rebuilt", text)
        self.assertIn("Notes read: 3", text)
        self.assertIn("Empty notes skipped: 1", text)
        self.assertIn("Notes failed: 1", text)
        self.assertIn("Facts: 1 → 3", text)
        self.assertIn("100%", text)

    async def test_aborted_pass_is_reported_as_stopped_early(self):
        async def fake_rebuild(focus, existing, on_progress):
            return _memory_progress(3, 40, ["a"], failed=3, aborted_reason="3 notes in a row failed at note 3/40")

        await self._run(fake_rebuild)

        text = self.context.bot.edits[-1]["text"]
        self.assertIn("stopped early", text)
        self.assertIn("3 notes in a row failed", text)
        self.assertIn("Everything processed so far is saved", text)

    async def test_empty_database_is_reported_without_a_delta(self):
        async def fake_rebuild(focus, existing, on_progress):
            return _memory_progress(0, 0, [])

        await self._run(fake_rebuild)

        self.assertIn("No saved notes found", self.context.bot.edits[-1]["text"])

    async def test_rebuild_failure_is_reported_and_swallowed(self):
        fake_rebuild = AsyncMock(side_effect=RuntimeError("notion down"))

        with patch.object(bot.logger, "exception"):
            await self._run(fake_rebuild)

        self.assertIn("Memory rebuild failed: notion down", self.context.bot.edits[-1]["text"])
        # Only the pull before the pass: a pass that never ran has nothing to write.
        self.assertEqual(self.mirror.await_count, 1)

    async def test_concurrent_pass_is_reported_without_a_traceback(self):
        fake_rebuild = AsyncMock(
            side_effect=bot.profile_rebuild.RebuildAlreadyRunning("already running")
        )

        await self._run(fake_rebuild)

        self.assertIn("already running", self.context.bot.edits[-1]["text"])


class MemorySyncTests(unittest.IsolatedAsyncioTestCase):
    """Local state and the Notion memory pages, kept together in both directions."""

    def setUp(self):
        # Never pulled. A zero would throttle on a host booted under a minute ago.
        bot._last_memory_pull = None

    def _sync(self, adopted: bool, items: list[str], failure: Exception | None = None):
        return AsyncMock(
            side_effect=failure,
            return_value=bot.notion_memory.MemorySync(items, adopted),
        )

    async def test_author_profile_edited_in_notion_replaces_local_state(self):
        # The page carries plain text: an untouched bullet keeps its id, a
        # reworded one becomes a new entry.
        sync = self._sync(adopted=True, items=["stored fact", "typed by hand"])
        with patch.object(bot.state_store, "get_profile_points", return_value=_items("stored fact")), \
                patch.object(bot.state_store, "get_notion_mirror", return_value=["stored fact"]), \
                patch.object(bot.notion_memory, "sync_author_memory", new=sync), \
                patch.object(bot.state_store, "set_profile_points") as save, \
                patch.object(bot.state_store, "set_notion_mirror") as remember:
            await bot._sync_author_memory()

        sync.assert_awaited_once_with(["stored fact"], ["stored fact"])
        save.assert_called_once_with(_items("stored fact", "typed by hand"))
        remember.assert_called_once_with(bot.PROFILE_SECTION, ["stored fact", "typed by hand"])

    async def test_rules_edited_in_notion_replace_local_state(self):
        sync = self._sync(adopted=True, items=["typed by hand"])
        with patch.object(bot.state_store, "get_rules", return_value=_items("stored rule")), \
                patch.object(bot.state_store, "get_notion_mirror", return_value=["stored rule"]), \
                patch.object(bot.notion_memory, "sync_bot_memory", new=sync), \
                patch.object(bot.state_store, "set_rules") as save, \
                patch.object(bot.state_store, "set_notion_mirror") as remember:
            await bot._sync_bot_memory()

        # The stored rule was reworded, so it is a different rule with a new id.
        save.assert_called_once_with([bot.memory.MemoryItem("2", "typed by hand")])
        remember.assert_called_once_with(bot.RULES_SECTION, ["typed by hand"])

    async def test_an_untouched_page_leaves_local_state_alone(self):
        sync = self._sync(adopted=False, items=["stored rule"])
        with patch.object(bot.state_store, "get_rules", return_value=_items("stored rule")), \
                patch.object(bot.state_store, "get_notion_mirror", return_value=[]), \
                patch.object(bot.notion_memory, "sync_bot_memory", new=sync), \
                patch.object(bot.state_store, "set_rules") as save, \
                patch.object(bot.state_store, "set_notion_mirror") as remember:
            await bot._sync_bot_memory()

        save.assert_not_called()
        # The mirror still moves: the page is now known to list these rules.
        remember.assert_called_once_with(bot.RULES_SECTION, ["stored rule"])

    async def test_a_failing_sync_is_swallowed_and_changes_nothing(self):
        sync = self._sync(adopted=True, items=["x"], failure=RuntimeError("notion down"))
        with patch.object(bot.state_store, "get_profile_points", return_value=_items("fact")), \
                patch.object(bot.state_store, "get_notion_mirror", return_value=["fact"]), \
                patch.object(bot.notion_memory, "sync_author_memory", new=sync), \
                patch.object(bot.state_store, "set_profile_points") as save, \
                patch.object(bot.state_store, "set_notion_mirror") as remember:
            await bot._sync_author_memory()

        save.assert_not_called()
        remember.assert_not_called()

    async def test_rules_command_pulls_hand_edits_before_printing(self):
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(effective_message=message)

        with patch.object(bot, "_sync_bot_memory", new=AsyncMock()) as sync, \
                patch.object(bot.state_store, "get_rules", return_value=_items("typed by hand")):
            await bot.handle_rules(update, SimpleNamespace())

        sync.assert_awaited_once()
        self.assertIn("typed by hand", message.reply_text.await_args.args[0])

    async def test_startup_pulls_both_pages(self):
        application = SimpleNamespace(bot=SimpleNamespace(set_my_commands=AsyncMock()))

        with patch.object(bot.notion_memory, "ensure_memory_pages", new=AsyncMock()), \
                patch.object(bot, "_sync_author_memory_held", new=AsyncMock()) as author, \
                patch.object(bot, "_sync_bot_memory_held", new=AsyncMock()) as rules, \
                patch.object(bot, "replay_unprocessed_messages", new=AsyncMock()):
            await bot.post_init(application)

        author.assert_awaited_once()
        rules.assert_awaited_once()

    async def test_a_second_pull_inside_the_window_reuses_the_first(self):
        with patch.object(bot, "_sync_author_memory_held", new=AsyncMock()) as author, \
                patch.object(bot, "_sync_bot_memory_held", new=AsyncMock()):
            await bot._sync_memory()
            await bot._sync_memory()

        # A roast follow-up seconds later must not cost two more Notion reads.
        author.assert_awaited_once()

    async def test_a_freshly_booted_host_still_pulls(self):
        # `monotonic()` counts from boot: right after one, every timestamp is a
        # small number and must not read as a pull that just happened.
        with patch.object(bot, "monotonic", return_value=1.0), \
                patch.object(bot, "_sync_author_memory_held", new=AsyncMock()) as author, \
                patch.object(bot, "_sync_bot_memory_held", new=AsyncMock()):
            await bot._sync_memory()

        author.assert_awaited_once()

    async def test_an_expired_window_pulls_again(self):
        with patch.object(bot, "_sync_author_memory_held", new=AsyncMock()) as author, \
                patch.object(bot, "_sync_bot_memory_held", new=AsyncMock()):
            await bot._sync_memory()
            bot._last_memory_pull -= bot.MEMORY_PULL_TTL_SECONDS
            await bot._sync_memory()

        self.assertEqual(author.await_count, 2)

    async def test_explicit_reads_ignore_the_window(self):
        # /rules and /memory ask for the current list, so they always pull.
        with patch.object(bot, "_sync_bot_memory_held", new=AsyncMock()) as rules, \
                patch.object(bot, "_sync_author_memory_held", new=AsyncMock()):
            await bot._sync_memory()
            await bot._sync_bot_memory()

        self.assertEqual(rules.await_count, 2)

    async def test_memory_is_touched_by_one_coroutine_at_a_time(self):
        running = 0
        peak = 0

        async def slow_sync():
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0)
            running -= 1

        with patch.object(bot, "_sync_author_memory_held", new=slow_sync), \
                patch.object(bot, "_sync_bot_memory_held", new=AsyncMock()):
            await asyncio.gather(
                bot._sync_author_memory(),
                bot._sync_author_memory(),
                bot._sync_author_memory(),
            )

        self.assertEqual(peak, 1)
