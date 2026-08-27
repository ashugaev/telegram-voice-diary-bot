import asyncio
import hashlib
import logging
import os
import tempfile
import uuid
import zoneinfo
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from html import escape
from time import monotonic
from types import SimpleNamespace
from typing import Any

from telegram import BotCommand, BotCommandScopeChat, ForceReply, ReplyParameters, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    Defaults,
    MessageHandler,
    filters,
)

from config import settings
from services import memory, notion_memory, profile_rebuild, roast
from services.diary_dates import diary_today
from services.formatter import format_entry
from services.i18n import LANGUAGE_NAMES, SUPPORTED_LANGUAGES, normalize_language, t
from services.notion import save_entry
from services.state_store import PROFILE_SECTION, RULES_SECTION, state_store
from services.stats import build_audio_stats, format_audio_stats
from services.summary import generate_daily_summary, generate_weekly_report
from services.whisper import transcribe

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

DRAFTS_KEY = "drafts"
EDIT_PROMPTS_KEY = "edit_prompts"
MEMORY_PROMPTS_KEY = "memory_prompts"
MEMORY_REQUESTS_KEY = "memory_requests"
MAX_CONCURRENT_UPDATES = 1024
STARTUP_REPLAY_LIMIT = 10
DATE_PICKER_DAYS = 7
TELEGRAM_MESSAGE_LIMIT = 4096
SOURCE_DEEPLINK_PREFIX = "src_"
ROAST_CHAINS_LIMIT = 50
# Focus replies that mean "no extra focus, just rebuild".
MEMORY_SKIP_FOCUS_TOKENS = {"-", "--", "—", "skip", "no", "none"}
# Refresh the progress message every N notes: a full pass can be hundreds of
# notes, and one edit per note would hit Telegram's rate limit.
MEMORY_PROGRESS_EVERY = 5
# How long a roast may reuse the last pull from the Notion memory pages.
MEMORY_PULL_TTL_SECONDS = 60

# One note covers everything the bot just learned: facts about the author and
# rules it was taught. Both memories change on their own occasions, so a note
# carries whichever blocks moved and is never sent empty.
MEMORY_NOTE_HEADER = "memory.updated"
PROFILE_BLOCK_LABEL = "memory.about"
RULES_BLOCK_LABEL = "memory.rules"

# Memory is read-modify-written from a roast, a background profile extraction and
# startup, against both local state and Notion. One lock covers all of it, so
# only one of them touches memory at a time. Never held across a model call.
_memory_lock = asyncio.Lock()
# None until the first pull. `monotonic()` counts from boot, so a numeric zero
# would read as "pulled just now" on a freshly booted host and skip that pull.
_last_memory_pull: float | None = None

# In-memory (RAM-only) roast conversations, keyed by "chat_id:message_id" of each
# bot roast message. Replying to one of those messages continues that conversation.
# Intentionally not persisted: chains are discarded on restart.
_roast_chains: dict[str, list[dict]] = {}


@dataclass(frozen=True)
class PreviewRender:
    text: str
    page: int = 0
    page_count: int = 1
    truncated: bool = False

# Single source of truth for /help and the Telegram command menu. Keep in sync
# with the CommandHandler list in main() (guarded by a test).
COMMANDS: tuple[tuple[str, str], ...] = (
    ("start", "cmd.start"),
    ("help", "cmd.help"),
    ("weekly", "cmd.weekly"),
    ("stat", "cmd.stat"),
    ("memory", "cmd.memory"),
    ("rules", "cmd.rules"),
    ("language", "cmd.language"),
)

def _command_lines(language: str) -> str:
    return "\n".join(f"/{name} — {t(description, language)}" for name, description in COMMANDS)


def _help_text(language: str) -> str:
    return t("help", language, commands=_command_lines(language))


def _message_language(message=None, update: Update | None = None) -> str:
    stored = state_store.get_saved_language()
    if stored:
        return stored
    user = getattr(update, "effective_user", None) if update else None
    if user is None and message is not None:
        user = getattr(message, "from_user", None)
    return normalize_language(getattr(user, "language_code", None))


def _tags_html(tags: list[str]) -> str:
    all_tags = ["Daily"] + [t for t in tags if t != "Daily"]
    return " ".join(f"<code>{escape(t)}</code>" for t in all_tags)


def _local_today() -> date:
    return diary_today()


def _entry_date_options() -> list[str]:
    today = _local_today()
    return [(today - timedelta(days=offset)).isoformat() for offset in range(DATE_PICKER_DAYS)]


def _default_entry_date() -> str:
    return _entry_date_options()[0]


def _normalize_entry_date(entry_date: str | None) -> str:
    options = _entry_date_options()
    return entry_date if entry_date in options else options[0]


def _entry_date_label(entry_date: str | None, language: str | None = None) -> str:
    normalized = _normalize_entry_date(entry_date)
    entry_day = date.fromisoformat(normalized)
    today = _local_today()
    if entry_day == today:
        return t("date.today", language, date=normalized)
    if entry_day == today - timedelta(days=1):
        return t("date.yesterday", language, date=normalized)
    return normalized


def _compose_preview_text(
    title: str,
    escaped_text: str,
    tags: list[str],
    entry_date: str | None = None,
    language: str | None = None,
) -> str:
    parts = [
        f"<b>{escape(title)}</b>",
        escaped_text,
    ]
    if entry_date:
        parts.append(t("preview.date", language, date=escape(_entry_date_label(entry_date, language))))
    parts.append(
        _tags_html(tags),
    )
    return "\n\n".join(parts)


def _preview_truncation_notice(page: int, page_count: int, language: str | None = None) -> str:
    return t("preview.truncated", language, page=page + 1, page_count=page_count)


def _preview_page_candidate(
    title: str,
    text: str,
    tags: list[str],
    entry_date: str | None,
    start: int,
    text_length: int,
    page: int,
    page_count: int,
    language: str | None = None,
) -> str:
    page_text = escape(text[start:start + text_length]) + _preview_truncation_notice(page, page_count, language)
    return _compose_preview_text(title, page_text, tags, entry_date, language)


def _fit_preview_page_length(
    title: str,
    text: str,
    tags: list[str],
    entry_date: str | None,
    start: int,
    page: int,
    page_count: int,
    language: str | None = None,
) -> int:
    low = 0
    high = len(text) - start
    best = -1
    while low <= high:
        mid = (low + high) // 2
        candidate = _preview_page_candidate(title, text, tags, entry_date, start, mid, page, page_count, language)
        if len(candidate) <= TELEGRAM_MESSAGE_LIMIT:
            best = mid
            low = mid + 1
        else:
            high = mid - 1
    return best


def _preview_page_slices(
    title: str,
    text: str,
    tags: list[str],
    entry_date: str | None,
    page_count_hint: int,
    language: str | None = None,
) -> list[tuple[int, int]]:
    slices = []
    start = 0
    while start < len(text):
        text_length = _fit_preview_page_length(
            title,
            text,
            tags,
            entry_date,
            start,
            len(slices),
            page_count_hint,
            language,
        )
        if text_length <= 0:
            return []
        slices.append((start, text_length))
        start += text_length
    return slices


def _fallback_preview_text(title: str, entry_date: str | None, language: str | None = None) -> str:
    fallback = _compose_preview_text(
        title[:256],
        t("preview.fallback", language),
        [],
        entry_date,
        language,
    )
    return fallback[:TELEGRAM_MESSAGE_LIMIT]


def _render_preview(
    title: str,
    text: str,
    tags: list[str],
    entry_date: str | None = None,
    page: int = 0,
    language: str | None = None,
) -> PreviewRender:
    preview = _compose_preview_text(title, escape(text), tags, entry_date, language)
    if len(preview) <= TELEGRAM_MESSAGE_LIMIT:
        return PreviewRender(preview)

    page_count_hint = 1
    page_slices = []
    for _ in range(10):
        page_slices = _preview_page_slices(title, text, tags, entry_date, page_count_hint, language)
        if not page_slices:
            return PreviewRender(
                _fallback_preview_text(title, entry_date, language),
                page=0,
                page_count=1,
                truncated=True,
            )
        if len(page_slices) == page_count_hint:
            break
        page_count_hint = len(page_slices)

    page_count = len(page_slices)
    normalized_page = min(max(page, 0), page_count - 1)
    start, text_length = page_slices[normalized_page]
    page_text = _preview_page_candidate(
        title,
        text,
        tags,
        entry_date,
        start,
        text_length,
        normalized_page,
        page_count,
        language,
    )
    if len(page_text) > TELEGRAM_MESSAGE_LIMIT:
        return PreviewRender(
            _fallback_preview_text(title, entry_date, language),
            page=0,
            page_count=1,
            truncated=True,
        )
    return PreviewRender(page_text, page=normalized_page, page_count=page_count, truncated=True)


def _preview_text(
    title: str,
    text: str,
    tags: list[str],
    entry_date: str | None = None,
    page: int = 0,
    language: str | None = None,
) -> str:
    return _render_preview(title, text, tags, entry_date, page, language).text


def _preview_msg_id(draft: dict) -> int:
    return draft.get("preview_msg_id") or draft.get("title_msg_id") or draft["buttons_msg_id"]


def _new_entry_id() -> str:
    return uuid.uuid4().hex[:12]


def _drafts(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.user_data.setdefault(DRAFTS_KEY, {})


def _edit_prompts(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.user_data.setdefault(EDIT_PROMPTS_KEY, {})


def _memory_prompts(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.user_data.setdefault(MEMORY_PROMPTS_KEY, {})


def _memory_requests(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.user_data.setdefault(MEMORY_REQUESTS_KEY, {})


def _prompt_key(chat_id: int, message_id: int) -> str:
    return f"{chat_id}:{message_id}"


def _message_date(message) -> str | None:
    date = getattr(message, "date", None)
    if isinstance(date, datetime):
        return date.isoformat()
    return None


def _source_deeplink_payload(chat_id: int, message_id: int) -> str:
    return f"{SOURCE_DEEPLINK_PREFIX}{chat_id}_{message_id}"


def _parse_source_deeplink_payload(payload: str | None) -> tuple[int, int] | None:
    if not payload or not payload.startswith(SOURCE_DEEPLINK_PREFIX):
        return None
    raw_ids = payload.removeprefix(SOURCE_DEEPLINK_PREFIX)
    try:
        chat_id, message_id = raw_ids.split("_", 1)
        return int(chat_id), int(message_id)
    except ValueError:
        return None


def _clean_bot_username(username: str | None) -> str | None:
    if not username:
        return None
    return username.removeprefix("@")


def _bot_username(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    try:
        return _clean_bot_username(getattr(context.bot, "username", None))
    except (AttributeError, RuntimeError):
        return None


def _bot_source_deeplink(bot_username: str | None, chat_id: int, message_id: int) -> str | None:
    username = _clean_bot_username(bot_username)
    if not username:
        return None
    return f"https://t.me/{username}?start={_source_deeplink_payload(chat_id, message_id)}"


def _telegram_message_url_from_ids(
    chat_id: int | None,
    message_id: int | None,
    bot_username: str | None = None,
) -> str | None:
    if chat_id is None or message_id is None:
        return None

    chat_id = int(chat_id)
    message_id = int(message_id)
    if chat_id > 0:
        bot_deeplink = _bot_source_deeplink(bot_username, chat_id, message_id)
        if bot_deeplink:
            return bot_deeplink
        return f"tg://openmessage?user_id={chat_id}&message_id={message_id}"
    if str(chat_id).startswith("-100"):
        return f"https://t.me/c/{str(chat_id)[4:]}/{message_id}"
    bot_deeplink = _bot_source_deeplink(bot_username, chat_id, message_id)
    if bot_deeplink:
        return bot_deeplink
    return f"tg://openmessage?chat_id={chat_id}&message_id={message_id}"


def _telegram_message_url(message, bot_username: str | None = None) -> str | None:
    message_link = getattr(message, "link", None)
    if message_link:
        return message_link
    return _telegram_message_url_from_ids(
        getattr(message, "chat_id", None),
        getattr(message, "message_id", None),
        bot_username=bot_username,
    )


def _clickable_source_message_url(
    chat_id: int | None,
    message_id: int | None,
    stored_url: str | None = None,
    bot_username: str | None = None,
) -> str | None:
    if stored_url and not stored_url.startswith("tg://"):
        return stored_url
    generated_url = _telegram_message_url_from_ids(chat_id, message_id, bot_username=bot_username)
    return generated_url or stored_url


def _source_text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _entry_metadata(
    record: dict | None,
    source_text: str,
    bot_username: str | None = None,
) -> dict:
    if not record:
        return {}

    metadata = {
        "source": record.get("kind"),
        "telegram_chat_id": record.get("chat_id"),
        "telegram_message_id": record.get("message_id"),
        "source_message_url": _clickable_source_message_url(
            record.get("chat_id"),
            record.get("message_id"),
            stored_url=record.get("source_message_url"),
            bot_username=bot_username,
        ),
    }
    if record.get("kind") == "voice":
        metadata.update({
            "voice_file_unique_id": record.get("file_unique_id"),
            "audio_duration": record.get("duration"),
            "audio_file_size": record.get("file_size"),
        })
    elif record.get("kind") == "text":
        metadata["source_text_hash"] = _source_text_hash(source_text)
    return {key: value for key, value in metadata.items() if value is not None}


def _get_draft(context: ContextTypes.DEFAULT_TYPE, entry_id: str) -> dict[str, Any] | None:
    draft = _drafts(context).get(entry_id)
    if draft:
        draft.setdefault("entry_date", _default_entry_date())
        return draft

    draft = state_store.get_draft(entry_id)
    if draft:
        draft.setdefault("entry_date", _default_entry_date())
        _drafts(context)[entry_id] = draft
    return draft


def _preview_keyboard(
    entry_id: str,
    highlighted: bool = False,
    entry_date: str | None = None,
    show_format: bool = False,
    show_original: bool = False,
    show_pagination: bool = False,
    preview_page: int = 0,
    page_count: int = 1,
    language: str | None = None,
) -> InlineKeyboardMarkup:
    highlight_btn = (
        InlineKeyboardButton(t("button.highlighted", language), callback_data=f"toggle_highlight:{entry_id}")
        if highlighted else
        InlineKeyboardButton(t("button.mark_highlight", language), callback_data=f"toggle_highlight:{entry_id}")
    )
    rows = []
    if show_pagination and page_count > 1:
        previous_page = max(preview_page - 1, 0)
        next_page = min(preview_page + 1, page_count - 1)
        rows.append([
            InlineKeyboardButton("←", callback_data=f"preview_page:{entry_id}:{previous_page}"),
            InlineKeyboardButton("→", callback_data=f"preview_page:{entry_id}:{next_page}"),
        ])
    rows.append(
        [
            InlineKeyboardButton(t("button.title", language), callback_data=f"edit_title:{entry_id}"),
            InlineKeyboardButton(t("button.text", language), callback_data=f"edit_text:{entry_id}"),
            InlineKeyboardButton(t("button.tags", language), callback_data=f"edit_tags:{entry_id}"),
        ],
    )
    if show_format:
        rows.append([InlineKeyboardButton(t("button.format", language), callback_data=f"format:{entry_id}")])
    elif show_original:
        rows.append([InlineKeyboardButton(t("button.original", language), callback_data=f"unformat:{entry_id}")])
    rows.append([InlineKeyboardButton(t("button.date", language, date=_entry_date_label(entry_date, language)), callback_data=f"pick_date:{entry_id}")])
    rows.append([highlight_btn])
    if roast.is_configured():
        rows.append([InlineKeyboardButton(t("button.roast", language), callback_data=f"roast:{entry_id}")])
    rows.append([InlineKeyboardButton(t("button.save", language), callback_data=f"save:{entry_id}")])
    rows.append([InlineKeyboardButton(t("button.cancel", language), callback_data=f"cancel:{entry_id}")])
    return InlineKeyboardMarkup(rows)


def _date_picker_keyboard(entry_id: str, selected_date: str | None = None, language: str | None = None) -> InlineKeyboardMarkup:
    normalized = _normalize_entry_date(selected_date)
    rows = []
    for entry_date in _entry_date_options():
        prefix = "✓ " if entry_date == normalized else ""
        rows.append([
            InlineKeyboardButton(
                f"{prefix}{_entry_date_label(entry_date, language)}",
                callback_data=f"set_date:{entry_id}:{entry_date}",
            )
        ])
    rows.append([InlineKeyboardButton(t("button.back_preview", language), callback_data=f"back_to_preview:{entry_id}")])
    rows.append([InlineKeyboardButton(t("button.cancel_draft", language), callback_data=f"cancel:{entry_id}")])
    return InlineKeyboardMarkup(rows)


def _duplicate_voice_keyboard(message_key: str, language: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("button.add_anyway", language), callback_data=f"add_duplicate:{message_key}")],
        [InlineKeyboardButton(t("button.cancel", language), callback_data=f"cancel_duplicate:{message_key}")],
    ])


def _duplicate_save_keyboard(entry_id: str, language: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("button.add_anyway", language), callback_data=f"save_anyway:{entry_id}")],
        [InlineKeyboardButton(t("button.cancel", language), callback_data=f"cancel:{entry_id}")],
    ])


def _retry_processing_keyboard(message_key: str, language: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("button.retry", language), callback_data=f"retry_process:{message_key}")],
    ])


def _duplicate_warning_text(metadata: dict | None, language: str | None = None) -> str:
    if metadata and metadata.get("source") == "voice":
        return t("duplicate.voice", language)
    return t("duplicate.entry", language)


def _draft_highlighted(draft: dict) -> bool:
    return draft["title"].startswith("⭐ ")


def _draft_preview_page(draft: dict) -> int:
    try:
        return max(0, int(draft.get("preview_page", 0)))
    except (TypeError, ValueError):
        return 0


def _render_preview_for_draft(draft: dict) -> PreviewRender:
    return _render_preview(
        draft["title"],
        draft["text"],
        draft["tags"],
        draft.get("entry_date"),
        _draft_preview_page(draft),
        draft.get("language"),
    )


def _can_show_format(formatted_text: str | None, formatted: bool = False) -> bool:
    return bool(formatted_text) and not formatted


def _preview_keyboard_for_draft(draft: dict, preview: PreviewRender | None = None) -> InlineKeyboardMarkup:
    preview = preview or _render_preview_for_draft(draft)
    return _preview_keyboard(
        draft["id"],
        highlighted=_draft_highlighted(draft),
        entry_date=draft.get("entry_date"),
        show_format=_can_show_format(draft.get("formatted_text"), bool(draft.get("formatted"))),
        show_original=bool(draft.get("formatted")),
        show_pagination=preview.truncated,
        preview_page=preview.page,
        page_count=preview.page_count,
        language=draft.get("language"),
    )


def _message_chat_id(message) -> int:
    chat_id = getattr(message, "chat_id", None)
    if chat_id is not None:
        return chat_id
    return message.chat.id


async def _edit_reply_message(
    context: ContextTypes.DEFAULT_TYPE,
    message,
    text: str,
    **kwargs,
):
    return await context.bot.edit_message_text(
        chat_id=_message_chat_id(message),
        message_id=message.message_id,
        text=text,
        **kwargs,
    )


class StoredMessageRef:
    def __init__(self, bot, chat_id: int, message_id: int) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.message_id = message_id


async def _reply_to_source(message_ref, text: str, **kwargs):
    bot = message_ref.bot if isinstance(message_ref, StoredMessageRef) else message_ref.get_bot()
    return await bot.send_message(
        chat_id=_message_chat_id(message_ref),
        text=text,
        reply_parameters=ReplyParameters(
            message_id=message_ref.message_id,
            allow_sending_without_reply=True,
        ),
        **kwargs,
    )


def _roast_chain_key(chat_id: int, message_id: int) -> str:
    return f"{chat_id}:{message_id}"


def _replied_roast_chain(message) -> list[dict] | None:
    """Return the roast chain the message replies to, or None if it isn't a roast reply."""
    reply_to = getattr(message, "reply_to_message", None)
    if not reply_to:
        return None
    return _roast_chains.get(_roast_chain_key(message.chat_id, reply_to.message_id))


def _store_roast_chain(chat_id: int, message_id: int, messages: list[dict]) -> None:
    while len(_roast_chains) >= ROAST_CHAINS_LIMIT:
        oldest = next(iter(_roast_chains))
        _roast_chains.pop(oldest, None)
    _roast_chains[_roast_chain_key(chat_id, message_id)] = [dict(message) for message in messages]


def _split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    chunks = []
    remaining = text.strip()
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks or [""]


async def _deliver_roast(reply_target, chain: list[dict], context, status_message=None):
    """Send the latest assistant turn (chain[-1]) as Telegram message(s) and map every
    delivered message id to the full chain so the user can reply to continue it."""
    chunks = _split_message(chain[-1]["content"])
    sent_messages = []
    for index, chunk in enumerate(chunks):
        if index == 0 and status_message is not None:
            await _edit_reply_message(context, status_message, chunk)
            sent_messages.append(status_message)
        else:
            target = sent_messages[-1] if sent_messages else reply_target
            sent_messages.append(await _reply_to_source(target, chunk))
    for message in sent_messages:
        _store_roast_chain(_message_chat_id(message), message.message_id, chain)
    return sent_messages[-1]


async def _sync_author_memory() -> None:
    async with _memory_lock:
        await _sync_author_memory_held()


async def _sync_bot_memory() -> None:
    async with _memory_lock:
        await _sync_bot_memory_held()


async def _sync_author_memory_held() -> None:
    """Best-effort two-way sync of the author profile with its Notion page. A
    page edited by hand wins, so run this before reading the profile too.
    Caller holds `_memory_lock`."""
    points = state_store.get_profile_points()
    try:
        result = await notion_memory.sync_author_memory(
            memory.texts(points),
            state_store.get_notion_mirror(PROFILE_SECTION),
        )
    except Exception:
        logger.exception("Failed to sync the author profile with Notion")
        return
    # The page carries no ids, so an adopted list keeps them where the text
    # survived the edit and mints fresh ones for what the author reworded.
    if result.adopted:
        state_store.set_profile_points(memory.adopt(points, result.items))
    state_store.set_notion_mirror(PROFILE_SECTION, result.items)


async def _sync_bot_memory_held() -> None:
    """Best-effort two-way sync of the behavior rules with their Notion page.
    Caller holds `_memory_lock`."""
    rules = state_store.get_rules()
    try:
        result = await notion_memory.sync_bot_memory(
            memory.texts(rules),
            state_store.get_notion_mirror(RULES_SECTION),
        )
    except Exception:
        logger.exception("Failed to sync the behavior rules with Notion")
        return
    if result.adopted:
        state_store.set_rules(memory.adopt(rules, result.items))
    state_store.set_notion_mirror(RULES_SECTION, result.items)


async def _sync_memory() -> None:
    """Pull hand edits from both memory pages before a roast reads its memory.

    Throttled: a roast is a conversation, and every follow-up turn would
    otherwise cost two Notion reads. Explicit reads — /rules, /memory, startup —
    call the per-page syncs directly and always pull."""
    global _last_memory_pull
    # Checked before the lock, so a throttled turn waits on nothing.
    if _last_memory_pull is not None and monotonic() - _last_memory_pull < MEMORY_PULL_TTL_SECONDS:
        return
    async with _memory_lock:
        await _sync_author_memory_held()
        await _sync_bot_memory_held()
        _last_memory_pull = monotonic()


async def _update_profile_points(diary_text: str, reply_target=None, language: str | None = None) -> None:
    """Best-effort: refresh the persisted author profile from a diary entry.
    Never blocks or breaks the roast flow — failures are logged and swallowed.

    `reply_target` is the message the note about the new facts replies to. An
    entry that taught nothing sends nothing."""
    await _sync_author_memory()
    existing = state_store.get_profile_points()
    try:
        points = await roast.extract_profile_points(diary_text, existing, language=language)
    except Exception:
        logger.exception("Failed to update roast profile points")
        return
    async with _memory_lock:
        # Extraction is slow, and a hand edit adopted while it ran would be
        # overwritten by a list merged from a stale read. Drop this pass instead
        # — the next diary message extracts again.
        if state_store.get_profile_points() != existing:
            logger.info("Author profile moved while extracting; dropping this pass")
            return
        state_store.set_profile_points(points)
        await _sync_author_memory_held()
    if reply_target is None:
        return
    # Outside the lock: a Telegram send must never hold memory.
    try:
        note, sent = await _send_memory_note(
            reply_target, (PROFILE_BLOCK_LABEL, _memory_diff_lines(existing, points))
        )
        if sent:
            chain = [
                {"role": "user", "content": diary_text},
                {"role": "assistant", "content": note},
            ]
            for message in sent:
                _store_roast_chain(_message_chat_id(message), message.message_id, chain)
    except Exception:
        logger.exception("Failed to post the profile update note")


def _memory_diff_lines(
    before: list[memory.MemoryItem],
    after: list[memory.MemoryItem],
) -> list[str]:
    """What changed in one memory list, by text: gained, then lost. A reworded
    entry reads as both, which is the shortest honest way to show a rewrite."""
    before_texts, after_texts = memory.texts(before), memory.texts(after)
    lines = [f"+ {text}" for text in after_texts if text not in before_texts]
    lines += [f"− {text}" for text in before_texts if text not in after_texts]
    return lines


def _render_memory_note(*blocks: tuple[str, list[str]]) -> str | None:
    """One compact note out of the blocks that moved. A block with no lines is
    dropped, and nothing moved at all means no note — the author is only ever
    pinged about a real change."""
    parts = [f"{label}:\n" + "\n".join(lines) for label, lines in blocks if lines]
    if not parts:
        return None
    language = state_store.get_language()
    localized = [
        f"{t(label, language)}:\n" + "\n".join(lines)
        for label, lines in blocks if lines
    ]
    return "\n".join([t(MEMORY_NOTE_HEADER, language), *localized])


async def _send_memory_note(reply_target, *blocks: tuple[str, list[str]]) -> tuple[str | None, list]:
    """Post the note, if there is one. A dense extraction can outgrow one
    Telegram message, so it is chunked like a roast. Returns the complete note
    and the messages that carried it."""
    text = _render_memory_note(*blocks)
    if not text:
        return None, []
    sent = []
    for chunk in _split_message(text):
        sent.append(await _reply_to_source(sent[-1] if sent else reply_target, chunk))
    return text, sent


async def _persist_rules_ops(
    reply_target,
    chain: list[dict],
    before: list[memory.MemoryItem],
    ops: list | None,
) -> None:
    """Store the rule operations the model attached to its reply and tell the author.

    No operations, or operations that change nothing, leave the stored list
    untouched: the model only sends them when it wants the rules changed."""
    if not ops:
        return
    after = memory.apply_ops(before, ops)
    if after == before:
        return
    state_store.set_rules(after)
    _, notes = await _send_memory_note(
        reply_target, (RULES_BLOCK_LABEL, _memory_diff_lines(before, after))
    )
    # Map the note to the chain too, so replying to it keeps the conversation.
    for note in notes:
        _store_roast_chain(_message_chat_id(note), note.message_id, chain)
    # Last, so Notion latency never delays the note.
    await _sync_bot_memory()


async def _run_roast(reply_target, chain: list[dict], context, status_message=None) -> None:
    language = _message_language(reply_target)
    # Hand edits in Notion outrank stored memory, so pull before reading it.
    await _sync_memory()
    points = state_store.get_profile_points()
    rules = state_store.get_rules()
    try:
        reply = await roast.roast(chain, points=points, rules=rules, language=language)
    except Exception as e:
        logger.exception("Error generating roast")
        error_text = t("roast.failed", language, error=e)
        if status_message is not None:
            await _edit_reply_message(context, status_message, error_text)
        else:
            await _reply_to_source(reply_target, error_text)
        return
    chain.append({"role": "assistant", "content": reply.text})
    last = await _deliver_roast(reply_target, chain, context, status_message=status_message)
    try:
        await _persist_rules_ops(last, chain, rules, reply.rules_ops)
    except Exception:
        logger.exception("Failed to persist roast rules update")


async def _roast_draft(query, context: ContextTypes.DEFAULT_TYPE, draft: dict) -> None:
    language = draft.get("language")
    if not roast.is_configured():
        await query.message.reply_text(t("roast.unavailable", language))
        return

    text = (draft.get("text") or "").strip()
    if not text:
        await query.message.reply_text(t("roast.empty", language))
        return

    status = await _reply_to_source(query.message, t("roast.status", language))
    chain = [{"role": "user", "content": text}]
    await _run_roast(query.message, chain, context, status_message=status)


async def _handle_roast_followup(update: Update, context: ContextTypes.DEFAULT_TYPE, chain: list[dict]) -> None:
    user_msg = update.effective_message
    reply_text = (user_msg.text or "").strip()
    if not reply_text:
        await handle_text(update, context)
        return

    new_chain = list(chain) + [{"role": "user", "content": reply_text}]
    status = await _reply_to_source(user_msg, t("roast.thinking", _message_language(user_msg)))
    await _run_roast(user_msg, new_chain, context, status_message=status)


async def _handle_roast_voice_followup(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chain: list[dict],
) -> None:
    """Continue a roast conversation from a voice reply: transcribe first, then roast."""
    user_msg = update.effective_message
    language = _message_language(user_msg)
    status = await _reply_to_source(user_msg, t("transcribing", language))
    try:
        reply_text = await _transcribe_voice_file(context, user_msg.voice.file_id)
    except Exception as e:
        logger.exception("Error transcribing roast follow-up voice message")
        await _edit_reply_message(context, status, t("error", language, error=e))
        return

    if not reply_text:
        await _edit_reply_message(
            context,
            status,
            t("speech.empty", language, model=settings.openai_transcription_model),
        )
        return

    logger.info(
        "Roast follow-up transcription with %s: %s",
        settings.openai_transcription_model,
        reply_text,
    )
    new_chain = list(chain) + [{"role": "user", "content": reply_text}]
    await _edit_reply_message(context, status, t("roast.thinking", language))
    await _run_roast(user_msg, new_chain, context, status_message=status)


async def post_init(application: Application) -> None:
    for language in SUPPORTED_LANGUAGES:
        await application.bot.set_my_commands(
            [BotCommand(name, t(description, language)) for name, description in COMMANDS],
            language_code=language,
        )
    await application.bot.set_my_commands(
        [BotCommand(name, t(description)) for name, description in COMMANDS]
    )
    try:
        await notion_memory.ensure_memory_pages()
    except Exception:
        logger.exception("Failed to ensure the Notion memory pages exist")
    # Adopt whatever was edited in Notion while the bot was down.
    await _sync_memory()
    await replay_unprocessed_messages(application)


async def replay_unprocessed_messages(application: Application) -> None:
    records = state_store.recent_unprocessed_messages(STARTUP_REPLAY_LIMIT)
    if not records:
        return

    logger.info("Replaying %d unprocessed message(s) after restart", len(records))
    for record in records:
        message_ref = StoredMessageRef(
            application.bot,
            chat_id=record["chat_id"],
            message_id=record["message_id"],
        )
        context = SimpleNamespace(
            application=application,
            bot=application.bot,
            user_data={},
        )
        application.create_task(
            _process_message_record(record["key"], message_ref, context),
        )


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    language = _message_language(update=update)
    payload = context.args[0] if getattr(context, "args", None) else None
    source = _parse_source_deeplink_payload(payload)
    if source:
        await _send_source_jump(update, context, *source)
        return

    await update.effective_message.reply_text(t("welcome", language))


async def _send_source_jump(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
) -> None:
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=t("source.message", _message_language(update=update)),
            reply_parameters=ReplyParameters(
                message_id=message_id,
                allow_sending_without_reply=False,
            ),
        )
    except Exception:
        logger.exception("Error opening source message")
        await update.effective_message.reply_text(
            t("source.failed", _message_language(update=update))
        )


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(_help_text(_message_language(update=update)), parse_mode="Markdown")


def _language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(LANGUAGE_NAMES[language], callback_data=f"language:{language}")
            for language in SUPPORTED_LANGUAGES
        ]
    ])


async def _set_chat_commands(context: ContextTypes.DEFAULT_TYPE, chat_id: int, language: str) -> None:
    await context.bot.set_my_commands(
        [BotCommand(name, t(description, language)) for name, description in COMMANDS],
        scope=BotCommandScopeChat(chat_id),
    )


async def handle_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    language = _message_language(update=update)
    await update.effective_message.reply_text(
        "\n".join([
            t("language.current", language, language_name=LANGUAGE_NAMES[language]),
            t("language.choose", language),
        ]),
        reply_markup=_language_keyboard(),
    )


async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, language = (query.data or "").split(":", 1)
    if language not in SUPPORTED_LANGUAGES:
        await query.edit_message_text(t("language.invalid", _message_language(update=update)))
        return
    state_store.set_language(language)
    await _set_chat_commands(context, query.message.chat_id, language)
    await query.edit_message_text(t("language.changed", language, language_name=LANGUAGE_NAMES[language]))


async def handle_rules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the standing behavior rules. Editing happens in conversation: tell
    the bot how to act, or to forget a rule, and it rewrites the list itself.
    Rules typed straight into the Notion page count too — they are pulled first."""
    await _sync_bot_memory()
    language = _message_language(update=update)
    rules = state_store.get_rules()
    if not rules:
        await update.effective_message.reply_text(
            t("rules.empty", language)
        )
        return
    lines = [t("rules.header", language)] + [
        f"{index}. {rule}" for index, rule in enumerate(memory.texts(rules), 1)
    ]
    await update.effective_message.reply_text("\n".join(lines))


async def _transcribe_voice_file(context: ContextTypes.DEFAULT_TYPE, file_id: str) -> str:
    tmp_path = None
    try:
        voice_file = await context.bot.get_file(file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name
        await voice_file.download_to_drive(tmp_path)
        return (await transcribe(tmp_path)).strip()
    finally:
        if tmp_path:
            with suppress(FileNotFoundError):
                os.unlink(tmp_path)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    language = _message_language(message, update)
    roast_chain = _replied_roast_chain(message)
    if roast_chain is not None:
        await _handle_roast_voice_followup(update, context, roast_chain)
        return

    reply_to = getattr(message, "reply_to_message", None)
    if reply_to and _memory_prompts(context).pop(
        _prompt_key(_message_chat_id(message), reply_to.message_id), None
    ):
        await _receive_memory_focus_voice(update, context)
        return

    voice = message.voice
    file_unique_id = getattr(voice, "file_unique_id", None)
    duration = getattr(voice, "duration", None)
    file_size = getattr(voice, "file_size", None)
    message_key = state_store.record_voice(
        chat_id=message.chat_id,
        message_id=message.message_id,
        file_id=voice.file_id,
        date=_message_date(message),
        file_unique_id=file_unique_id,
        duration=duration,
        file_size=file_size,
        source_message_url=_telegram_message_url(message, _bot_username(context)),
        language=language,
    )
    duplicate = state_store.find_duplicate_voice(
        file_unique_id,
        duration=duration,
        file_size=file_size,
        exclude_key=message_key,
    )
    if duplicate:
        state_store.mark_message_duplicate_pending(message_key, duplicate["key"])
        await _reply_to_source(
            message,
            t("duplicate.voice", language),
            reply_markup=_duplicate_voice_keyboard(message_key, language),
        )
        return

    context.application.create_task(
        _process_message_record(message_key, message, context),
        update=update,
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    language = _message_language(message, update)
    message_key = state_store.record_text(
        chat_id=message.chat_id,
        message_id=message.message_id,
        text=message.text,
        date=_message_date(message),
        source_message_url=_telegram_message_url(message, _bot_username(context)),
        language=language,
    )
    context.application.create_task(
        _process_message_record(message_key, message, context),
        update=update,
    )


async def _process_message_record(
    message_key: str,
    message_ref,
    context: ContextTypes.DEFAULT_TYPE,
    status_message=None,
) -> None:
    record = state_store.get_message(message_key)
    if not record or record.get("status") in {"drafted", "saved"}:
        return

    state_store.mark_message_processing(message_key)
    if record["kind"] == "voice":
        await _process_voice_record(record, message_ref, context, status_message=status_message)
    elif record["kind"] == "text":
        await _process_text_record(record, message_ref, context, status_message=status_message)


async def _process_voice_record(
    record: dict[str, Any],
    message_ref,
    context: ContextTypes.DEFAULT_TYPE,
    status_message=None,
) -> None:
    status_msg = status_message
    language = record.get("language")
    try:
        if status_msg:
            await _edit_reply_message(context, status_msg, t("listening", language))
        else:
            status_msg = await _reply_to_source(message_ref, t("listening", language))

        await _edit_reply_message(context, status_msg, t("transcribing", language))
        transcription = await _transcribe_voice_file(context, record["file_id"])
        logger.info(
            "Transcription with %s: %s",
            settings.openai_transcription_model,
            transcription,
        )
        if not transcription:
            state_store.mark_message_failed(
                record["key"],
                f"{settings.openai_transcription_model} returned an empty transcription",
            )
            await _edit_reply_message(
                context,
                status_msg,
                t("speech.empty", language, model=settings.openai_transcription_model),
                reply_markup=_retry_processing_keyboard(record["key"], language),
            )
            return

        await _create_preview(
            message_ref,
            context,
            transcription,
            message_key=record["key"],
            preview_message=status_msg,
            language=language,
        )

    except Exception as e:
        logger.exception("Error processing voice message")
        state_store.mark_message_failed(record["key"], str(e))
        if status_msg:
            await _edit_reply_message(
                context,
                status_msg,
                t("error", language, error=e),
                reply_markup=_retry_processing_keyboard(record["key"], language),
            )
        else:
            await _reply_to_source(
                message_ref,
                t("error", language, error=e),
                reply_markup=_retry_processing_keyboard(record["key"], language),
            )


async def _process_text_record(
    record: dict[str, Any],
    message_ref,
    context: ContextTypes.DEFAULT_TYPE,
    status_message=None,
) -> None:
    status_msg = status_message
    language = record.get("language")
    try:
        if status_msg:
            await _edit_reply_message(context, status_msg, t("preparing", language))
        else:
            status_msg = await _reply_to_source(message_ref, t("preparing", language))
        await _create_preview(
            message_ref,
            context,
            record["text"],
            message_key=record["key"],
            preview_message=status_msg,
            language=language,
        )
    except Exception as e:
        logger.exception("Error processing text message")
        state_store.mark_message_failed(record["key"], str(e))
        if status_msg:
            await _edit_reply_message(
                context,
                status_msg,
                t("error", language, error=e),
                reply_markup=_retry_processing_keyboard(record["key"], language),
            )
        else:
            await _reply_to_source(
                message_ref,
                t("error", language, error=e),
                reply_markup=_retry_processing_keyboard(record["key"], language),
            )


async def _create_preview(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    source_text: str,
    message_key: str | None = None,
    preview_message=None,
    language: str | None = None,
) -> None:
    entry_id = _new_entry_id()
    entry_date = _default_entry_date()
    record = state_store.get_message(message_key) if message_key else None
    language = normalize_language(language)
    title, formatted_text, tags = await format_entry(source_text, language)
    text = source_text

    preview = _render_preview(title, text, tags, entry_date, language=language)
    keyboard = _preview_keyboard(
        entry_id,
        highlighted=False,
        entry_date=entry_date,
        show_format=_can_show_format(formatted_text),
        show_pagination=preview.truncated,
        preview_page=preview.page,
        page_count=preview.page_count,
        language=language,
    )
    if preview_message:
        preview_msg = preview_message
        await _edit_reply_message(
            context,
            preview_msg,
            preview.text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    else:
        preview_msg = await _reply_to_source(
            message,
            preview.text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    _drafts(context)[entry_id] = {
        "id": entry_id,
        "title": title,
        "text": text,
        "tags": tags,
        "raw_text": source_text,
        "formatted_text": formatted_text,
        "formatted": False,
        "entry_date": entry_date,
        "metadata": _entry_metadata(record, source_text, bot_username=_bot_username(context)),
        "language": language,
        "allow_duplicate": bool(record and record.get("allow_duplicate")),
        "chat_id": message.chat_id,
        "preview_msg_id": preview_msg.message_id,
        "preview_page": preview.page,
        "saving": False,
        "message_key": message_key,
    }
    state_store.save_draft(_drafts(context)[entry_id])
    if message_key:
        state_store.mark_message_drafted(message_key, entry_id)
    if source_text and source_text.strip():
        context.application.create_task(_update_profile_points(source_text, preview_msg, language))


def _callback_payload(update: Update) -> tuple[str, str] | tuple[None, None]:
    data = update.callback_query.data or ""
    if ":" not in data:
        return None, None
    action, entry_id = data.split(":", 2)[:2]
    return action, entry_id


def _callback_value(update: Update) -> str | None:
    data = update.callback_query.data or ""
    parts = data.split(":", 2)
    if len(parts) < 3:
        return None
    return parts[2]


async def entry_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    action, entry_id = _callback_payload(update)
    draft = _get_draft(context, entry_id)
    language = draft.get("language") if draft else _message_language(update=update)
    if not action or not draft:
        await query.message.reply_text(t("draft.gone", language))
        return

    if draft.get("saving") and action != "save":
        await query.message.reply_text(t("draft.saving", language))
        return

    if action == "save":
        await _save_draft(query, context, entry_id, draft)
    elif action == "save_anyway":
        draft["allow_duplicate"] = True
        state_store.save_draft(draft)
        await _save_draft(query, context, entry_id, draft)
    elif action == "format":
        await _format_draft(query, context, draft)
    elif action == "roast":
        await _roast_draft(query, context, draft)
    elif action == "unformat":
        await _unformat_draft(query, context, draft)
    elif action == "cancel":
        await _cancel_draft(query, context, entry_id, draft)
    elif action == "toggle_highlight":
        await _toggle_highlight(context, draft)
    elif action == "preview_page":
        await _set_preview_page(update, context, draft)
    elif action == "pick_date":
        await _show_date_picker(query, draft)
    elif action == "back_to_preview":
        await _edit_preview(context, draft)
    elif action == "set_date":
        await _set_entry_date(update, context, draft)
    elif action in {"edit_title", "edit_text", "edit_tags"}:
        await _request_edit(query, context, entry_id, action.removeprefix("edit_"), language)


async def duplicate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    if ":" not in data:
        await query.message.reply_text(t("voice.gone", _message_language(update=update)))
        return

    action, message_key = data.split(":", 1)
    record = state_store.get_message(message_key)
    language = record.get("language") if record else _message_language(update=update)
    if not record or record.get("kind") != "voice":
        await query.edit_message_text(t("voice.gone", language))
        return

    if action == "cancel_duplicate":
        state_store.mark_message_cancelled(message_key)
        await query.edit_message_text(t("cancelled", language))
        return

    if action != "add_duplicate":
        return

    state_store.mark_message_duplicate_confirmed(message_key)
    await query.edit_message_text(t("adding_anyway", language))
    message_ref = StoredMessageRef(
        context.bot,
        chat_id=record["chat_id"],
        message_id=record["message_id"],
    )
    context.application.create_task(
        _process_message_record(message_key, message_ref, context),
        update=update,
    )


async def retry_processing_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    if ":" not in data:
        await query.message.reply_text(t("message.gone", _message_language(update=update)))
        return

    _, message_key = data.split(":", 1)
    record = state_store.get_message(message_key)
    language = record.get("language") if record else _message_language(update=update)
    if not record or record.get("status") in {"drafted", "saved", "cancelled"}:
        await query.edit_message_text(t("message.gone", language))
        return
    if record.get("status") == "processing":
        await query.message.reply_text(t("processing", language))
        return

    message_ref = StoredMessageRef(
        context.bot,
        chat_id=record["chat_id"],
        message_id=record["message_id"],
    )
    await query.edit_message_text(t("retrying", language))
    context.application.create_task(
        _process_message_record(message_key, message_ref, context, status_message=query.message),
        update=update,
    )


def _draft_metadata_for_save(draft: dict, context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    metadata = dict(draft.get("metadata") or {})
    bot_username = _bot_username(context)
    if metadata.get("source_message_url") and not metadata["source_message_url"].startswith("tg://"):
        return metadata

    message_key = draft.get("message_key")
    record = state_store.get_message(message_key) if message_key else None
    if record:
        generated = _entry_metadata(
            record,
            draft.get("raw_text") or draft.get("text") or "",
            bot_username=bot_username,
        )
        metadata = {**generated, **metadata}
    elif metadata.get("telegram_chat_id") is not None and metadata.get("telegram_message_id") is not None:
        metadata["source_message_url"] = _clickable_source_message_url(
            metadata["telegram_chat_id"],
            metadata["telegram_message_id"],
            stored_url=metadata.get("source_message_url"),
            bot_username=bot_username,
        )

    if metadata:
        draft["metadata"] = metadata
        return metadata
    return None


async def _save_draft(query, context: ContextTypes.DEFAULT_TYPE, entry_id: str, draft: dict) -> None:
    if draft.get("saving"):
        return

    draft["saving"] = True
    language = draft.get("language")
    draft["entry_date"] = _normalize_entry_date(draft.get("entry_date"))
    metadata = _draft_metadata_for_save(draft, context)
    try:
        await query.edit_message_text(t("saving", language))
        result = await save_entry(
            draft["title"],
            draft["text"],
            draft["tags"],
            metadata=metadata,
            entry_date=draft["entry_date"],
            allow_duplicate=draft.get("allow_duplicate", False),
        )
        if result.created:
            await query.edit_message_text(t("saved", language))
        else:
            draft["saving"] = False
            state_store.save_draft(draft)
            await query.edit_message_text(
                _duplicate_warning_text(draft.get("metadata"), language),
                reply_markup=_duplicate_save_keyboard(entry_id, language),
            )
            return
    except Exception as e:
        logger.exception("Error saving to Notion")
        draft["saving"] = False
        state_store.save_draft(draft)
        await query.edit_message_text(
            t("not_saved", language, error=e),
            reply_markup=_preview_keyboard_for_draft(draft),
        )
        return

    _drafts(context).pop(entry_id, None)
    state_store.mark_message_saved(draft.get("message_key"))
    state_store.remove_draft(entry_id)


async def _format_draft(query, context: ContextTypes.DEFAULT_TYPE, draft: dict) -> None:
    if draft.get("formatted"):
        await query.message.reply_text(t("formatted_already", draft.get("language")))
        return

    formatted_text = draft.get("formatted_text")
    if not formatted_text:
        await query.message.reply_text(t("formatted_missing", draft.get("language")))
        return

    draft["text"] = formatted_text
    draft["formatted"] = True
    draft["preview_page"] = 0
    state_store.save_draft(draft)
    await _edit_preview(context, draft)


async def _unformat_draft(query, context: ContextTypes.DEFAULT_TYPE, draft: dict) -> None:
    if not draft.get("formatted"):
        await query.message.reply_text(t("original_already", draft.get("language")))
        return

    raw_text = draft.get("raw_text")
    if raw_text is None:
        await query.message.reply_text(t("original_missing", draft.get("language")))
        return

    draft["text"] = raw_text
    draft["formatted"] = False
    draft["preview_page"] = 0
    state_store.save_draft(draft)
    await _edit_preview(context, draft)


async def _cancel_draft(query, context: ContextTypes.DEFAULT_TYPE, entry_id: str, draft: dict) -> None:
    _drafts(context).pop(entry_id, None)
    state_store.mark_message_cancelled(draft.get("message_key"))
    state_store.remove_draft(entry_id)
    await query.edit_message_text(t("cancelled", draft.get("language")))


async def _toggle_highlight(context: ContextTypes.DEFAULT_TYPE, draft: dict) -> None:
    highlighted = _draft_highlighted(draft)
    if highlighted:
        draft["title"] = draft["title"][len("⭐ "):]
    else:
        draft["title"] = f"⭐ {draft['title']}"
    state_store.save_draft(draft)

    await _edit_preview(context, draft)


async def _edit_preview(context: ContextTypes.DEFAULT_TYPE, draft: dict) -> None:
    previous_entry_date = draft.get("entry_date")
    previous_preview_page = draft.get("preview_page")
    draft["entry_date"] = _normalize_entry_date(draft.get("entry_date"))
    preview = _render_preview_for_draft(draft)
    draft["preview_page"] = preview.page
    if previous_entry_date != draft["entry_date"] or previous_preview_page != preview.page:
        state_store.save_draft(draft)
    await context.bot.edit_message_text(
        chat_id=draft["chat_id"],
        message_id=_preview_msg_id(draft),
        text=preview.text,
        parse_mode="HTML",
        reply_markup=_preview_keyboard_for_draft(draft, preview),
    )


async def _set_preview_page(update: Update, context: ContextTypes.DEFAULT_TYPE, draft: dict) -> None:
    try:
        draft["preview_page"] = int(_callback_value(update) or 0)
    except ValueError:
        draft["preview_page"] = 0
    state_store.save_draft(draft)
    await _edit_preview(context, draft)


async def _show_date_picker(query, draft: dict) -> None:
    draft["entry_date"] = _normalize_entry_date(draft.get("entry_date"))
    await query.edit_message_text(
        text=t("date.choose", draft.get("language"), date=escape(_entry_date_label(draft["entry_date"], draft.get("language")))),
        parse_mode="HTML",
        reply_markup=_date_picker_keyboard(draft["id"], draft["entry_date"], draft.get("language")),
    )


async def _set_entry_date(update: Update, context: ContextTypes.DEFAULT_TYPE, draft: dict) -> None:
    entry_date = _callback_value(update)
    if entry_date not in _entry_date_options():
        await update.callback_query.message.reply_text(t("date.gone", draft.get("language")))
        await _show_date_picker(update.callback_query, draft)
        return

    draft["entry_date"] = entry_date
    state_store.save_draft(draft)
    await _edit_preview(context, draft)


async def _request_edit(query, context: ContextTypes.DEFAULT_TYPE, entry_id: str, field: str, language: str | None = None) -> None:
    labels = {
        "title": t("edit.title", language),
        "text": t("edit.text", language),
        "tags": t("edit.tags", language),
    }
    prompt = await query.message.reply_text(
        labels[field],
        reply_markup=ForceReply(selective=True),
    )
    _edit_prompts(context)[_prompt_key(query.message.chat_id, prompt.message_id)] = {
        "entry_id": entry_id,
        "field": field,
    }


async def receive_edit_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_msg = update.effective_message
    reply_to = user_msg.reply_to_message
    if not reply_to:
        await handle_text(update, context)
        return

    chat_id = update.effective_chat.id
    prompt_id = reply_to.message_id
    prompt = _edit_prompts(context).pop(_prompt_key(chat_id, prompt_id), None)
    if not prompt:
        if _memory_prompts(context).pop(_prompt_key(chat_id, prompt_id), None):
            await _receive_memory_focus(update, context, user_msg.text or "")
            return
        roast_chain = _roast_chains.get(_roast_chain_key(chat_id, prompt_id))
        if roast_chain is not None:
            await _handle_roast_followup(update, context, roast_chain)
            return
        await handle_text(update, context)
        return

    draft = _get_draft(context, prompt["entry_id"])
    if not draft:
        await user_msg.reply_text(t("draft.gone", _message_language(user_msg, update)))
        return

    field = prompt["field"]
    if field == "title":
        draft["title"] = user_msg.text.strip()
    elif field == "text":
        draft["text"] = user_msg.text.strip()
        if not draft.get("formatted"):
            draft["raw_text"] = draft["text"]
    elif field == "tags":
        draft["tags"] = [t.strip() for t in user_msg.text.split(",") if t.strip()]
    draft["preview_page"] = 0

    state_store.save_draft(draft)
    await _edit_preview(context, draft)
    with suppress(Exception):
        await context.bot.delete_message(chat_id, prompt_id)
    with suppress(Exception):
        await context.bot.delete_message(chat_id, user_msg.message_id)


# --- Retrospective long-term memory rebuild -------------------------------
# Two steps: /memory asks for focus points, the reply shows a confirmation card,
# and Confirm starts a sequential walk over every saved note. Every message here
# is plain text on purpose — the focus text is arbitrary user input and must not
# be parsed as Markdown or HTML.


def _memory_stored_line(stored: int, language: str | None = None) -> str:
    if stored:
        return t("memory.stored", language, count=stored)
    return t("memory.empty_stored", language)


def _memory_intro_text(stored: int, language: str | None = None) -> str:
    return t("memory.intro", language, stored=_memory_stored_line(stored, language))


def _memory_focus_line(focus: str, language: str | None = None) -> str:
    return t("memory.focus", language, focus=focus) if focus else t("memory.no_focus", language)


def _memory_confirm_text(focus: str, stored: int, language: str | None = None) -> str:
    return t(
        "memory.confirm",
        language,
        focus=_memory_focus_line(focus, language),
        stored=_memory_stored_line(stored, language),
    )


def _memory_progress_text(progress, focus: str, language: str | None = None) -> str:
    return t(
        "memory.progress",
        language,
        bar=profile_rebuild.render_progress_bar(progress.handled, progress.total),
        facts=len(progress.points),
        focus=_memory_focus_line(focus, language),
    )


def _memory_result_text(progress, before: int, focus: str, language: str | None = None) -> str:
    if not progress.total:
        return t("memory.no_notes", language)

    lines = [
        t("memory.stopped", language) if progress.aborted_reason
        else t("memory.done", language),
        "",
        profile_rebuild.render_progress_bar(progress.handled, progress.total),
        t("memory.notes_read", language, count=progress.processed),
    ]
    if progress.skipped:
        lines.append(t("memory.empty_skipped", language, count=progress.skipped))
    if progress.failed:
        lines.append(t("memory.failed_count", language, count=progress.failed))
    lines.append(t("memory.facts", language, before=before, after=len(progress.points)))
    lines.append(_memory_focus_line(focus, language))
    if progress.aborted_reason:
        lines += ["", t("memory.reason", language, reason=progress.aborted_reason), t("memory.saved_so_far", language)]
    return "\n".join(lines)


def _memory_keyboard(request_id: str, language: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(t("button.confirm", language), callback_data=f"memory_confirm:{request_id}"),
        InlineKeyboardButton(t("button.cancel", language), callback_data=f"memory_cancel:{request_id}"),
    ]])


async def handle_memory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Step 1: ask for the focus points that should steer this rebuild."""
    message = update.effective_message
    language = _message_language(message, update)
    if not roast.is_configured():
        await message.reply_text(t("memory.api_missing", language))
        return
    if profile_rebuild.is_running():
        await message.reply_text(t("memory.running", language))
        return

    prompt = await message.reply_text(
        _memory_intro_text(len(state_store.get_profile_points()), language),
        reply_markup=ForceReply(selective=True),
    )
    _memory_prompts(context)[_prompt_key(_message_chat_id(message), prompt.message_id)] = True


async def _receive_memory_focus(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    focus_text: str,
) -> None:
    """Step 2: park the focus under a request id and ask for confirmation."""
    focus = " ".join(focus_text.split())
    if focus.lower() in MEMORY_SKIP_FOCUS_TOKENS:
        focus = ""

    request_id = _new_entry_id()
    language = _message_language(update.effective_message, update)
    _memory_requests(context)[request_id] = {"focus": focus, "language": language}
    await update.effective_message.reply_text(
        _memory_confirm_text(focus, len(state_store.get_profile_points()), language),
        reply_markup=_memory_keyboard(request_id, language),
    )


async def _receive_memory_focus_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A voice reply to the focus prompt is transcribed into focus, never saved as a note."""
    message = update.effective_message
    language = _message_language(message, update)
    status = await _reply_to_source(message, t("transcribing", language))
    try:
        focus_text = await _transcribe_voice_file(context, message.voice.file_id)
    except Exception as e:
        logger.exception("Error transcribing memory focus voice message")
        await _edit_reply_message(context, status, t("memory.voice_retry", language, error=e))
        return

    if not focus_text:
        await _edit_reply_message(
            context,
            status,
            t("memory.no_speech_retry", language, model=settings.openai_transcription_model),
        )
        return

    await _edit_reply_message(context, status, t("memory.focus", language, focus=focus_text))
    await _receive_memory_focus(update, context, focus_text)


async def memory_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Step 3: Confirm starts the sequential pass, Cancel drops the request."""
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    if ":" not in data:
        return
    action, request_id = data.split(":", 1)

    request = _memory_requests(context).pop(request_id, None)
    language = (request or {}).get("language") or _message_language(update=update)
    if request is None:
        await query.edit_message_text(t("memory.request_gone", language))
        return

    if action == "memory_cancel":
        await query.edit_message_text(t("memory.cancelled", language))
        return

    if profile_rebuild.is_running():
        await query.edit_message_text(t("memory.running", language))
        return

    focus = request.get("focus") or ""
    await query.edit_message_text(t("memory.starting", language))
    context.application.create_task(
        _run_memory_rebuild(context, query.message, focus, language),
        update=update,
    )


async def _run_memory_rebuild(
    context: ContextTypes.DEFAULT_TYPE,
    status_message,
    focus: str,
    language: str | None = None,
) -> None:
    """Drive the sequential rebuild: persist points after every note so an abort or
    a restart never loses the pass, and refresh the progress message on a throttle."""
    await _sync_author_memory()
    before = state_store.get_profile_points()
    last_rendered = None

    async def on_progress(progress) -> None:
        nonlocal last_rendered
        state_store.set_profile_points(progress.points)
        if progress.handled % MEMORY_PROGRESS_EVERY:
            return
        text = _memory_progress_text(progress, focus, language)
        if text == last_rendered:
            return
        last_rendered = text
        with suppress(Exception):
            await _edit_reply_message(context, status_message, text)

    try:
        result = await profile_rebuild.rebuild_profile(focus or None, before, on_progress, language=language)
    except profile_rebuild.RebuildAlreadyRunning:
        with suppress(Exception):
            await _edit_reply_message(context, status_message, t("memory.running", language))
        return
    except Exception as e:
        logger.exception("Memory rebuild failed")
        with suppress(Exception):
            await _edit_reply_message(context, status_message, t("memory.failed", language, error=e))
        return

    # One sync for the whole pass, not one per note.
    await _sync_author_memory()

    with suppress(Exception):
        await _edit_reply_message(
            context,
            status_message,
            _memory_result_text(result, len(before), focus, language),
        )


async def handle_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    language = _message_language(update=update)
    await update.effective_message.reply_text(t("weekly.generating", language))
    try:
        report = await generate_weekly_report(language)
        if report:
            await update.effective_message.reply_text(
                f"{t('weekly.header', language)}\n\n{report}",
                parse_mode="Markdown",
            )
        else:
            await update.effective_message.reply_text(t("weekly.empty", language))
    except Exception:
        logger.exception("Error generating weekly report")
        await update.effective_message.reply_text(t("weekly.error", language))


async def handle_stat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    language = _message_language(update=update)
    await update.effective_message.reply_text(t("stat.counting", language))
    try:
        stats = await build_audio_stats(language=language)
        await update.effective_message.reply_text(
            format_audio_stats(stats, language),
            parse_mode="Markdown",
        )
    except Exception:
        logger.exception("Error generating audio stats")
        await update.effective_message.reply_text(t("stat.error", language))


async def send_weekly_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Generating weekly report...")
    language = state_store.get_language()
    try:
        report = await generate_weekly_report(language)
        if report:
            await context.bot.send_message(
                chat_id=settings.allowed_user_id,
                text=f"{t('weekly.header', language)}\n\n{report}",
                parse_mode="Markdown",
            )
        else:
            await context.bot.send_message(
                chat_id=settings.allowed_user_id,
                text=t("weekly.empty_push", language),
            )
    except Exception:
        logger.exception("Error generating weekly report")


async def send_daily_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Generating daily summary...")
    language = state_store.get_language()
    try:
        summary = await generate_daily_summary(language)
        if summary:
            await context.bot.send_message(
                chat_id=settings.allowed_user_id,
                text=f"{t('daily.header', language)}\n\n{summary}",
                parse_mode="Markdown",
            )
        else:
            await context.bot.send_message(
                chat_id=settings.allowed_user_id,
                text=t("daily.empty_push", language),
            )
    except Exception:
        logger.exception("Error generating daily summary")


def main() -> None:
    app = (
        ApplicationBuilder()
        .token(settings.telegram_token)
        .defaults(Defaults(disable_notification=settings.silent_notifications))
        .concurrent_updates(MAX_CONCURRENT_UPDATES)
        .post_init(post_init)
        .build()
    )

    user_filter = filters.User(user_id=settings.allowed_user_id)

    command_handlers = [
        CommandHandler("start", handle_start, filters=user_filter),
        CommandHandler("help", handle_help, filters=user_filter),
        CommandHandler("weekly", handle_weekly, filters=user_filter),
        CommandHandler("stat", handle_stat, filters=user_filter),
        CommandHandler("memory", handle_memory, filters=user_filter),
        CommandHandler("rules", handle_rules, filters=user_filter),
        CommandHandler("language", handle_language, filters=user_filter),
    ]

    for handler in command_handlers:
        app.add_handler(handler)
    app.add_handler(MessageHandler(filters.VOICE & user_filter, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.REPLY & user_filter, receive_edit_reply))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & user_filter, handle_text))
    app.add_handler(
        CallbackQueryHandler(
            retry_processing_callback,
            pattern="^retry_process:",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            duplicate_callback,
            pattern="^(add_duplicate|cancel_duplicate):",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            memory_callback,
            pattern="^memory_(confirm|cancel):",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            language_callback,
            pattern="^language:",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            entry_callback,
            pattern="^(save|save_anyway|format|roast|unformat|cancel|toggle_highlight|preview_page|pick_date|set_date|back_to_preview|edit_title|edit_text|edit_tags):",
        )
    )

    tz = zoneinfo.ZoneInfo(settings.timezone)
    app.job_queue.run_daily(
        send_daily_summary,
        time=time(21, 0, tzinfo=tz),
    )
    app.job_queue.run_daily(
        send_weekly_report,
        time=time(21, 0, tzinfo=tz),
        days=(6,),  # Sunday only
    )

    logger.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
