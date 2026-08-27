from config import settings
from services.ai import create_chat_client
from services.i18n import ai_language, normalize_language
from services.notion import extract_page_title, get_page_text, get_today_pages, get_week_pages
from services.stats import build_period_stats_from_pages, format_daily_stats, format_weekly_stats

openai_client = create_chat_client()

SUMMARY_PROMPTS = {
    "en": """You are the author's clear, close friend helping him look back at the day.
Below are today's diary entries.
Write a short, warm daily recap in English (2-4 sentences), direct and human:
surface the main events, mood, and notable thoughts. Stay on his side, kind but not flattering or corporate.
No bullet points. Write one short paragraph.""",
    "ru": """Ты — чёткий братан автора, помогаешь ему оглянуться на прошедший день.
Ниже — записи из его дневника за сегодня.
Собери короткую и тёплую выжимку дня на русском (2-4 предложения) в живом пацанском стиле:
подсвети главные события, настроение и заметные мысли. Будь на его стороне, по-доброму, без подлизывания и канцелярщины.
Без буллет-поинтов — пиши одним коротким абзацем.""",
}


async def _fetch_page_text(page_id: str) -> str:
    """Fetches all text blocks from a Notion page and returns them as plain text."""
    return await get_page_text(page_id)


WEEKLY_PROMPTS = {
    "en": """You are the author's clear, close friend helping him look back at the week.
Below are all diary entries from the last 7 days.
Entries marked ⭐ were marked important by the author.

Write a weekly review in English, direct, warm, and on his side:
1. One warm paragraph (3-5 sentences) that captures the week.
2. A list of 5-7 highlights. Include every ⭐ entry first, then add whatever else truly stood out. Each item is a short bullet.

No headings. Write like a real friend telling him what mattered this week. No flattery. No corporate tone.""",
    "ru": """Ты — чёткий братан автора, помогаешь ему оглянуться на прошедшую неделю.
Ниже — все записи из дневника за последние 7 дней.
Записи, помеченные ⭐, чел сам отметил как важные.

Собери разбор недели на русском в живом пацанском стиле, по-братски и на его стороне:
1. Тёплый живой абзац (3-5 предложений), который ловит дух недели.
2. Список из 5-7 хайлайтов — сначала все записи с ⭐, потом добавь остальное, что реально зацепило. Каждый пункт — короткий буллет.

Без заголовков. Пиши по-человечески и тепло, будто рассказываешь другу про важную неделю. Без подлизывания и канцелярщины.""",
}


def _localized_prompt(prompt: str, language: str | None) -> str:
    return f"{prompt}\n\nWrite the report in {ai_language(language)}."


async def generate_weekly_report(language: str | None = None) -> str | None:
    """Generates a GPT weekly highlight report. Returns None if no pages found."""
    language = normalize_language(language)
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
            {"role": "system", "content": _localized_prompt(WEEKLY_PROMPTS[language], language)},
            {"role": "user", "content": full_text},
        ],
    )
    stats = format_weekly_stats(build_period_stats_from_pages(pages, language), language)
    return f"{stats}\n\n{response.choices[0].message.content}"


async def generate_daily_summary(language: str | None = None) -> str | None:
    """Generates a GPT summary of today's diary entries. Returns None if no entries exist."""
    language = normalize_language(language)
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
            {"role": "system", "content": _localized_prompt(SUMMARY_PROMPTS[language], language)},
            {"role": "user", "content": full_text},
        ],
    )
    stats = format_daily_stats(build_period_stats_from_pages(pages, language), language)
    return f"{stats}\n\n{response.choices[0].message.content}"
