import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services import memory
from services.memory import MemoryItem
from services.i18n import DEFAULT_LANGUAGE, normalize_language


STATE_PATH = Path(os.getenv("BOT_STATE_PATH", ".data/message_state.json"))
MAX_RETAINED_MESSAGES = 200
# State sections mirrored to a Notion memory page.
PROFILE_SECTION = "profile"
RULES_SECTION = "rules"
UNPROCESSED_STATUSES = {"received", "processing", "failed"}
VOICE_DUPLICATE_STATUSES = {"drafted", "saved"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateStore:
    def __init__(self, path: Path = STATE_PATH) -> None:
        self.path = path
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "version": 1,
                "messages": {},
                "drafts": {},
                "profile": {"points": [], "notion_mirror": []},
                "rules": {"items": [], "notion_mirror": []},
                "settings": {"language": DEFAULT_LANGUAGE},
            }
        with self.path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("version", 1)
        data.setdefault("messages", {})
        data.setdefault("drafts", {})
        data.setdefault("profile", {})
        data["profile"].setdefault("points", [])
        data["profile"].setdefault("notion_mirror", [])
        data.setdefault("rules", {})
        data["rules"].setdefault("items", [])
        data["rules"].setdefault("notion_mirror", [])
        data.setdefault("settings", {})
        if data["settings"].get("language"):
            data["settings"]["language"] = normalize_language(data["settings"].get("language"))
        return data

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        tmp_path.replace(self.path)

    def _prune_messages(self) -> None:
        messages = self.data["messages"]
        if len(messages) <= MAX_RETAINED_MESSAGES:
            return
        ordered = sorted(
            messages.items(),
            key=lambda item: (item[1].get("date") or "", item[1].get("message_id") or 0),
            reverse=True,
        )
        keep = {key for key, _ in ordered[:MAX_RETAINED_MESSAGES]}
        self.data["messages"] = {key: value for key, value in messages.items() if key in keep}

    def message_key(self, chat_id: int, message_id: int) -> str:
        return f"{chat_id}:{message_id}"

    def record_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        date: str | None,
        source_message_url: str | None = None,
        language: str | None = None,
    ) -> str:
        return self._record_message(
            chat_id,
            message_id,
            "text",
            {"text": text, "source_message_url": source_message_url, "language": normalize_language(language)},
            date,
        )

    def record_voice(
        self,
        chat_id: int,
        message_id: int,
        file_id: str,
        date: str | None,
        file_unique_id: str | None = None,
        duration: int | None = None,
        file_size: int | None = None,
        source_message_url: str | None = None,
        language: str | None = None,
    ) -> str:
        payload = {
            "file_id": file_id,
            "file_unique_id": file_unique_id,
            "duration": duration,
            "file_size": file_size,
            "source_message_url": source_message_url,
            "language": normalize_language(language),
        }
        return self._record_message(chat_id, message_id, "voice", payload, date)

    def _record_message(
        self,
        chat_id: int,
        message_id: int,
        kind: str,
        payload: dict[str, Any],
        date: str | None,
    ) -> str:
        key = self.message_key(chat_id, message_id)
        messages = self.data["messages"]
        if key in messages:
            return key
        messages[key] = {
            "key": key,
            "chat_id": chat_id,
            "message_id": message_id,
            "kind": kind,
            "status": "received",
            "date": date or _now(),
            "created_at": _now(),
            "updated_at": _now(),
            **payload,
        }
        self._prune_messages()
        self._save()
        return key

    def get_message(self, key: str) -> dict[str, Any] | None:
        message = self.data["messages"].get(key)
        return deepcopy(message) if message else None

    def mark_message_processing(self, key: str) -> None:
        self._update_message(key, {"status": "processing", "error": None})

    def mark_message_drafted(self, key: str, entry_id: str) -> None:
        self._update_message(key, {"status": "drafted", "entry_id": entry_id, "error": None})

    def mark_message_duplicate_pending(self, key: str, duplicate_key: str) -> None:
        self._update_message(key, {
            "status": "duplicate_pending",
            "duplicate_of": duplicate_key,
            "error": None,
        })

    def mark_message_duplicate_confirmed(self, key: str) -> None:
        self._update_message(key, {"status": "received", "allow_duplicate": True, "error": None})

    def mark_message_saved(self, key: str | None) -> None:
        if key:
            self._update_message(key, {"status": "saved", "error": None})

    def mark_message_cancelled(self, key: str | None) -> None:
        if key:
            self._update_message(key, {"status": "cancelled", "error": None})

    def mark_message_failed(self, key: str, error: str) -> None:
        self._update_message(key, {"status": "failed", "error": error})

    def _update_message(self, key: str, updates: dict[str, Any]) -> None:
        message = self.data["messages"].get(key)
        if not message:
            return
        message.update(updates)
        message["updated_at"] = _now()
        self._save()

    def recent_unprocessed_messages(self, limit: int) -> list[dict[str, Any]]:
        messages = [
            message
            for message in self.data["messages"].values()
            if message.get("status") in UNPROCESSED_STATUSES
        ]
        messages.sort(
            key=lambda message: (message.get("date") or "", message.get("message_id") or 0),
            reverse=True,
        )
        return [deepcopy(message) for message in reversed(messages[:limit])]

    def find_duplicate_voice(
        self,
        file_unique_id: str | None,
        duration: int | None = None,
        file_size: int | None = None,
        exclude_key: str | None = None,
    ) -> dict[str, Any] | None:
        if not file_unique_id:
            return None

        matches = []
        for key, message in self.data["messages"].items():
            if key == exclude_key:
                continue
            if message.get("kind") != "voice":
                continue
            if message.get("status") not in VOICE_DUPLICATE_STATUSES:
                continue
            if message.get("file_unique_id") != file_unique_id:
                continue
            if not self._voice_fact_matches(message, "duration", duration):
                continue
            if not self._voice_fact_matches(message, "file_size", file_size):
                continue
            matches.append(message)

        if not matches:
            return None

        matches.sort(
            key=lambda message: (message.get("updated_at") or "", message.get("message_id") or 0),
            reverse=True,
        )
        return deepcopy(matches[0])

    def _voice_fact_matches(self, message: dict[str, Any], field: str, value: int | None) -> bool:
        stored = message.get(field)
        if stored is None or value is None:
            return True
        return int(stored) == int(value)

    def get_profile_points(self) -> list[MemoryItem]:
        """Durable facts about the author, each with the id the model addresses."""
        return memory.load(self.data["profile"].get("points", []))

    def set_profile_points(self, points: list[MemoryItem]) -> None:
        # No mechanical cap — the list size is guided at the prompt level.
        self.data["profile"] = {
            "points": memory.dump(points),
            "notion_mirror": self.data["profile"].get("notion_mirror", []),
            "updated_at": _now(),
        }
        self._save()

    def get_rules(self) -> list[MemoryItem]:
        """Standing behavior rules the author dictated to the bot."""
        return memory.load(self.data["rules"].get("items", []))

    def set_rules(self, rules: list[MemoryItem]) -> None:
        # Callers only write when the list actually changed — an unchanged list
        # never touches disk.
        self.data["rules"] = {
            "items": memory.dump(rules),
            "notion_mirror": self.data["rules"].get("notion_mirror", []),
            "updated_at": _now(),
        }
        self._save()

    def get_notion_mirror(self, section: str) -> list[str]:
        """What the section's Notion page listed at the last successful sync.

        A page that no longer lists exactly this was edited by hand, which is how
        the bot tells a manual Notion edit from its own last write."""
        return list(self.data[section].get("notion_mirror", []))

    def set_notion_mirror(self, section: str, items: list[str]) -> None:
        if self.data[section].get("notion_mirror") == items:
            return
        self.data[section]["notion_mirror"] = list(items)
        self._save()

    def get_language(self) -> str:
        return normalize_language(self.data.get("settings", {}).get("language"))

    def get_saved_language(self) -> str | None:
        language = self.data.get("settings", {}).get("language")
        return normalize_language(language) if language else None

    def set_language(self, language: str) -> None:
        normalized = normalize_language(language)
        self.data.setdefault("settings", {})["language"] = normalized
        self.data["settings"]["updated_at"] = _now()
        self._save()

    def save_draft(self, draft: dict[str, Any]) -> None:
        stored = deepcopy(draft)
        stored["updated_at"] = _now()
        stored.setdefault("created_at", _now())
        self.data["drafts"][stored["id"]] = stored
        self._save()

    def get_draft(self, entry_id: str) -> dict[str, Any] | None:
        draft = self.data["drafts"].get(entry_id)
        return deepcopy(draft) if draft else None

    def remove_draft(self, entry_id: str) -> None:
        self.data["drafts"].pop(entry_id, None)
        self._save()


state_store = StateStore()
