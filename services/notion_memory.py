"""Two-way sync of the bot's long-term memory with Notion.

Three pages sit next to the diary database, inside the same parent page, so the
memory is readable and editable in the same place as the notes:

  "Memory — Author profile"  durable facts about the author
  "Memory — Bot rules"       standing behavior rules the author dictated
  "Memory — Chronology"      dated events the author lived through

A page edited by hand is the source of truth: the author owns their memory, and
what they typed into Notion outranks what the bot stored. The caller passes the
list it last saw on the page (the mirror) alongside the local list, which is what
separates a manual edit from the bot's own last write:

  page == local            nothing to do
  page != mirror           the page was edited by hand — adopt it
  page == mirror           the page is stale — rewrite it from local

Best-effort by contract — callers swallow failures. A broken sync must never
break the diary flow.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from config import settings
from services.notion import (
    API,
    NOTION_TIMEOUT,
    _request_with_retry,
    _rich_text,
)

logger = logging.getLogger(__name__)

AUTHOR_MEMORY_PAGE_TITLE = "Memory — Author profile"
BOT_MEMORY_PAGE_TITLE = "Memory — Bot rules"
CHRONOLOGY_MEMORY_PAGE_TITLE = "Memory — Chronology"
# Notion rejects a children payload longer than this.
NOTION_CHILDREN_CHUNK_SIZE = 100

# Resolving a page id costs two requests, and syncing now runs before every read
# of memory, so ids are cached for the process and dropped on any failure.
_page_ids: dict[str, str] = {}


@dataclass(frozen=True)
class MemorySync:
    """Outcome of one sync: the list both sides now hold, and whether it came
    from a hand-edited page instead of local state."""

    items: list[str]
    adopted: bool


def _header_line(count: int, label: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"Updated {stamp} · {count} {label}"


def _memory_blocks(items: list[str], label: str) -> list[dict]:
    return [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": _rich_text(_header_line(len(items), label))},
        },
        *(
            {
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": _rich_text(item)},
            }
            for item in items
        ),
    ]


async def _page_children(http: httpx.AsyncClient, block_id: str) -> list[dict]:
    blocks = []
    cursor = None
    while True:
        url = f"{API}/blocks/{block_id}/children?page_size=100"
        if cursor:
            url = f"{url}&start_cursor={cursor}"
        data = (await _request_with_retry(http, "get", url)).json()
        blocks.extend(data.get("results", []))
        if not data.get("has_more"):
            return blocks
        cursor = data.get("next_cursor")


async def _memory_parent_page_id(http: httpx.AsyncClient) -> str:
    """The page holding the diary database — memory pages become its children."""
    resp = await _request_with_retry(
        http,
        "get",
        f"{API}/databases/{settings.notion_database_id}",
    )
    parent = resp.json().get("parent") or {}
    page_id = parent.get("page_id")
    if not page_id:
        raise RuntimeError(
            "Notion memory needs the diary database to live inside a page, "
            f"but its parent is {parent.get('type')!r}"
        )
    return page_id


async def _find_or_create_memory_page(
    http: httpx.AsyncClient,
    parent_page_id: str,
    title: str,
    label: str,
) -> str:
    for block in await _page_children(http, parent_page_id):
        if block.get("type") == "child_page" and block["child_page"].get("title") == title:
            return block["id"]

    resp = await _request_with_retry(
        http,
        "post",
        f"{API}/pages",
        json={
            "parent": {"page_id": parent_page_id},
            "properties": {"title": {"title": _rich_text(title)}},
            "children": _memory_blocks([], label),
        },
    )
    page_id = resp.json().get("id")
    if not page_id:
        raise RuntimeError(f'Notion create page response for "{title}" had no page id')
    logger.info('Created Notion memory page "%s" (%s)', title, page_id)
    return page_id


def _listed_items(blocks: list[dict]) -> list[str]:
    """The items a memory page currently shows. The header paragraph carries a
    timestamp, so only the bullets are compared."""
    return [
        "".join(part["plain_text"] for part in block["bulleted_list_item"].get("rich_text", []))
        for block in blocks
        if block.get("type") == "bulleted_list_item"
    ]


async def _replace_page_body(
    http: httpx.AsyncClient,
    page_id: str,
    blocks: list[dict],
    existing: list[dict],
) -> None:
    for block in existing:
        await _request_with_retry(http, "delete", f"{API}/blocks/{block['id']}")
    for start in range(0, len(blocks), NOTION_CHILDREN_CHUNK_SIZE):
        await _request_with_retry(
            http,
            "patch",
            f"{API}/blocks/{page_id}/children",
            json={"children": blocks[start:start + NOTION_CHILDREN_CHUNK_SIZE]},
        )


def forget_page_ids() -> None:
    """Drops every cached page id, so the next sync resolves them again."""
    _page_ids.clear()


async def _memory_page_id(http: httpx.AsyncClient, title: str, label: str) -> str:
    cached = _page_ids.get(title)
    if cached:
        return cached
    parent_page_id = await _memory_parent_page_id(http)
    page_id = await _find_or_create_memory_page(http, parent_page_id, title, label)
    _page_ids[title] = page_id
    return page_id


async def _sync_memory_page(
    http: httpx.AsyncClient,
    title: str,
    items: list[str],
    label: str,
    mirror: list[str],
) -> MemorySync:
    """Brings the page and `items` back together, hand edits winning."""
    try:
        page_id = await _memory_page_id(http, title, label)
        existing = await _page_children(http, page_id)
        remote = _listed_items(existing)
        if remote == items:
            return MemorySync(items, False)
        if remote != mirror:
            logger.info('Adopted %d item(s) edited by hand on "%s"', len(remote), title)
            return MemorySync(remote, True)

        await _replace_page_body(http, page_id, _memory_blocks(items, label), existing)
        logger.info('Synced %d item(s) to Notion memory page "%s"', len(items), title)
        return MemorySync(items, False)
    except Exception:
        # A page deleted or renamed under us must be resolved again, not retried
        # forever against a dead id.
        _page_ids.pop(title, None)
        raise


MEMORY_PAGES = (
    (AUTHOR_MEMORY_PAGE_TITLE, "facts"),
    (BOT_MEMORY_PAGE_TITLE, "rules"),
    (CHRONOLOGY_MEMORY_PAGE_TITLE, "events"),
)


async def ensure_memory_pages() -> list[str]:
    """Creates any missing memory page, leaving the content of existing ones
    alone. Run at startup so every page is in Notion before the first sync."""
    async with httpx.AsyncClient(timeout=NOTION_TIMEOUT) as http:
        return [await _memory_page_id(http, title, label) for title, label in MEMORY_PAGES]


async def sync_author_memory(points: list[str], mirror: list[str]) -> MemorySync:
    """Syncs the author profile — the facts the bot knows about the author."""
    async with httpx.AsyncClient(timeout=NOTION_TIMEOUT) as http:
        return await _sync_memory_page(http, AUTHOR_MEMORY_PAGE_TITLE, points, "facts", mirror)


async def sync_bot_memory(rules: list[str], mirror: list[str]) -> MemorySync:
    """Syncs the bot's own memory — the standing behavior rules the author
    dictated. Wired by whoever owns those rules in local state."""
    async with httpx.AsyncClient(timeout=NOTION_TIMEOUT) as http:
        return await _sync_memory_page(http, BOT_MEMORY_PAGE_TITLE, rules, "rules", mirror)


async def sync_chronology_memory(events: list[str], mirror: list[str]) -> MemorySync:
    """Syncs the chronology — the dated events the author lived through."""
    async with httpx.AsyncClient(timeout=NOTION_TIMEOUT) as http:
        return await _sync_memory_page(
            http, CHRONOLOGY_MEMORY_PAGE_TITLE, events, "events", mirror,
        )
