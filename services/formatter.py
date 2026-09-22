import json
import logging

from typing import Any

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
- "tags": tags matching author rules or explicitly named by user, otherwise []

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
- "tags": теги по правилам автора или явно названные пользователем, иначе []

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
- "tags": tags matching author rules or explicitly named by user, otherwise []

Do not return the full note text.
Return valid JSON only. No markdown. No explanation.""",
    "ru": """Верни JSON для дневниковой заметки:
- "title": короткий заголовок 3-5 слов, без кавычек
- "tags": теги по правилам автора или явно названные пользователем, иначе []

Не возвращай полный текст заметки.
Только валидный JSON, без markdown и пояснений.""",
}

EDIT_DRAFT_PROMPTS = {
    "en": """You edit a diary note draft according to the user's instructions.
Return JSON for the updated diary note:
- "title": short 3-5 word title, no quotes
- "text": updated note text, split into meaningful paragraphs
- "tags": updated list of tags

Rules:
- Apply the user's instructions precisely (e.g. change title, edit text, add/remove tags).
- If the instruction only asks to change title, keep text and tags intact.
- If the instruction only asks to change tags, keep title and text intact.
- If the instruction asks to edit text, update text accordingly while keeping the author's style.
- Follow author behavior rules if provided.
- Return valid JSON only. No markdown. No explanation.""",
    "ru": """Ты редактируешь черновик дневниковой заметки по указаниям пользователя.
Верни JSON для обновленной дневниковой заметки:
- "title": короткий заголовок 3-5 слов, без кавычек
- "text": обновленный текст заметки, разбитый на смысловые абзацы
- "tags": обновленный список тегов

Правила:
- Точно примени указания пользователя (например: изменить заголовок, поправить текст, добавить или убрать теги).
- Если указание касается только заголовка — сохрани текст и теги без изменений.
- Если указание касается только тегов — сохрани заголовок и текст без изменений.
- Если указание касается текста — обнови текст согласно запросу, сохраняя авторский стиль.
- Соблюдай правила автора, если они указаны.
- Только валидный JSON, без markdown и пояснений.""",
}

SYSTEM_PROMPT = SYSTEM_PROMPTS["ru"]
METADATA_PROMPT = METADATA_PROMPTS["ru"]
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


def _extract_rule_strings(rules: list[Any] | None) -> list[str]:
    if not rules:
        return []
    result = []
    for item in rules:
        text = getattr(item, "text", None)
        if text is None and isinstance(item, str):
            text = item
        text = str(text or "").strip()
        if text:
            result.append(text)
    return result


def _with_rules(prompt: str, rules: list[str], language: str = "ru") -> str:
    if not rules:
        return prompt
    header = "Author behavior rules:" if language == "en" else "Правила автора:"
    rules_text = "\n".join(f"- {rule}" for rule in rules)
    return f"{prompt}\n\n{header}\n{rules_text}"


def _with_language(prompt: str, language: str) -> str:
    return f"{prompt}\n\n{LANGUAGE_INSTRUCTION.format(language=ai_language(language))}"


async def format_entry(
    transcription: str,
    language: str | None = None,
    rules: list[Any] | None = None,
) -> tuple[str, str, list[str]]:
    lang = normalize_language(language) if language else "ru"
    rule_strs = _extract_rule_strings(rules)
    if len(transcription) > LONG_TRANSCRIPTION_CHAR_LIMIT:
        base_prompt = _with_language(METADATA_PROMPTS[lang], lang) if language else METADATA_PROMPT
        system_prompt = _with_rules(base_prompt, rule_strs, lang)
        response = await client.chat.completions.create(
            model=settings.formatter_model,
            max_completion_tokens=METADATA_MAX_COMPLETION_TOKENS,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": transcription},
            ],
        )
        data = _parse_json(response.choices[0].message.content or "")
        title = str(data.get("title") or "").strip() or _fallback_title(transcription, lang)
        return title, transcription, _coerce_tags(data.get("tags"))

    base_prompt = _with_language(SYSTEM_PROMPTS[lang], lang) if language else SYSTEM_PROMPT
    system_prompt = _with_rules(base_prompt, rule_strs, lang)
    response = await client.chat.completions.create(
        model=settings.formatter_model,
        max_completion_tokens=FORMATTER_MAX_COMPLETION_TOKENS,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": transcription},
        ],
    )
    data = _parse_json(response.choices[0].message.content or "")
    title = str(data.get("title") or "").strip() or _fallback_title(transcription, lang)
    text = str(data.get("text") or "").strip() or transcription
    return title, text, _coerce_tags(data.get("tags"))


async def edit_entry_draft(
    instruction: str,
    current_title: str,
    current_text: str,
    current_tags: list[str],
    raw_text: str = "",
    language: str | None = None,
    rules: list[Any] | None = None,
) -> tuple[str, str, list[str]]:
    lang = normalize_language(language) if language else "ru"
    rule_strs = _extract_rule_strings(rules)
    base_prompt = _with_language(EDIT_DRAFT_PROMPTS[lang], lang) if language else EDIT_DRAFT_PROMPTS["ru"]
    system_prompt = _with_rules(base_prompt, rule_strs, lang)

    user_content = (
        f"Текущий черновик:\n"
        f"Заголовок: {current_title}\n"
        f"Теги: {json.dumps(current_tags, ensure_ascii=False)}\n"
        f"Текст:\n{current_text}\n\n"
        + (f"Исходный распознанный текст:\n{raw_text}\n\n" if raw_text and raw_text != current_text else "")
        + f"Указание пользователя:\n{instruction}"
    ) if lang == "ru" else (
        f"Current draft:\n"
        f"Title: {current_title}\n"
        f"Tags: {json.dumps(current_tags, ensure_ascii=False)}\n"
        f"Text:\n{current_text}\n\n"
        + (f"Original raw text:\n{raw_text}\n\n" if raw_text and raw_text != current_text else "")
        + f"User instruction:\n{instruction}"
    )

    response = await client.chat.completions.create(
        model=settings.formatter_model,
        max_completion_tokens=FORMATTER_MAX_COMPLETION_TOKENS,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    data = _parse_json(response.choices[0].message.content or "")
    new_title = str(data.get("title") or "").strip() or current_title
    new_text = str(data.get("text") or "").strip() or current_text
    new_tags = _coerce_tags(data.get("tags")) if "tags" in data else current_tags
    return new_title, new_text, new_tags
