import json
import logging

from config import settings
from services.ai import create_chat_client
from services.i18n import ai_language, normalize_language, t

client = create_chat_client()
logger = logging.getLogger(__name__)

LONG_TRANSCRIPTION_CHAR_LIMIT = 6000
FORMATTER_MAX_COMPLETION_TOKENS = 1024
METADATA_MAX_COMPLETION_TOKENS = 512

SYSTEM_PROMPTS = {
    "en": """Return JSON for a diary note:
- "title": short 3-5 word title, no quotes
- "text": the original text with minimal cleanup, split into meaningful paragraphs
- "tags": only tags the user named explicitly, otherwise []

Rules for "text":
- keep the author's style, wording, and thought order
- do not replace words with synonyms or improve the meaning
- fix only obvious transcription junk, repeats, punctuation, and rough mistakes
- do not add facts, conclusions, names, or details
- if a phrase is short or fragmentary, keep it short
- split text into meaningful paragraphs: new thought, new paragraph; separate paragraphs with a blank line
- do not add headings, captions, lists, numbering, or other labels to paragraphs

Return valid JSON only. No markdown. No explanation.""",
    "ru": """Верни JSON для дневниковой заметки:
- "title": короткий заголовок 3-5 слов, без кавычек
- "text": исходный текст с минимальной правкой, разбитый на смысловые абзацы
- "tags": только явно названные пользователем теги, иначе []

Правила для "text":
- не переписывай стиль, формулировки и порядок мыслей
- не заменяй слова синонимами и не улучшай смысл
- исправляй только очевидный мусор распознавания, повторы, пунктуацию и грубые ошибки
- не добавляй факты, выводы, имена и детали
- если фраза короткая или обрывочная, оставь ее короткой
- разбивай текст на смысловые абзацы: новая мысль — новый абзац, разделяй абзацы пустой строкой
- не добавляй заголовки, подписи, списки, нумерацию или другие метки к абзацам

Только валидный JSON, без markdown и пояснений.""",
}

METADATA_PROMPTS = {
    "en": """Return JSON for a diary note:
- "title": short 3-5 word title, no quotes
- "tags": only tags the user named explicitly, otherwise []

Do not return the full note text.
Return valid JSON only. No markdown. No explanation.""",
    "ru": """Верни JSON для дневниковой заметки:
- "title": короткий заголовок 3-5 слов, без кавычек
- "tags": только явно названные пользователем теги, иначе []

Не возвращай полный текст заметки.
Только валидный JSON, без markdown и пояснений.""",
}

LANGUAGE_INSTRUCTION = "Write title, text, and tags in {language}."


def _fallback_title(transcription: str, language: str | None = None) -> str:
    words = " ".join(transcription.split()).split()
    if not words:
        return t("formatter.untitled", language)
    return " ".join(words[:5]).strip(".,:;!?") or t("formatter.untitled", language)


def _coerce_tags(value) -> list[str]:
    if not isinstance(value, list):
        return []

    tags = []
    for item in value:
        tag = str(item).strip()
        if tag:
            tags.append(tag)
    return tags


def _parse_json(content: str) -> dict:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.warning("Formatter returned invalid JSON; falling back to raw transcription: %s", exc)
        return {}

    if not isinstance(data, dict):
        logger.warning("Formatter returned non-object JSON; falling back to raw transcription")
        return {}
    return data


def _with_language(prompt: str, language: str | None) -> str:
    return f"{prompt}\n\n{LANGUAGE_INSTRUCTION.format(language=ai_language(language))}"


async def format_entry(transcription: str, language: str | None = None) -> tuple[str, str, list[str]]:
    language = normalize_language(language)
    if len(transcription) > LONG_TRANSCRIPTION_CHAR_LIMIT:
        response = await client.chat.completions.create(
            model=settings.formatter_model,
            max_completion_tokens=METADATA_MAX_COMPLETION_TOKENS,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _with_language(METADATA_PROMPTS[language], language)},
                {"role": "user", "content": transcription},
            ],
        )
        data = _parse_json(response.choices[0].message.content or "")
        title = str(data.get("title") or "").strip() or _fallback_title(transcription, language)
        return title, transcription, _coerce_tags(data.get("tags"))

    response = await client.chat.completions.create(
        model=settings.formatter_model,
        max_completion_tokens=FORMATTER_MAX_COMPLETION_TOKENS,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _with_language(SYSTEM_PROMPTS[language], language)},
            {"role": "user", "content": transcription},
        ],
    )
    data = _parse_json(response.choices[0].message.content or "")
    title = str(data.get("title") or "").strip() or _fallback_title(transcription, language)
    text = str(data.get("text") or "").strip() or transcription
    return title, text, _coerce_tags(data.get("tags"))
