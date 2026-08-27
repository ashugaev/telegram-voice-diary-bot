import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("NOTION_TOKEN", "test-notion-token")
os.environ.setdefault("NOTION_DATABASE_ID", "test-notion-db")
os.environ.setdefault("ALLOWED_USER_ID", "1")

from services import memory
from services import state_store as state_store_module
from services.state_store import PROFILE_SECTION, RULES_SECTION, StateStore


class StateStoreTests(unittest.TestCase):
    def test_records_messages_statuses_and_drafts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(Path(tmpdir) / "state.json")

            key = store.record_voice(
                123,
                10,
                "file-1",
                "2026-06-04T10:00:00+00:00",
                file_unique_id="voice-unique",
                duration=42,
                file_size=1000,
                source_message_url="tg://openmessage?user_id=123&message_id=10",
            )
            duplicate_key = store.record_voice(123, 10, "file-2", None)
            store.mark_message_processing(key)
            store.mark_message_drafted(key, "entry-1")
            store.save_draft({"id": "entry-1", "title": "Title", "tags": ["work"]})

            self.assertEqual(key, "123:10")
            self.assertEqual(duplicate_key, key)
            message = store.get_message(key)
            self.assertEqual(message["file_id"], "file-1")
            self.assertEqual(message["file_unique_id"], "voice-unique")
            self.assertEqual(message["duration"], 42)
            self.assertEqual(message["file_size"], 1000)
            self.assertEqual(message["source_message_url"], "tg://openmessage?user_id=123&message_id=10")
            self.assertEqual(message["status"], "drafted")
            self.assertEqual(message["entry_id"], "entry-1")

            draft = store.get_draft("entry-1")
            draft["title"] = "Changed"
            self.assertEqual(store.get_draft("entry-1")["title"], "Title")

            store.mark_message_saved(key)
            self.assertEqual(store.get_message(key)["status"], "saved")

            store.mark_message_cancelled(key)
            self.assertEqual(store.get_message(key)["status"], "cancelled")
            store.remove_draft("entry-1")
            self.assertIsNone(store.get_draft("entry-1"))

    def test_profile_points_carry_ids_persist_and_never_cap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            store = StateStore(path)
            self.assertEqual(store.get_profile_points(), [])

            store.set_profile_points(memory.load(["  likes hiking ", "", "avoids conflict"]))
            stored = store.get_profile_points()
            self.assertEqual(memory.texts(stored), ["likes hiking", "avoids conflict"])

            # Ids persist with the text, so the model can address a fact next time.
            self.assertEqual(StateStore(path).get_profile_points(), stored)

            store.set_profile_points(memory.load([f"fact {i}" for i in range(150)]))
            self.assertEqual(len(store.get_profile_points()), 150)  # no mechanical cap on list size

    def test_rules_carry_ids_and_persist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            store = StateStore(path)
            self.assertEqual(store.get_rules(), [])

            store.set_rules(memory.load(["  не задавай вопросов ", "", "пиши коротко"]))
            stored = store.get_rules()
            self.assertEqual(memory.texts(stored), ["не задавай вопросов", "пиши коротко"])
            self.assertEqual(StateStore(path).get_rules(), stored)

    def test_notion_mirror_persists_and_survives_a_local_rewrite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            store = StateStore(path)
            self.assertEqual(store.get_notion_mirror(RULES_SECTION), [])

            store.set_notion_mirror(RULES_SECTION, ["пиши коротко"])
            self.assertEqual(StateStore(path).get_notion_mirror(RULES_SECTION), ["пиши коротко"])

            # Writing the rules must not drop what the Notion page is known to list,
            # otherwise the next sync reads a hand edit into every stale page.
            store.set_rules(memory.load(["пиши коротко", "не задавай вопросов"]))
            self.assertEqual(store.get_notion_mirror(RULES_SECTION), ["пиши коротко"])

            store.set_profile_points(memory.load(["likes hiking"]))
            self.assertEqual(store.get_notion_mirror(PROFILE_SECTION), [])

    def test_state_written_before_rules_existed_still_loads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            path.write_text(
                json.dumps({"version": 1, "messages": {}, "drafts": {}, "profile": {"points": ["old"]}}),
                encoding="utf-8",
            )
            store = StateStore(path)

            self.assertEqual(store.get_rules(), [])
            # A profile stored as plain strings gets ids on read, nothing is lost.
            self.assertEqual(store.get_profile_points(), [memory.MemoryItem("1", "old")])

    def test_language_persists_and_legacy_state_has_no_saved_language(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            path.write_text(json.dumps({"version": 1, "messages": {}, "drafts": {}}), encoding="utf-8")
            store = StateStore(path)

            self.assertIsNone(store.get_saved_language())
            self.assertEqual(store.get_language(), "en")

            store.set_language("ru-RU")
            self.assertEqual(StateStore(path).get_saved_language(), "ru")

    def test_recent_unprocessed_messages_returns_oldest_to_newest_within_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(Path(tmpdir) / "state.json")
            old_key = store.record_text(123, 1, "old", "2026-06-01T10:00:00+00:00")
            newest_key = store.record_text(123, 3, "newest", "2026-06-03T10:00:00+00:00")
            middle_key = store.record_text(123, 2, "middle", "2026-06-02T10:00:00+00:00")
            store.mark_message_saved(old_key)

            recent = store.recent_unprocessed_messages(limit=2)

            self.assertEqual([message["key"] for message in recent], [middle_key, newest_key])

    def test_prunes_old_messages_when_limit_is_exceeded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_limit = state_store_module.MAX_RETAINED_MESSAGES
            state_store_module.MAX_RETAINED_MESSAGES = 2
            try:
                store = StateStore(Path(tmpdir) / "state.json")
                store.record_text(123, 1, "one", "2026-06-01T10:00:00+00:00")
                store.record_text(123, 2, "two", "2026-06-02T10:00:00+00:00")
                store.record_text(123, 3, "three", "2026-06-03T10:00:00+00:00")
            finally:
                state_store_module.MAX_RETAINED_MESSAGES = original_limit

            self.assertIsNone(store.get_message("123:1"))
            self.assertIsNotNone(store.get_message("123:2"))
            self.assertIsNotNone(store.get_message("123:3"))

    def test_finds_saved_voice_duplicate_by_stable_file_facts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(Path(tmpdir) / "state.json")
            original_key = store.record_voice(
                123,
                10,
                "file-1",
                "2026-06-04T10:00:00+00:00",
                file_unique_id="voice-unique",
                duration=42,
                file_size=1000,
            )
            duplicate_key = store.record_voice(
                123,
                11,
                "file-2",
                "2026-06-04T10:05:00+00:00",
                file_unique_id="voice-unique",
                duration=42,
                file_size=1000,
            )
            store.mark_message_saved(original_key)

            duplicate = store.find_duplicate_voice(
                "voice-unique",
                duration=42,
                file_size=1000,
                exclude_key=duplicate_key,
            )

            self.assertEqual(duplicate["key"], original_key)

    def test_duplicate_pending_messages_are_not_replayed_until_confirmed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(Path(tmpdir) / "state.json")
            key = store.record_voice(
                123,
                10,
                "file-1",
                "2026-06-04T10:00:00+00:00",
                file_unique_id="voice-unique",
            )
            store.mark_message_duplicate_pending(key, "123:9")

            self.assertEqual(store.recent_unprocessed_messages(limit=10), [])
            store.mark_message_duplicate_confirmed(key)

            self.assertEqual([message["key"] for message in store.recent_unprocessed_messages(limit=10)], [key])
            self.assertTrue(store.get_message(key)["allow_duplicate"])
