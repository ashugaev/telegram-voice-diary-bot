from config import settings
from services.ai import create_chat_client
from services.notion import extract_page_title, get_page_text, get_today_pages, get_week_pages
from services.stats import build_period_stats_from_pages, format_daily_stats, format_weekly_stats

openai_client = create_chat_client()

SUMMARY_PROMPT = """Ты — чёткий братан автора, помогаешь ему оглянуться на прошедший день.
Ниже — записи из его дневника за сегодня.
Собери короткую и тёплую выжимку дня на русском (2-4 предложения) в живом пацанском стиле:
подсвети главные события, настроение и заметные мысли. Будь на его стороне, по-доброму, без подлизывания и канцелярщины.
Без буллет-поинтов — пиши одним коротким абзацем."""


async def _fetch_page_text(page_id: str) -> str:
    """Fetches all text blocks from a Notion page and returns them as plain text."""
    return await get_page_text(page_id)


WEEKLY_PROMPT = """Ты — чёткий братан автора, помогаешь ему оглянуться на прошедшую неделю.
Ниже — все записи из дневника за последние 7 дней.

Собери разбор недели на русском в живом пацанском стиле, по-братски и на его стороне:
1. Тёплый живой абзац (3-5 предложений), который ловит дух недели.
2. Список из 5-7 хайлайтов, которые реально зацепили. Каждый пункт — короткий буллет.

Без заголовков. Пиши по-человечески и тепло, будто рассказываешь другу про важную неделю. Без подлизывания и канцелярщины."""


async def generate_weekly_report() -> str | None:
    """Generates a GPT weekly report. Returns None if no pages found."""
    pages = await get_week_pages()
    if not pages:
        return None

    sections = []
    for page in pages:
        page_title = extract_page_title(page)
        page_text = await _fetch_page_text(page["id"])
        if page_text.strip():
            sections.append(f"### {page_title}\n{page_text}")

    if not sections:
        return None

    full_text = "\n\n".join(sections)
    response = await openai_client.chat.completions.create(
        model=settings.summary_model,
        max_completion_tokens=1024,
        messages=[
            {"role": "system", "content": WEEKLY_PROMPT},
            {"role": "user", "content": full_text},
        ],
    )
    stats = format_weekly_stats(build_period_stats_from_pages(pages))
    return f"{stats}\n\n{response.choices[0].message.content}"


async def generate_daily_summary() -> str | None:
    """Generates a GPT summary of today's diary entries. Returns None if no entries exist."""
    pages = await get_today_pages()
    if not pages:
        return None

    sections = []
    for page in pages:
        page_title = extract_page_title(page)
        page_text = await _fetch_page_text(page["id"])
        if page_text.strip():
            sections.append(f"### {page_title}\n{page_text}")

    if not sections:
        return None

    full_text = "\n\n".join(sections)

    response = await openai_client.chat.completions.create(
        model=settings.summary_model,
        max_completion_tokens=512,
        messages=[
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": full_text},
        ],
    )
    stats = format_daily_stats(build_period_stats_from_pages(pages))
    return f"{stats}\n\n{response.choices[0].message.content}"
