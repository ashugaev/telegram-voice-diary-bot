import asyncio
import re
from dataclasses import dataclass
from datetime import date, timedelta
import httpx
from config import settings
from services.diary_dates import diary_today

API = "https://api.notion.com/v1"
NOTION_TIMEOUT = 30
NOTION_RETRY_ATTEMPTS = 3
NOTION_RETRY_DELAY = 1
NOTION_TEXT_CHUNK_SIZE = 2000
TITLE_PROPERTY_CANDIDATES = ("Name", "Title", "title")
CREATED_PROPERTY = "Created"
TAGS_PROPERTY = "Tags"
DAY_PROPERTY = "Day"
SOURCE_PROPERTY = "Source"
SOURCE_OPTIONS = ("voice", "text")
TELEGRAM_CHAT_ID_PROPERTY = "Telegram Chat ID"
TELEGRAM_MESSAGE_ID_PROPERTY = "Telegram Message ID"
SOURCE_MESSAGE_URL_PROPERTY = "Source Message URL"
ORIGINAL_TEXT_PROPERTY = "Original Text"
VOICE_FILE_UNIQUE_ID_PROPERTY = "Voice File Unique ID"
AUDIO_DURATION_PROPERTY = "Audio Duration"
AUDIO_FILE_SIZE_PROPERTY = "Audio File Size"
SOURCE_TEXT_HASH_PROPERTY = "Source Text SHA256"
HEADERS = {
    "Authorization": f"Bearer {settings.notion_token}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


@dataclass(frozen=True)
class NotionSchema:
    title: str
    created: str
    tags: str
    day: str
    source: str
    telegram_chat_id: str
    telegram_message_id: str
    source_message_url: str
    original_text: str
    voice_file_unique_id: str
    audio_duration: str
    audio_file_size: str
    source_text_hash: str


@dataclass(frozen=True)
class SaveResult:
    page_id: str
    created: bool


def _is_retryable_status(status_code: int) -> bool:
    return status_code in {408, 409, 429} or status_code >= 500


async def _request_with_retry(
    http: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs,
) -> httpx.Response:
    delay = NOTION_RETRY_DELAY
    request = getattr(http, method)
    for attempt in range(1, NOTION_RETRY_ATTEMPTS + 1):
        try:
            resp = await request(url, headers=HEADERS, **kwargs)
        except httpx.RequestError as e:
            if attempt == NOTION_RETRY_ATTEMPTS:
                raise RuntimeError(
                    f"Notion {method.upper()} failed after {attempt} attempts: {e}"
                ) from e
        else:
            if resp.is_success:
                return resp
            if not _is_retryable_status(resp.status_code) or attempt == NOTION_RETRY_ATTEMPTS:
                raise RuntimeError(f"Notion {method.upper()} error {resp.status_code}: {resp.text}")

        await asyncio.sleep(delay)
        delay *= 2

    raise RuntimeError(f"Notion {method.upper()} failed after {NOTION_RETRY_ATTEMPTS} attempts")


MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}


def _today_date() -> str:
    return diary_today().isoformat()  # e.g. "2026-04-09"


def _notion_entry_date(entry_date: str | None = None) -> str:
    if not entry_date:
        return _today_date()
    try:
        return date.fromisoformat(entry_date).isoformat()
    except ValueError as e:
        raise RuntimeError(f"Invalid entry date: {entry_date}") from e


def _today_label() -> str:
    today = diary_today()
    return f"{today.day} {MONTHS_RU[today.month]}"


def extract_page_title(page: dict) -> str:
    title_prop = _find_page_property(page["properties"], "title", TITLE_PROPERTY_CANDIDATES)
    parts = title_prop.get("title", [])
    return "".join(p["plain_text"] for p in parts)


def _find_page_property(properties: dict, prop_type: str, candidates: tuple[str, ...]) -> dict:
    for name in candidates:
        prop = properties.get(name)
        if prop and prop.get("type") == prop_type:
            return prop
    for prop in properties.values():
        if prop.get("type") == prop_type:
            return prop
    raise RuntimeError(f"Notion page is missing a {prop_type} property")


def _find_database_property(properties: dict, prop_type: str, candidates: tuple[str, ...]) -> str:
    for name in candidates:
        prop = properties.get(name)
        if prop and prop.get("type") == prop_type:
            return name
    for name, prop in properties.items():
        if prop.get("type") == prop_type:
            return name
    available = ", ".join(sorted(properties))
    raise RuntimeError(f"Notion database is missing a {prop_type} property. Available: {available}")


async def _database_properties(http: httpx.AsyncClient) -> dict:
    resp = await _request_with_retry(
        http,
        "get",
        f"{API}/databases/{settings.notion_database_id}",
    )
    return resp.json().get("properties", {})


def _ensure_database_property(
    properties: dict,
    updates: dict,
    name: str,
    prop_type: str,
    create_body: dict,
) -> str:
    prop = properties.get(name)
    if not prop:
        updates[name] = create_body
    elif prop.get("type") != prop_type:
        raise RuntimeError(f'Notion property "{name}" must be a {prop_type} property')
    return name


def _ensure_select_options(
    properties: dict,
    updates: dict,
    name: str,
    required_options: tuple[str, ...],
) -> None:
    """Adds any missing select options so query filters on them don't 400.

    Notion auto-creates select options when writing a page, but rejects query
    filters that reference an option the database has never seen.
    """
    prop = properties.get(name)
    if not prop or prop.get("type") != "select":
        return
    existing = prop.get("select", {}).get("options", [])
    existing_names = {option["name"] for option in existing}
    missing = [option for option in required_options if option not in existing_names]
    if not missing:
        return
    merged = [{"name": option_name} for option_name in existing_names | set(missing)]
    pending = updates.get(name, {})
    select_body = {**pending.get("select", {}), "options": merged}
    updates[name] = {**pending, "select": select_body}


async def ensure_database_schema(http: httpx.AsyncClient) -> NotionSchema:
    """Ensures the Notion database has the properties this bot writes."""
    properties = await _database_properties(http)
    title_property = _find_database_property(properties, "title", TITLE_PROPERTY_CANDIDATES)

    updates = {}
    created_property = _ensure_database_property(
        properties, updates, CREATED_PROPERTY, "date", {"date": {}}
    )
    tags_property = _ensure_database_property(
        properties, updates, TAGS_PROPERTY, "multi_select", {"multi_select": {}}
    )
    day_property = _ensure_database_property(
        properties, updates, DAY_PROPERTY, "select", {"select": {}}
    )
    source_property = _ensure_database_property(
        properties,
        updates,
        SOURCE_PROPERTY,
        "select",
        {"select": {"options": [{"name": name} for name in SOURCE_OPTIONS]}},
    )
    _ensure_select_options(properties, updates, source_property, SOURCE_OPTIONS)
    telegram_chat_id_property = _ensure_database_property(
        properties, updates, TELEGRAM_CHAT_ID_PROPERTY, "number", {"number": {}}
    )
    telegram_message_id_property = _ensure_database_property(
        properties, updates, TELEGRAM_MESSAGE_ID_PROPERTY, "number", {"number": {}}
    )
    source_message_url_property = _ensure_database_property(
        properties, updates, SOURCE_MESSAGE_URL_PROPERTY, "url", {"url": {}}
    )
    original_text_property = _ensure_database_property(
        properties, updates, ORIGINAL_TEXT_PROPERTY, "rich_text", {"rich_text": {}}
    )
    voice_file_unique_id_property = _ensure_database_property(
        properties, updates, VOICE_FILE_UNIQUE_ID_PROPERTY, "rich_text", {"rich_text": {}}
    )
    audio_duration_property = _ensure_database_property(
        properties, updates, AUDIO_DURATION_PROPERTY, "number", {"number": {}}
    )
    audio_file_size_property = _ensure_database_property(
        properties, updates, AUDIO_FILE_SIZE_PROPERTY, "number", {"number": {}}
    )
    source_text_hash_property = _ensure_database_property(
        properties, updates, SOURCE_TEXT_HASH_PROPERTY, "rich_text", {"rich_text": {}}
    )

    if updates:
        await _request_with_retry(
            http,
            "patch",
            f"{API}/databases/{settings.notion_database_id}",
            json={"properties": updates},
        )

    return NotionSchema(
        title=title_property,
        created=created_property,
        tags=tags_property,
        day=day_property,
        source=source_property,
        telegram_chat_id=telegram_chat_id_property,
        telegram_message_id=telegram_message_id_property,
        source_message_url=source_message_url_property,
        original_text=original_text_property,
        voice_file_unique_id=voice_file_unique_id_property,
        audio_duration=audio_duration_property,
        audio_file_size=audio_file_size_property,
        source_text_hash=source_text_hash_property,
    )


def _combine_tags(
    existing_page: dict | None,
    new_tags: list[str],
    tags_property: str,
) -> list[dict]:
    """Merges page tags with new ones, always prepends Daily, no duplicates."""
    existing = []
    if existing_page:
        existing = [
            t["name"]
            for t in existing_page["properties"].get(tags_property, {}).get("multi_select", [])
        ]
    all_tags = ["Daily"] + [t for t in (existing + new_tags) if t != "Daily"]
    # deduplicate while preserving order
    seen = set()
    unique = []
    for t in all_tags:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return [{"name": t} for t in unique]


def _text_chunks(value: object) -> list[str]:
    text = str(value)
    if not text:
        return [""]
    return [
        text[start:start + NOTION_TEXT_CHUNK_SIZE]
        for start in range(0, len(text), NOTION_TEXT_CHUNK_SIZE)
    ]


def _rich_text(value: object) -> list[dict]:
    return [{"text": {"content": chunk}} for chunk in _text_chunks(value)]


def _rich_text_property(value: object) -> dict:
    return {"rich_text": _rich_text(value)}


def _number_property(value: object) -> dict:
    return {"number": int(value)}


def _metadata_properties(schema: NotionSchema, metadata: dict | None) -> dict:
    if not metadata:
        return {}

    properties = {}
    if metadata.get("source"):
        properties[schema.source] = {"select": {"name": str(metadata["source"])}}
    if metadata.get("telegram_chat_id") is not None:
        properties[schema.telegram_chat_id] = _number_property(metadata["telegram_chat_id"])
    if metadata.get("telegram_message_id") is not None:
        properties[schema.telegram_message_id] = _number_property(metadata["telegram_message_id"])
    if metadata.get("source_message_url"):
        properties[schema.source_message_url] = {"url": metadata["source_message_url"]}
    if metadata.get("voice_file_unique_id"):
        properties[schema.voice_file_unique_id] = _rich_text_property(metadata["voice_file_unique_id"])
    if metadata.get("audio_duration") is not None:
        properties[schema.audio_duration] = _number_property(metadata["audio_duration"])
    if metadata.get("audio_file_size") is not None:
        properties[schema.audio_file_size] = _number_property(metadata["audio_file_size"])
    if metadata.get("source_text_hash"):
        properties[schema.source_text_hash] = _rich_text_property(metadata["source_text_hash"])
    return properties


def _metadata_filter(schema: NotionSchema, metadata: dict | None) -> dict | None:
    if not metadata:
        return None

    source = metadata.get("source")
    if source == "text" and metadata.get("source_text_hash"):
        return {
            "and": [
                {"property": schema.source, "select": {"equals": "text"}},
                {
                    "property": schema.source_text_hash,
                    "rich_text": {"equals": metadata["source_text_hash"]},
                },
            ]
        }

    if source == "voice" and metadata.get("voice_file_unique_id"):
        filters = [
            {"property": schema.source, "select": {"equals": "voice"}},
            {
                "property": schema.voice_file_unique_id,
                "rich_text": {"equals": metadata["voice_file_unique_id"]},
            },
        ]
        if metadata.get("audio_duration") is not None:
            filters.append({
                "property": schema.audio_duration,
                "number": {"equals": int(metadata["audio_duration"])},
            })
        if metadata.get("audio_file_size") is not None:
            filters.append({
                "property": schema.audio_file_size,
                "number": {"equals": int(metadata["audio_file_size"])},
            })
        return {"and": filters}

    return None


async def _find_duplicate_page(
    http: httpx.AsyncClient,
    schema: NotionSchema,
    metadata: dict | None,
) -> dict | None:
    duplicate_filter = _metadata_filter(schema, metadata)
    if not duplicate_filter:
        return None

    resp = await _request_with_retry(
        http,
        "post",
        f"{API}/databases/{settings.notion_database_id}/query",
        json={
            "filter": duplicate_filter,
            "page_size": 1,
        },
    )
    results = resp.json().get("results", [])
    return results[0] if results else None


def _split_paragraphs(text: str) -> list[str]:
    """Splits text into semantic paragraphs on blank lines, dropping empties."""
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text)]
    paragraphs = [paragraph for paragraph in paragraphs if paragraph]
    return paragraphs or [""]


def _paragraph_blocks(text: str) -> list[dict]:
    return [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": _rich_text(chunk)},
        }
        for paragraph in _split_paragraphs(text)
        for chunk in _text_chunks(paragraph)
    ]


async def get_today_pages() -> list[dict]:
    today = _today_date()
    return await get_diary_pages(start_date=today, end_date=today)


def _database_query_filter(
    schema: NotionSchema,
    start_date: str | None = None,
    end_date: str | None = None,
    source: str | None = None,
) -> dict | None:
    filters = []
    if start_date:
        filters.append({"property": schema.created, "date": {"on_or_after": start_date}})
    if end_date:
        filters.append({"property": schema.created, "date": {"on_or_before": end_date}})
    if source:
        filters.append({"property": schema.source, "select": {"equals": source}})

    if not filters:
        return None
    if len(filters) == 1:
        return filters[0]
    return {"and": filters}


async def get_diary_pages(
    start_date: str | None = None,
    end_date: str | None = None,
    source: str | None = None,
) -> list[dict]:
    """Returns diary database pages matching optional date/source filters."""
    async with httpx.AsyncClient(timeout=NOTION_TIMEOUT) as http:
        schema = await ensure_database_schema(http)
        query_filter = _database_query_filter(schema, start_date, end_date, source)
        pages = []
        cursor = None

        while True:
            payload = {
                "page_size": 100,
                "sorts": [{"property": schema.created, "direction": "ascending"}],
            }
            if query_filter:
                payload["filter"] = query_filter
            if cursor:
                payload["start_cursor"] = cursor

            resp = await _request_with_retry(
                http,
                "post",
                f"{API}/databases/{settings.notion_database_id}/query",
                json=payload,
            )
            data = resp.json()
            pages.extend(data.get("results", []))
            if not data.get("has_more"):
                return pages
            cursor = data.get("next_cursor")


async def get_page_text(page_id: str) -> str:
    """Fetches all text blocks from a Notion page and returns them as plain text."""
    blocks = []
    async with httpx.AsyncClient(timeout=NOTION_TIMEOUT) as http:
        cursor = None
        while True:
            url = f"{API}/blocks/{page_id}/children?page_size=100"
            if cursor:
                url = f"{url}&start_cursor={cursor}"
            resp = await _request_with_retry(http, "get", url)
            data = resp.json()
            blocks.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
    lines = []
    for block in blocks:
        block_type = block.get("type")
        rich_text = block.get(block_type, {}).get("rich_text", [])
        text = "".join(t["plain_text"] for t in rich_text)
        if text:
            lines.append(text)
    return "\n\n".join(lines)


async def _verify_page_created(http: httpx.AsyncClient, page_id: str) -> None:
    resp = await _request_with_retry(
        http,
        "get",
        f"{API}/pages/{page_id}",
    )
    page = resp.json()
    if page.get("id") != page_id or page.get("archived"):
        raise RuntimeError(f"Notion saved page verification failed for {page_id}")


async def create_page(
    entry_title: str,
    entry_text: str,
    entry_tags: list[str],
    metadata: dict | None = None,
    entry_date: str | None = None,
    allow_duplicate: bool = False,
    original_text: str | None = None,
) -> SaveResult:
    async with httpx.AsyncClient(timeout=NOTION_TIMEOUT) as http:
        schema = await ensure_database_schema(http)
        duplicate = None if allow_duplicate else await _find_duplicate_page(http, schema, metadata)
        if duplicate:
            page_id = duplicate["id"]
            await _verify_page_created(http, page_id)
            return SaveResult(page_id=page_id, created=False)

        notion_entry_date = _notion_entry_date(entry_date)
        properties = {
            schema.title: {"title": _rich_text(entry_title)},
            schema.created: {"date": {"start": notion_entry_date}},
            schema.day: {"select": {"name": notion_entry_date}},
            schema.tags: {
                "multi_select": _combine_tags(None, entry_tags, schema.tags),
            },
            **_metadata_properties(schema, metadata),
        }
        if original_text is not None:
            properties[schema.original_text] = _rich_text_property(original_text)
        resp = await _request_with_retry(
            http,
            "post",
            f"{API}/pages",
            json={
                "parent": {"database_id": settings.notion_database_id},
                "properties": properties,
                "children": [
                    {
                        "object": "block",
                        "type": "heading_3",
                        "heading_3": {"rich_text": _rich_text(entry_title)},
                    },
                    *_paragraph_blocks(entry_text),
                ],
            },
        )
        page = resp.json()
        page_id = page.get("id")
        if not page_id:
            raise RuntimeError("Notion create page response did not include page id")
        await _verify_page_created(http, page_id)
        return SaveResult(page_id=page_id, created=True)


async def get_week_pages() -> list[dict]:
    """Returns all diary pages created in the last 7 days, oldest first."""
    today = diary_today()
    week_ago = today - timedelta(days=6)
    return await get_diary_pages(start_date=week_ago.isoformat(), end_date=today.isoformat())


async def save_entry(
    entry_title: str,
    entry_text: str,
    entry_tags: list[str],
    metadata: dict | None = None,
    entry_date: str | None = None,
    allow_duplicate: bool = False,
    original_text: str | None = None,
) -> SaveResult:
    """Creates and verifies a separate Notion database row for every diary entry."""
    return await create_page(
        entry_title,
        entry_text,
        entry_tags,
        metadata,
        entry_date,
        allow_duplicate=allow_duplicate,
        original_text=original_text,
    )
