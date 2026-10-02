import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("NOTION_TOKEN", "test-notion-token")
os.environ.setdefault("NOTION_DATABASE_ID", "test-notion-db")
os.environ.setdefault("ALLOWED_USER_ID", "1")

import bot
from telegram.error import BadRequest

from services import speech
from services.state_store import StateStore


class SpeechTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_speech_arguments(self):
        create = AsyncMock(return_value=SimpleNamespace(content=b"opus"))
        client = SimpleNamespace(audio=SimpleNamespace(speech=SimpleNamespace(create=create)))
        with patch.object(speech, "client", client):
            self.assertEqual(await speech.synthesize("Hello"), b"opus")
        self.assertEqual(create.await_args.kwargs, dict(
            model=speech.settings.openai_tts_model, voice=speech.settings.openai_tts_voice,
            input="Hello", instructions=speech.VOICE_INSTRUCTIONS, response_format="opus",
        ))

    def test_unicode_and_boundaries(self):
        for text in ["界🙂" * 1200, "A sentence. " * 700, "paragraph\n\n" * 400, "word " * 1500]:
            chunks = speech.split_speech(text)
            self.assertTrue(all(0 < len(c.encode()) <= speech.MAX_INPUT_BYTES for c in chunks))
            self.assertEqual("".join(text.split()), "".join("".join(chunks).split()))
        self.assertEqual(speech.split_speech("  "), [])


class VoiceFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = StateStore(Path(self.temp.name) / "state.json")
        self.store.set_voice_mode(1, True)
        self.patch = patch.object(bot, "state_store", self.store)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        bot._roast_chains.clear()
        bot._chat_mode_chains.clear()
        self.client = SimpleNamespace(
            send_voice=AsyncMock(side_effect=self.sent_voice),
            send_message=AsyncMock(side_effect=self.sent_text),
            edit_message_text=AsyncMock(), delete_message=AsyncMock(), set_my_commands=AsyncMock(),
        )
        self.counter = 20
        self.audio = []
        self.context = SimpleNamespace(bot=self.client)
        self.source = bot.StoredMessageRef(self.client, 1, 10)
        self.status = bot.StoredMessageRef(self.client, 1, 11)
        self.chain = [{"role": "assistant", "content": "Complete answer"}]

    def message(self):
        self.counter += 1
        return SimpleNamespace(chat_id=1, message_id=self.counter, get_bot=lambda: self.client)

    async def sent_voice(self, **kwargs):
        self.audio.append((kwargs["voice"].name, kwargs["voice"].getvalue()))
        return self.message()

    async def sent_text(self, **kwargs):
        return self.message()

    async def test_voice_maps_full_chain_and_keyboard_and_removes_status(self):
        with patch.object(speech, "synthesize", AsyncMock(return_value=b"opus")), \
                patch.object(bot.roast, "is_multimodel_configured", return_value=True), \
                patch.object(bot, "_register_roast_option_messages") as register:
            last = await bot._deliver_roast(self.source, self.chain, self.context,
                self.status, model="model", prompt_chain=[], session_id="session")
        self.assertEqual(self.audio, [("reply.ogg", b"opus")])
        self.assertEqual(bot._roast_chains[f"1:{last.message_id}"], self.chain)
        kwargs = self.client.send_voice.await_args.kwargs
        self.assertEqual(kwargs["reply_parameters"].message_id, 10)
        self.assertEqual(kwargs["reply_markup"].inline_keyboard[0][0].callback_data, "vote")
        self.assertEqual(register.call_args.args[2], "Complete answer")
        self.client.delete_message.assert_awaited_once_with(chat_id=1, message_id=11)
        self.client.edit_message_text.assert_not_awaited()

    async def test_synthesis_failure_full_text_fallback(self):
        with patch.object(speech, "synthesize", AsyncMock(side_effect=RuntimeError("failed"))):
            last = await bot._deliver_roast(self.source, self.chain, self.context, self.status)
        self.client.send_voice.assert_not_awaited()
        text = self.client.edit_message_text.await_args.kwargs["text"]
        self.assertIn("Audio unavailable", text)
        self.assertIn("Complete answer", text)
        self.assertEqual(last.message_id, 11)
        self.assertEqual(bot._roast_chains["1:11"], self.chain)

    async def test_later_synthesis_failure_sends_no_audio(self):
        with patch.object(speech, "split_speech", return_value=["first", "second"]), \
                patch.object(speech, "synthesize", AsyncMock(side_effect=[b"opus", RuntimeError("failed")])):
            await bot._deliver_roast(self.source, self.chain, self.context, self.status)
        self.client.send_voice.assert_not_awaited()
        self.assertIn("Complete answer", self.client.edit_message_text.await_args.kwargs["text"])

    async def test_empty_voice_reply_falls_back(self):
        self.chain[-1]["content"] = ""
        with patch.object(speech, "synthesize", AsyncMock()) as synth:
            last = await bot._deliver_roast(self.source, self.chain, self.context, self.status)
        synth.assert_not_awaited()
        self.assertEqual(last.message_id, 11)
        self.assertIn("Audio unavailable", self.client.edit_message_text.await_args.kwargs["text"])

    async def test_privacy_error_first_and_later_chunks_preserves_metadata(self):
        for prefix in (False, True):
            with self.subTest(prefix=prefix):
                bot._roast_chains.clear()
                self.client.send_message.reset_mock()
                self.client.send_voice.side_effect = (
                    [self.message(), BadRequest(" Voice_messages_forbidden ")]
                    if prefix else [BadRequest("Voice_messages_forbidden")]
                )
                self.chain[-1]["content"] = "first second"
                with patch.object(speech, "split_speech", return_value=["first", "second"]), \
                        patch.object(speech, "synthesize", AsyncMock(return_value=b"opus")), \
                        patch.object(bot.roast, "is_multimodel_configured", return_value=True), \
                        patch.object(bot, "_register_roast_option_messages") as register:
                    last = await bot._deliver_roast(self.source, self.chain, self.context,
                        self.status, model="model", prompt_chain=[], session_id="session")
                kwargs = self.client.send_message.await_args.kwargs
                self.assertIn("Privacy and Security > Voice Messages", kwargs["text"])
                self.assertIn("second", kwargs["text"])
                self.assertEqual("first" in kwargs["text"], not prefix)
                self.assertEqual(kwargs["reply_markup"].inline_keyboard[0][0].callback_data, "vote")
                self.assertEqual(bot._roast_chains[f"1:{last.message_id}"], self.chain)
                self.assertEqual(register.call_args.args[2], "first second")
                self.assertEqual(len(register.call_args.args[0]), 2 if prefix else 1)

    async def test_unrelated_bad_request_keeps_generic_fallback(self):
        for prefix in (False, True):
            with self.subTest(prefix=prefix):
                error = BadRequest("Voice_messages_forbidden elsewhere")
                self.client.send_voice.side_effect = [self.message(), error] if prefix else [error]
                with patch.object(speech, "split_speech", return_value=["first", "second"]), \
                        patch.object(speech, "synthesize", AsyncMock(return_value=b"opus")):
                    await bot._deliver_roast(self.source, self.chain, self.context)
                text = self.client.send_message.await_args.kwargs["text"]
                self.assertIn("Audio unavailable", text)
                self.assertNotIn("Privacy", text)
                self.assertEqual("first" in text, not prefix)
                self.assertIn("second", text)

    async def test_voice_command_refresh_failure_still_confirms_and_invalid_skips(self):
        message = SimpleNamespace(chat_id=1, reply_text=AsyncMock())
        update = SimpleNamespace(effective_message=message)
        self.client.set_my_commands.side_effect = RuntimeError("menu failed")
        with patch.object(bot.logger, "exception") as log:
            await bot.handle_voice_mode(update, SimpleNamespace(args=["off"], bot=self.client))
        self.assertFalse(self.store.get_voice_mode(1))
        self.assertIn("disabled", message.reply_text.await_args.args[0])
        log.assert_called_once()
        self.client.set_my_commands.assert_awaited_once()
        await bot.handle_voice_mode(update, SimpleNamespace(args=["invalid"], bot=self.client))
        self.assertEqual(self.client.set_my_commands.await_count, 1)

    async def test_partial_send_falls_back_remaining_only(self):
        self.chain[-1]["content"] = "first part. second part."
        self.client.send_voice.side_effect = [self.message(), RuntimeError("send failed")]
        with patch.object(speech, "split_speech", return_value=["first part.", "second part."]), \
                patch.object(speech, "synthesize", AsyncMock(return_value=b"opus")) as synth:
            last = await bot._deliver_roast(self.source, self.chain, self.context, self.status)
        self.assertEqual(synth.await_count, 2)
        text = self.client.send_message.await_args.kwargs["text"]
        self.assertIn("second part.", text)
        self.assertNotIn("first part.", text)
        self.assertEqual(len(bot._roast_chains), 2)
        self.assertEqual(bot._roast_chains[f"1:{last.message_id}"], self.chain)

    async def test_prefix_survives_fallback_failure(self):
        first = self.message()
        self.client.send_voice.side_effect = [first, RuntimeError("voice failed")]
        self.client.send_message.side_effect = RuntimeError("text failed")
        with patch.object(speech, "split_speech", return_value=["first", "second"]), \
                patch.object(speech, "synthesize", AsyncMock(return_value=b"opus")), \
                patch.object(bot.roast, "is_multimodel_configured", return_value=True), \
                patch.object(bot, "_register_roast_option_messages") as register:
            with self.assertRaisesRegex(RuntimeError, "text failed"):
                await bot._deliver_roast(self.source, self.chain, self.context,
                    self.status, model="model", prompt_chain=[], session_id="session")
        self.assertEqual(bot._roast_chains[f"1:{first.message_id}"], self.chain)
        self.assertEqual(register.call_args.args[0], [first])

    async def test_multi_chunk_voice_reply_links_and_maps(self):
        with patch.object(speech, "split_speech", return_value=["first", "second"]), \
                patch.object(speech, "synthesize", AsyncMock(return_value=b"opus")):
            last = await bot._deliver_roast(self.source, self.chain, self.context)
        calls = self.client.send_voice.await_args_list
        self.assertEqual(calls[0].kwargs["reply_parameters"].message_id, 10)
        self.assertEqual(calls[1].kwargs["reply_parameters"].message_id, last.message_id - 1)
        self.assertEqual(len(bot._roast_chains), 2)
        self.assertTrue(all(chain == self.chain for chain in bot._roast_chains.values()))

    async def test_first_send_failure_and_status_cleanup_failure(self):
        self.client.send_voice.side_effect = RuntimeError("send failed")
        self.client.delete_message.side_effect = RuntimeError("gone")
        with patch.object(speech, "synthesize", AsyncMock(return_value=b"opus")):
            last = await bot._deliver_roast(self.source, self.chain, self.context, self.status)
        self.assertIn("Complete answer", self.client.send_message.await_args.kwargs["text"])
        self.assertIn(f"1:{last.message_id}", bot._roast_chains)

    async def test_command_toggle_args_and_mode_isolation(self):
        message = SimpleNamespace(chat_id=1, reply_text=AsyncMock())
        update = SimpleNamespace(effective_message=message)
        for args, expected in [([], False), (["on"], True), (["ON"], True), (["bad"], True), (["off", "on"], True), (["off"], False)]:
            await bot.handle_voice_mode(update, SimpleNamespace(args=args, bot=self.client))
            self.assertEqual(self.store.get_voice_mode(1), expected)
        self.assertEqual(self.client.set_my_commands.await_count, 4)
        self.assertEqual(self.client.set_my_commands.await_args.kwargs["scope"].chat_id, 1)
        self.assertIn("voice", [c.command for c in self.client.set_my_commands.await_args.args[0]])
        self.assertEqual(self.store.get_mode(1), "diary")
        self.assertIn("voice", dict(bot.COMMANDS))

    async def test_chat_text_runs_real_roast_and_voice_delivery(self):
        source = SimpleNamespace(chat_id=1, message_id=10, text="Hello", get_bot=lambda: self.client)
        update = SimpleNamespace(effective_message=source)
        def create_task(coroutine):
            coroutine.close()
        self.context.application = SimpleNamespace(create_task=create_task)
        with patch.object(bot.roast, "is_configured", return_value=True), \
                patch.object(bot, "_sync_memory", AsyncMock()), \
                patch.object(bot.roast, "roast", AsyncMock(return_value=SimpleNamespace(text="Answer", rules_ops=[]))), \
                patch.object(speech, "synthesize", AsyncMock(return_value=b"opus")):
            await bot._handle_chat_mode_text(update, self.context)
        self.client.send_voice.assert_awaited_once()
        self.assertEqual(bot._chat_mode_chains[1][-1], {"role": "assistant", "content": "Answer"})

    def test_old_state_reload_and_chat_isolation(self):
        path = Path(self.temp.name) / "old.json"
        path.write_text('{"version":1}')
        store = StateStore(path)
        self.assertFalse(store.get_voice_mode(1))
        store.set_voice_mode(1, True)
        store.set_mode(1, "chat")
        reloaded = StateStore(path)
        self.assertTrue(reloaded.get_voice_mode(1))
        self.assertFalse(reloaded.get_voice_mode(2))
        reloaded.set_mode(1, "diary")
        self.assertTrue(reloaded.get_voice_mode(1))
