"""Retrospective rebuild of the author profile (long-term memory).

Walks every saved diary note oldest-first and refreshes the profile one note at
a time, exactly like the per-message refresh does: each step feeds one note plus
the profile accumulated so far back into the extractor, and its output becomes
the input of the next step.

The pass is deliberately boring and safe:
- strictly sequential — one note, one AI request, never concurrent;
- single-flight — a second pass is rejected while one is in flight;
- fault-isolated — a note that fails to read or extract leaves the accumulated
  points untouched and the walk continues;
- circuit-broken — a run aborts once notes fail back-to-back, instead of burning
  one doomed request per remaining note;
- observable — `on_progress` fires after every note so the caller can persist
  points incrementally and render a progress bar.
"""

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass

from services import roast
from services.memory import MemoryItem
from services.notion import CREATED_PROPERTY, extract_page_title, get_diary_pages, get_page_text

logger = logging.getLogger(__name__)

# Pause between notes so a long pass does not hammer Notion or the AI provider.
STEP_DELAY_SECONDS = 0.5
# Abort once this many notes fail back-to-back: a bad key or a rate-limit wall
# should not cost one request per remaining note.
MAX_CONSECUTIVE_FAILURES = 3
PROGRESS_BAR_WIDTH = 12
PROGRESS_BAR_FILLED = "▰"
PROGRESS_BAR_EMPTY = "▱"

PROCESSED = "processed"
SKIPPED = "skipped"
FAILED = "failed"

_run_lock = asyncio.Lock()


class RebuildAlreadyRunning(RuntimeError):
    """Raised when a rebuild is requested while another one is still running."""


@dataclass(frozen=True)
class RebuildProgress:
    total: int
    processed: int
    skipped: int
    failed: int
    points: list[MemoryItem]
    aborted_reason: str | None = None

    @property
    def handled(self) -> int:
        """Notes the walk is done with, however they turned out."""
        return self.processed + self.skipped + self.failed


def is_running() -> bool:
    return _run_lock.locked()


def render_progress_bar(handled: int, total: int) -> str:
    if total <= 0:
        return f"{PROGRESS_BAR_EMPTY * PROGRESS_BAR_WIDTH} 0% · 0/0 notes"
    ratio = min(1.0, max(0.0, handled / total))
    filled = round(ratio * PROGRESS_BAR_WIDTH)
    bar = PROGRESS_BAR_FILLED * filled + PROGRESS_BAR_EMPTY * (PROGRESS_BAR_WIDTH - filled)
    return f"{bar} {round(ratio * 100)}% · {handled}/{total} notes"


async def _pause() -> None:
    """Rate-limit breather between notes. Its own function so tests can drop it."""
    await asyncio.sleep(STEP_DELAY_SECONDS)


def _page_date(page: dict) -> str:
    created = page.get("properties", {}).get(CREATED_PROPERTY, {}).get("date") or {}
    return (created.get("start") or "")[:10]


def _page_title(page: dict) -> str:
    with suppress(Exception):
        return extract_page_title(page).strip()
    return ""


def _note_text(page: dict, body: str) -> str:
    """Compose what the extractor sees. The date and title are prepended so the
    model can tell a passing phase from a durable trait while reading history."""
    body = (body or "").strip()
    if not body:
        return ""
    header = " · ".join(part for part in (_page_date(page), _page_title(page)) if part)
    return f"{header}\n\n{body}" if header else body


async def _rebuild_step(
    page: dict,
    points: list[MemoryItem],
    focus: str | None,
    language: str | None,
) -> tuple[str, list[MemoryItem]]:
    """Fold one note into the profile. Never raises: on failure the caller keeps
    the points it already had and the walk moves on."""
    page_id = page.get("id")
    try:
        note = _note_text(page, await get_page_text(page_id))
    except Exception:
        logger.exception("Profile rebuild could not read Notion page %s", page_id)
        return FAILED, points

    if not note:
        return SKIPPED, points

    try:
        return PROCESSED, await roast.extract_profile_points(note, points, focus=focus, language=language)
    except Exception:
        logger.exception("Profile rebuild could not extract points from page %s", page_id)
        return FAILED, points


async def _report(on_progress, progress: RebuildProgress) -> None:
    if on_progress is None:
        return
    try:
        await on_progress(progress)
    except Exception:
        logger.exception("Profile rebuild progress callback failed")


async def rebuild_profile(
    focus: str | None,
    existing_points: list[MemoryItem],
    on_progress=None,
    language: str | None = None,
) -> RebuildProgress:
    """Rebuild the author profile from every saved diary note, oldest first.

    `existing_points` seeds the pass: an empty list builds the profile from
    scratch, a populated one gets corrected note by note. `focus` is the user's
    priority hint for this pass. Returns the final progress snapshot.
    """
    if is_running():
        raise RebuildAlreadyRunning("A profile rebuild is already running")

    async with _run_lock:
        pages = await get_diary_pages()
        total = len(pages)
        points = list(existing_points)
        counts = {PROCESSED: 0, SKIPPED: 0, FAILED: 0}
        consecutive_failures = 0
        aborted_reason = None

        def snapshot() -> RebuildProgress:
            return RebuildProgress(
                total=total,
                processed=counts[PROCESSED],
                skipped=counts[SKIPPED],
                failed=counts[FAILED],
                points=list(points),
                aborted_reason=aborted_reason,
            )

        logger.info("Profile rebuild starting over %d note(s), focus=%r", total, focus or "")
        await _report(on_progress, snapshot())

        for index, page in enumerate(pages):
            if index:
                await _pause()

            outcome, points = await _rebuild_step(page, points, focus, language)
            counts[outcome] += 1
            consecutive_failures = consecutive_failures + 1 if outcome == FAILED else 0
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                aborted_reason = (
                    f"{consecutive_failures} notes in a row failed at note {index + 1}/{total}"
                )

            await _report(on_progress, snapshot())
            if aborted_reason:
                logger.warning("Profile rebuild aborted: %s", aborted_reason)
                break

        result = snapshot()
        logger.info(
            "Profile rebuild finished: %d processed, %d skipped, %d failed, %d fact(s)",
            result.processed,
            result.skipped,
            result.failed,
            len(result.points),
        )
        return result
