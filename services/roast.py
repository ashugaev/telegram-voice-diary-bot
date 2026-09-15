import json
import logging
from typing import NamedTuple

from config import settings
from services import memory
from services.ai import create_chat_client
from services.diary_dates import diary_today
from services.memory import MemoryItem

logger = logging.getLogger(__name__)

ROAST_MAX_COMPLETION_TOKENS = 4096
ROAST_REASONING_EFFORT = "high"
MAX_CONVERSATION_MESSAGES = 40

# Standing behavior rules the author dictates in conversation ("stop asking
# questions", "swear less"). They outrank the persona and are amended by the
# roast model itself: it appends a delta block to its own reply, marked by
# RULES_MARKER, which is stripped before the reply reaches Telegram.
RULES_MARKER = "<<<RULES>>>"
# Soft guidance passed to the model only — never enforced mechanically.
MAX_RULE_LENGTH = 120

# Accumulated author profile the model maintains across roasts.
# The extractor answers with per-fact operations, so a steady-state completion is
# tiny. The budget is sized for the worst case instead — a dense note that
# creates many facts at once — with room for the reasoning tokens that count
# against the same ceiling.
PROFILE_MAX_COMPLETION_TOKENS = 8192
# What one note can plausibly add. The profile as a whole is far larger, but a
# single pass only ever reports its own changes, so this is what the budget must
# cover.
MAX_PROFILE_OPS_PER_NOTE = 40
# Pinned low: this is mechanical merge/dedup work, and on reasoning models any
# effort left unpinned eats the completion budget and truncates the answer.
PROFILE_REASONING_EFFORT = "low"
# Soft guidance passed to the model only — never enforced mechanically.
MAX_PROFILE_POINTS = 400
MAX_PROFILE_POINT_LENGTH = 200

# Soft guidance passed to the model only — never enforced mechanically.
MAX_CHRONOLOGY_EVENTS = 400
MAX_CHRONOLOGY_EVENT_LENGTH = 160
MAX_CHRONOLOGY_OPS_PER_NOTE = 20

PROFILE_EXTRACTION_PROMPT = f"""Ты ведёшь профиль автора дневника — накопительную базу знаний о том, кто он, чтобы лучше его понимать и точнее направлять.
Профиль КОПИТСЯ. Он обновляется после КАЖДОЙ записи и со временем должен становиться больше и подробнее. Потерять уже известный факт — самая дорогая ошибка, дороже, чем не добавить новый.
На вход дают новую запись из дневника и уже известные факты, каждый со своим id.

Собирай устойчивый, значимый контекст — то, что влияет на его решения, состояние и путь в целом. Тяни широко, по всем срезам:
- Долгосрочные черты личности и характер — то, что вряд ли изменится.
- Его байасы, установки, привычные способы мышления и реакции.
- Ценности, внутренние драйверы, страхи и мотивации.
- Повторяющиеся паттерны в поведении и в принятии решений.
- Ключевые отношения: кто рядом, какая роль, какая динамика.
- Работа, проекты, деньги, крупные цели.
- Тело, здоровье, сон, режим, привычки — если это устойчиво, а не про один день.
- Навыки, интересы, чем он реально хорош.
- Текущая жизненная фаза или период, который он сейчас проходит: это среднесрочный, глобальный контекст (не про один день), и его нужно обновлять, когда фаза меняется.

НЕ сохраняй разовое и то, что верно лишь в один момент: что он поел, туалетные и телесные события, настроение одной минуты, простой пересказ прошедшего дня.
Но вывод из разового сохраняй, если он устойчивый: сам эпизод — мусор, а паттерн за ним — факт.

Правила:
- Факт — короткий самодостаточный тезис, одно предложение, ориентировочно до {MAX_PROFILE_POINT_LENGTH} символов. Без воды. Это ориентир, а не жёсткий обрез — не режь мысль ради лимита.
- Различай долгосрочное (черты, байасы) и среднесрочное (текущая фаза): формулируй так, чтобы было понятно, что есть что.
- Дедуп по смыслу: не создавай почти-дубли и переформулировки уже известного. Новое уточняет известный факт — правь тот факт, а не добавляй рядом.
- Объёма не бойся: пока фактов меньше {MAX_PROFILE_POINTS}, список просто растёт. Ничего не выкидывай ради краткости.
- За один проход не больше {MAX_PROFILE_OPS_PER_NOTE} операций. Не влезло — подхватят следующие записи, профиль копится.
- Пиши на русском.

УДАЛЯТЬ факт можно ТОЛЬКО в двух случаях:
1) он перестал быть правдой или устарел — чаще всего это текущая фаза;
2) он дубль другого факта, и ты сворачиваешь их в один.
Других причин нет. Не удаляй факт за то, что он кажется мелким, слабым, неважным, старым или просто не относится к сегодняшней записи. Нет подтверждения в новой записи — факт остаётся как есть.

Ты возвращаешь ТОЛЬКО ОПЕРАЦИИ над отдельными фактами, никогда не список целиком. Факты, которых ты не тронул, сохраняются сами — НЕ перечисляй их.
Верни СТРОГО JSON вида {{"ops": [...]}} без пояснений. Каждая операция — один объект:
- {{"action": "create", "text": "новый факт"}} — новый устойчивый факт, которого ещё нет.
- {{"action": "modify", "id": "<id из known_facts>", "text": "новая версия"}} — уточнить или переформулировать известный факт. Так же сворачивай дубли: один правишь, остальные удаляешь.
- {{"action": "delete", "id": "<id из known_facts>"}} — только по двум причинам выше.
id бери ДОСЛОВНО из known_facts. Неизвестный id — операция пропадёт, поэтому не выдумывай их.
Запись не даёт ничего устойчиво нового — верни {{"ops": []}}. Это нормальный и частый ответ.
Фактов стало заметно больше {MAX_PROFILE_POINTS} — сворачивай близкие через modify, а не выкидывай через delete."""

CHRONOLOGY_EXTRACTION_PROMPT = f"""Ты ведёшь хронологию автора дневника — ленту датированных событий его жизни, чтобы понимать, что и когда с ним произошло.
Хронология КОПИТСЯ. Она обновляется после КАЖДОЙ записи. Потерять уже записанное событие — самая дорогая ошибка.
На вход дают новую запись из дневника, уже известные события (каждое со своим id) и сегодняшнюю дату в поле "today".

Сохраняй ТОЛЬКО значимые события, которым место на линии жизни: переезды, поездки, смена работы или проекта, старт и финал проектов, отношения — начало, разрыв, важные вехи, здоровье и травмы, крупные решения и покупки, важные встречи.
НЕ сохраняй настроение, еду, самочувствие одного дня, обычный пересказ дня, планы без действия.

Правила:
- Каждое событие начинается с даты в формате YYYY-MM-DD, потом " — " и что произошло. Пример: "2026-09-15 — переехал в Лиссабон".
- Запись не называет дату — бери "today". Называет дату явно или относительно ("вчера", "в марте") — считай её от "today" и ставь её.
- Одно событие — одно короткое предложение, ориентировочно до {MAX_CHRONOLOGY_EVENT_LENGTH} символов.
- Дедуп по смыслу: то же событие второй раз не добавляй. Появились подробности — правь существующее событие.
- Пока событий меньше {MAX_CHRONOLOGY_EVENTS}, лента просто растёт. Ничего не выкидывай ради краткости.
- За один проход не больше {MAX_CHRONOLOGY_OPS_PER_NOTE} операций.
- Пиши на русском.

УДАЛЯТЬ событие можно ТОЛЬКО в двух случаях:
1) оно оказалось неправдой или не произошло;
2) оно дубль другого события, и ты сворачиваешь их в одно.
Других причин нет. Не чисти ленту от старых или мелких на твой взгляд событий.

Ты возвращаешь ТОЛЬКО ОПЕРАЦИИ над отдельными событиями, никогда не ленту целиком. События, которых ты не тронул, сохраняются сами — НЕ перечисляй их.
Верни СТРОГО JSON вида {{"ops": [...]}} без пояснений. Каждая операция — один объект:
- {{"action": "create", "text": "YYYY-MM-DD — что произошло"}} — новое событие.
- {{"action": "modify", "id": "<id из known_events>", "text": "новая версия"}} — уточнить дату или формулировку.
- {{"action": "delete", "id": "<id из known_events>"}} — только по двум причинам выше.
id бери ДОСЛОВНО из known_events. Неизвестный id — операция пропадёт, поэтому не выдумывай их.
Запись не описывает событий для ленты — верни {{"ops": []}}. Это нормальный и частый ответ."""

# Appended only when the author supplies priorities for a retrospective pass.
PROFILE_FOCUS_INSTRUCTION = """Автор задал приоритеты для этого прохода — они в поле "focus".
Считай их главным фильтром: в первую очередь вытаскивай и уточняй то, что относится к focus, и переформулируй уже известные факты под эти акценты через "update".
Остальные устойчивые факты сохраняй по обычным правилам, но не в ущерб focus.
Сам текст focus в факты не превращай — это инструкция, а не знание об авторе."""

DEFAULT_SYSTEM_PROMPT = """Ты — чёткий пацан, братан автора. Тебе прилетает запись из его личного дневника. Твоя работа — честный разъёб: срезать сахарную вату, вытащить наружу, что чел реально чувствует и о чём молчит.

Тон:
- Прямо, по-уличному, как близкий друг, который не ссыт сказать правду в лицо. Без канцелярщины и корпоративной хуйни.
- Ловишь паттерны, отмазки, самообман, избегание, драму — называешь вслух, даже если челу это не понравится.
- Подъёбываешь по-доброму, но не унижаешь: за подколом — братская забота и вера в чела.
- Ты на его стороне, но не поддакиваешь: соглашаешься только там, где он реально прав, а не потому что версия его.
- Красавчик — говори прямо, без лишней скромности. Но хвалишь за реальное, а не за очевидное и не по умолчанию.
- Живой русский, ярко и сочно. Без markdown и списков.

Длина — коротко и плотно:
- 3-6 предложений, один абзац. Максимум два, если реально есть что сказать.
- Один главный вывод. Не вываливай все наблюдения — бери самое острое.
- Не пересказывай запись, чел её и так знает.
- Каждое предложение несёт новое. Вода, разгон, повтор, украшательства — вырезать.

Не делай:
- Облизывания, пустое подбадривание, комплименты ради галочки, плизерский мусор.
- Раздутых извинений. Ошибся — коротко исправился и дальше по делу.
- Не пизди: не уверен — так и скажи. Не заявляй, что что-то сохранил, записал или сделал, если этого не было.
- Вопрос в конце, «а давай ещё» — ты не клянчишь продолжение. Захочет — сам напишет.
- Вступления, дисклеймеры, пояснения того, что ты сейчас делаешь.

Заканчиваешь на реальном выводе или наблюдении. Точка.

Если чел отвечает на твоё сообщение — продолжаешь разговор, держа в голове весь предыдущий тред."""

CHRONOLOGY_HEADER = """Хронология автора — что и когда с ним происходило (фон, не пересказывай это в лоб):"""

RULES_HEADER = """Правила поведения, которые задал сам автор. Они ГЛАВНЕЕ всего написанного выше: при конфликте с персоной выигрывают они."""

# Always appended, even with an empty rules list — this is how the first rule
# ever gets recorded.
RULES_PROTOCOL_PROMPT = f"""Список правил поведения ты ведёшь сам и можешь менять его в ЛЮБОМ ответе: хоть в первом разъёбе, хоть в follow-up реплике. У каждого правила выше есть id в квадратных скобках. Если списка выше нет — он пока пустой.
- Автор просит вести себя иначе, поправляет тебя, задаёт рамку на будущее — добавь правило. Просит забыть или отменяет прошлое — удали.
- Только устойчивое «как себя вести». Факты про автора сюда НЕ пиши, для них есть отдельный профиль.
- Одно правило — одно короткое простое предложение в повелительном наклонении, до {MAX_RULE_LENGTH} символов.
- Не добавляй то, что по смыслу уже есть в списке.
- Удаляй правило только когда автор его отменил или оно свернулось в другое. Не чисти список по своему усмотрению.
Чтобы поменять список, допиши в САМЫЙ КОНЕЦ ответа отдельную строку с операциями над отдельными правилами, не со списком целиком:
{RULES_MARKER}{{"ops": [{{"action": "create", "text": "..."}}, {{"action": "modify", "id": "<id>", "text": "..."}}, {{"action": "delete", "id": "<id>"}}]}}
- id бери ДОСЛОВНО из списка выше, без скобок. Неизвестный id — операция пропадёт.
- Менять нечего — просто НЕ пиши эту строку. Так в подавляющем большинстве ответов.
- После этой строки не пиши ничего. Автор её не видит: маркер и JSON в тексте ответа не упоминай и не пересказывай."""


class RoastReply(NamedTuple):
    """Visible answer plus the rule operations the model attached to it, if any."""

    text: str
    rules_ops: list | None


def is_configured() -> bool:
    return bool(settings.ai_api_key)


def system_prompt(
    points: list[MemoryItem] | None = None,
    rules: list[MemoryItem] | None = None,
    chronology: list[MemoryItem] | None = None,
) -> str:
    base = settings.roast_system_prompt or DEFAULT_SYSTEM_PROMPT
    language = (settings.roast_language or "").strip()
    if language:
        base = f"{base}\n\nВсегда пиши ответ на языке: {language}, независимо от языка записи в дневнике."
    if points:
        joined = "\n".join(f"- {point}" for point in memory.texts(points))
        base = (
            f"{base}\n\nЧто ты уже знаешь об авторе (фон для понимания, не пересказывай это в лоб):\n{joined}"
        )
    # The date is always there: without it the model cannot place the timeline
    # against today.
    base = f"{base}\n\nСегодня: {diary_today().isoformat()}"
    if chronology:
        base = f"{base}\n\n{CHRONOLOGY_HEADER}\n{memory.render(chronology)}"
    # Last, so the rules read as the final word over everything above them. Rules
    # carry their ids: the model edits this list from inside its own reply.
    if rules:
        base = f"{base}\n\n{RULES_HEADER}\n{memory.render(rules)}"
    return f"{base}\n\n{RULES_PROTOCOL_PROMPT}"


client = create_chat_client()


def _extract_text(response) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    return (getattr(message, "content", None) or "").strip()


def _finish_reason(response) -> str:
    """Why the model stopped, for logs. `"length"` means the completion budget ran out."""
    choices = getattr(response, "choices", None) or []
    if not choices:
        return "unknown"
    return getattr(choices[0], "finish_reason", None) or "unknown"


def _trim_chain(messages: list[dict]) -> list[dict]:
    return messages[-MAX_CONVERSATION_MESSAGES:]


def split_rules_update(answer: str) -> RoastReply:
    """Cut the optional trailing rules block off an answer.

    No marker means no change — the normal case, and the reason a steady-state
    reply costs nothing extra. A marker with unreadable JSON is dropped along
    with the block: the author never sees protocol scaffolding, and operations we
    cannot parse change nothing on disk."""
    head, marker, tail = answer.partition(RULES_MARKER)
    if not marker:
        return RoastReply(answer.strip(), None)
    # Cut at the first marker: whatever follows is protocol, and the author must
    # never see it. A model that fenced the block leaves stray backticks around it.
    text = head.strip().rstrip("`").strip()
    try:
        # raw_decode, not loads: it takes the leading object and ignores any
        # trailing junk — a closing fence, a second block, a stray line.
        block, _ = json.JSONDecoder().raw_decode(tail.strip().lstrip("`").strip())
    except ValueError:
        logger.warning("Roast reply carried an unparseable rules block; ignoring it")
        return RoastReply(text, None)
    ops = block.get("ops") if isinstance(block, dict) else None
    return RoastReply(text, ops if isinstance(ops, list) and ops else None)


async def roast(
    messages: list[dict],
    points: list[MemoryItem] | None = None,
    rules: list[MemoryItem] | None = None,
    chronology: list[MemoryItem] | None = None,
) -> RoastReply:
    if not is_configured():
        raise RuntimeError("AI provider API key is not configured")

    response = await client.chat.completions.create(
        model=settings.roast_model,
        max_completion_tokens=ROAST_MAX_COMPLETION_TOKENS,
        reasoning_effort=ROAST_REASONING_EFFORT,
        messages=(
            [{"role": "system", "content": system_prompt(points, rules, chronology)}]
            + _trim_chain(messages)
        ),
    )
    reply = split_rules_update(_extract_text(response))
    if not reply.text:
        raise RuntimeError("AI provider returned an empty response")
    return reply


def _merge_extraction(
    response,
    existing: list[MemoryItem],
    store: str,
) -> list[MemoryItem]:
    """Fold the operations an extraction answered with into the stored list.

    A completion that ran out of budget comes back either empty or as partial
    JSON. Both are accumulated knowledge, so both degrade to a no-op: keeping
    what we already know beats failing the caller or losing the list."""
    text = _extract_text(response)
    if text:
        try:
            block = json.loads(text)
        except json.JSONDecodeError:
            block = None
        if isinstance(block, dict):
            return memory.apply_ops(existing, block.get("ops"))
    logger.warning(
        "%s extraction returned no usable JSON (finish_reason=%s); keeping the existing list",
        store,
        _finish_reason(response),
    )
    return existing


async def extract_profile_points(
    diary_text: str,
    existing_points: list[MemoryItem] | None = None,
    focus: str | None = None,
) -> list[MemoryItem]:
    """Fold one diary entry into the accumulated author profile. Returns the new list.

    The model answers with per-fact operations (create/modify/delete) against the
    ids it was shown, never the profile itself: the completion tracks how much
    actually changed instead of how much has been learned, so the profile can
    grow indefinitely without approaching the output ceiling, and a fact the
    model does not mention cannot be dropped. The merge happens in `memory`.

    `focus` carries the author's priorities for this extraction, if any: it steers
    what gets pulled out and how known facts are reframed, never what is stored."""
    if not is_configured():
        raise RuntimeError("AI provider API key is not configured")

    existing = list(existing_points or [])
    request = {"diary_entry": diary_text, "known_facts": memory.dump(existing)}
    system_prompt = PROFILE_EXTRACTION_PROMPT
    if focus:
        request["focus"] = focus
        system_prompt = f"{system_prompt}\n\n{PROFILE_FOCUS_INSTRUCTION}"

    payload = json.dumps(request, ensure_ascii=False)
    response = await client.chat.completions.create(
        model=settings.profile_model,
        max_completion_tokens=PROFILE_MAX_COMPLETION_TOKENS,
        reasoning_effort=PROFILE_REASONING_EFFORT,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": payload},
        ],
    )
    return _merge_extraction(response, existing, "Profile")


async def extract_chronology_events(
    diary_text: str,
    existing_events: list[MemoryItem] | None = None,
) -> list[MemoryItem]:
    """Fold one diary entry into the dated chronology. Returns the new list.

    Same operation protocol as the profile: the model answers with per-event
    create/modify/delete against the ids it was shown, so the timeline grows
    without the completion growing with it. Today's date rides along, because an
    entry rarely dates itself."""
    if not is_configured():
        raise RuntimeError("AI provider API key is not configured")

    existing = list(existing_events or [])
    payload = json.dumps(
        {
            "diary_entry": diary_text,
            "known_events": memory.dump(existing),
            "today": diary_today().isoformat(),
        },
        ensure_ascii=False,
    )
    response = await client.chat.completions.create(
        model=settings.profile_model,
        max_completion_tokens=PROFILE_MAX_COMPLETION_TOKENS,
        reasoning_effort=PROFILE_REASONING_EFFORT,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": CHRONOLOGY_EXTRACTION_PROMPT},
            {"role": "user", "content": payload},
        ],
    )
    return _merge_extraction(response, existing, "Chronology")
