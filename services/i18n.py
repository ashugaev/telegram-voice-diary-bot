DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("en", "ru")

LANGUAGE_NAMES = {
    "en": "English",
    "ru": "Русский",
}

AI_LANGUAGE_NAMES = {
    "en": "English",
    "ru": "Russian",
}


def normalize_language(language: str | None) -> str:
    if not language:
        return DEFAULT_LANGUAGE
    code = language.strip().lower().split("-", 1)[0].split("_", 1)[0]
    return code if code in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def ai_language(language: str | None) -> str:
    return AI_LANGUAGE_NAMES[normalize_language(language)]


MESSAGES: dict[str, dict[str, str]] = {
    "adding_anyway": {
        "en": "Adding this voice message anyway...",
        "ru": "Добавляю это голосовое еще раз...",
    },
    "button.add_anyway": {
        "en": "Add anyway",
        "ru": "Добавить все равно",
    },
    "button.back_preview": {
        "en": "← Back to preview",
        "ru": "← Назад к превью",
    },
    "button.cancel": {
        "en": "Cancel",
        "ru": "Отмена",
    },
    "button.cancel_draft": {
        "en": "Cancel draft",
        "ru": "Удалить черновик",
    },
    "button.confirm": {
        "en": "✓ Confirm",
        "ru": "✓ Подтвердить",
    },
    "button.date": {
        "en": "Date: {date}",
        "ru": "Дата: {date}",
    },
    "button.format": {
        "en": "✦ Format",
        "ru": "✦ Формат",
    },
    "button.highlighted": {
        "en": "⭐ Highlighted",
        "ru": "⭐ Хайлайт",
    },
    "button.mark_highlight": {
        "en": "Mark as Highlight ⭐",
        "ru": "Отметить хайлайтом ⭐",
    },
    "button.original": {
        "en": "↺ Original",
        "ru": "↺ Оригинал",
    },
    "button.retry": {
        "en": "Retry",
        "ru": "Повторить",
    },
    "button.roast": {
        "en": "🔥 Roast",
        "ru": "🔥 Разъёб",
    },
    "button.save": {
        "en": "✓ Save",
        "ru": "✓ Сохранить",
    },
    "button.tags": {
        "en": "✎ Tags",
        "ru": "✎ Теги",
    },
    "button.text": {
        "en": "✎ Text",
        "ru": "✎ Текст",
    },
    "button.title": {
        "en": "✎ Title",
        "ru": "✎ Заголовок",
    },
    "button.to_chat": {
        "en": "🔥 Switch to Chat",
        "ru": "🔥 Включить пиздеж",
    },
    "button.to_diary": {
        "en": "📖 Switch to Diary",
        "ru": "📖 Включить дневник",
    },
    "cancelled": {
        "en": "Cancelled.",
        "ru": "Отменено.",
    },
    "cmd.start": {
        "en": "What I do",
        "ru": "Что я делаю",
    },
    "cmd.help": {
        "en": "Commands and buttons",
        "ru": "Команды и кнопки",
    },
    "cmd.diary": {
        "en": "Switch to Diary mode",
        "ru": "Включить режим дневника",
    },
    "cmd.chat": {
        "en": "Switch to Chat mode (roast prompt)",
        "ru": "Включить режим пиздежа",
    },
    "cmd.weekly": {
        "en": "Weekly report now",
        "ru": "Итоги недели сейчас",
    },
    "cmd.stat": {
        "en": "Saved audio minutes",
        "ru": "Минуты аудио",
    },
    "cmd.memory": {
        "en": "Rebuild author profile from all notes",
        "ru": "Пересобрать профиль автора",
    },
    "cmd.rules": {
        "en": "Show behavior rules",
        "ru": "Правила поведения бота",
    },
    "cmd.lang": {
        "en": "Switch language",
        "ru": "Сменить язык",
    },
    "daily.empty_push": {
        "en": "Hey, how was your day? I'm sure you have something to be proud of!",
        "ru": "Как прошел день? Уверен, есть чем гордиться.",
    },
    "daily.header": {
        "en": "*Daily summary*",
        "ru": "*Итоги дня*",
    },
    "date.choose": {
        "en": "Choose note date from the last 7 days.\n\nCurrent: <code>{date}</code>",
        "ru": "Выбери дату записи из последних 7 дней.\n\nСейчас: <code>{date}</code>",
    },
    "date.gone": {
        "en": "This date is no longer available. Choose from the menu again.",
        "ru": "Эта дата уже недоступна. Выбери из меню снова.",
    },
    "date.today": {
        "en": "Today ({date})",
        "ru": "Сегодня ({date})",
    },
    "date.yesterday": {
        "en": "Yesterday ({date})",
        "ru": "Вчера ({date})",
    },
    "draft.gone": {
        "en": "This draft is no longer available.",
        "ru": "Этот черновик уже недоступен.",
    },
    "draft.saving": {
        "en": "This draft is already saving.",
        "ru": "Этот черновик уже сохраняется.",
    },
    "duplicate.entry": {
        "en": "This entry has already been added.\n\nAdd it again anyway?",
        "ru": "Эта запись уже добавлена.\n\nДобавить еще раз?",
    },
    "duplicate.voice": {
        "en": "This voice message has already been added.\n\nAdd it again anyway?",
        "ru": "Это голосовое уже добавлено.\n\nДобавить еще раз?",
    },
    "edit.tags": {
        "en": "Send tags separated by commas:",
        "ru": "Пришли теги через запятую:",
    },
    "edit.text": {
        "en": "Send a new text:",
        "ru": "Пришли новый текст:",
    },
    "edit.title": {
        "en": "Send a new title:",
        "ru": "Пришли новый заголовок:",
    },
    "error": {
        "en": "Error: {error}",
        "ru": "Ошибка: {error}",
    },
    "formatted_already": {
        "en": "This draft is already formatted.",
        "ru": "Этот черновик уже отформатирован.",
    },
    "formatted_missing": {
        "en": "Formatted text is no longer available.",
        "ru": "Отформатированный текст больше недоступен.",
    },
    "formatter.untitled": {
        "en": "Untitled",
        "ru": "Без названия",
    },
    "help": {
        "en": "*Sending*\nVoice or text. I'll transcribe, title, tag, and show a preview.\n\n*Preview buttons*\n`✎ Title` `✎ Text` `✎ Tags` — reply with new value\n`✦ Format` — clean up text, `↺ Original` restores original\n`Date` — today or last 6 days\n`Highlight ⭐` — mark for weekly report\n`🔥 Roast` — honest teardown, reply to continue\n`✓ Save` — write to Notion, nothing is saved until pressed\n`Cancel` — discard draft\n\n*Commands*\n{commands}\n\n*Automatic*\nDaily digest at 21:00. Weekly report on Sunday at 21:00.",
        "ru": "*Отправка*\nГолос или текст. Я распознаю, озаглавлю, проставлю теги и покажу превью.\n\n*Кнопки превью*\n`✎ Заголовок` `✎ Текст` `✎ Теги` — ответь новым значением\n`✦ Формат` — привести текст в порядок, `↺ Оригинал` вернет исходник\n`Дата` — сегодня или последние 6 дней\n`Хайлайт ⭐` — отметить для недельного отчета\n`🔥 Разъёб` — честный разбор, ответь чтобы продолжить\n`✓ Сохранить` — записать в Notion, до этого ничего не сохраняется\n`Отмена` — удалить черновик\n\n*Команды*\n{commands}\n\n*Автоматически*\nДайджест дня в 21:00. Недельный отчет в воскресенье в 21:00.",
    },
    "language.changed": {
        "en": "Language switched to {language_name}.",
        "ru": "Язык переключен на {language_name}.",
    },
    "language.choose": {
        "en": "Choose language / Выберите язык:",
        "ru": "Выберите язык / Choose language:",
    },
    "language.current": {
        "en": "Current language: {language_name}.",
        "ru": "Текущий язык: {language_name}.",
    },
    "language.invalid": {
        "en": "Unsupported language.",
        "ru": "Такой язык недоступен.",
    },
    "listening": {
        "en": "Listening...",
        "ru": "Слушаю...",
    },
    "mode.diary_enabled": {
        "en": "📖 Diary mode enabled. Voice and text messages are formatted and prepared for Notion.",
        "ru": "📖 Режим дневника включен. Голосовые и текстовые сообщения форматируются и готовятся к сохранению в Notion.",
    },
    "mode.chat_enabled": {
        "en": "🔥 Chat mode enabled. Messages continue the conversation with your roast buddy and are not saved to Notion. Memory updates normally.",
        "ru": "🔥 Режим пиздежа включен. Сообщения идут в постоянный диалог с коучем и не сохраняются в Notion. Память обновляется штатно.",
    },
    "memory.about": {
        "en": "About you",
        "ru": "О тебе",
    },
    "memory.chronology": {
        "en": "Chronology",
        "ru": "Хронология",
    },
    "memory.rules": {
        "en": "Rules",
        "ru": "Правила",
    },
    "memory.updated": {
        "en": "🧠 Memory updated",
        "ru": "🧠 Память обновлена",
    },
    "memory.api_missing": {
        "en": "AI provider API key is not configured.",
        "ru": "Ключ AI-провайдера не настроен.",
    },
    "memory.cancelled": {
        "en": "Memory rebuild cancelled.",
        "ru": "Пересборка памяти отменена.",
    },
    "memory.confirm": {
        "en": "🧠 Ready to rebuild long-term memory\n\n{focus}\n{stored}\n\nEvery note costs one AI request, so a full pass takes a while. Progress is saved as it goes.",
        "ru": "🧠 Готов пересобрать долгосрочную память\n\n{focus}\n{stored}\n\nКаждая заметка стоит один AI-запрос, поэтому полный проход займет время. Прогресс сохраняется по ходу.",
    },
    "memory.done": {
        "en": "✅ Long-term memory rebuilt",
        "ru": "✅ Долгосрочная память пересобрана",
    },
    "memory.empty_skipped": {
        "en": "Empty notes skipped: {count}",
        "ru": "Пустых заметок пропущено: {count}",
    },
    "memory.empty_stored": {
        "en": "Nothing is stored yet — the profile will be built from scratch.",
        "ru": "Пока ничего не сохранено — профиль будет собран с нуля.",
    },
    "memory.facts": {
        "en": "Facts: {before} → {after}",
        "ru": "Фактов: {before} → {after}",
    },
    "memory.failed": {
        "en": "Memory rebuild failed: {error}",
        "ru": "Пересборка памяти упала: {error}",
    },
    "memory.failed_count": {
        "en": "Notes failed: {count}",
        "ru": "Заметок с ошибкой: {count}",
    },
    "memory.focus": {
        "en": "Focus: {focus}",
        "ru": "Фокус: {focus}",
    },
    "memory.no_focus": {
        "en": "Focus: none",
        "ru": "Фокус: нет",
    },
    "memory.no_notes": {
        "en": "🧠 No saved notes found in Notion — nothing to rebuild from.",
        "ru": "🧠 В Notion нет сохраненных заметок — пересобирать не из чего.",
    },
    "memory.no_speech_retry": {
        "en": "{model} did not recognize any speech. Run /memory again to retry.",
        "ru": "{model} не распознал речь. Запусти /memory снова для повтора.",
    },
    "memory.notes_read": {
        "en": "Notes read: {count}",
        "ru": "Заметок прочитано: {count}",
    },
    "memory.progress": {
        "en": "🧠 Rebuilding long-term memory...\n\n{bar}\nFacts: {facts}\n{focus}",
        "ru": "🧠 Пересобираю долгосрочную память...\n\n{bar}\nФактов: {facts}\n{focus}",
    },
    "memory.reason": {
        "en": "Reason: {reason}",
        "ru": "Причина: {reason}",
    },
    "memory.request_gone": {
        "en": "This memory rebuild request is no longer available.",
        "ru": "Этот запрос пересборки памяти уже недоступен.",
    },
    "memory.running": {
        "en": "A memory rebuild is already running. Wait for it to finish.",
        "ru": "Пересборка памяти уже идет. Дождись завершения.",
    },
    "memory.saved_so_far": {
        "en": "Everything processed so far is saved.",
        "ru": "Все обработанное уже сохранено.",
    },
    "memory.starting": {
        "en": "🧠 Starting the long-term memory rebuild...",
        "ru": "🧠 Начинаю пересборку долгосрочной памяти...",
    },
    "memory.stopped": {
        "en": "⚠️ Long-term memory rebuild stopped early",
        "ru": "⚠️ Пересборка долгосрочной памяти остановилась раньше",
    },
    "memory.stored": {
        "en": "Stored now: {count} fact(s) — kept as the starting point and corrected along the way.",
        "ru": "Сейчас сохранено: {count} факт(ов) — беру их стартовой точкой и поправлю по ходу.",
    },
    "memory.intro": {
        "en": "🧠 Long-term memory rebuild\n\nI'll walk through every saved note in Notion, oldest first, and rebuild the author profile note by note — one AI request per note, same as when you send a new one.\n\n{stored}\n\nReply with the focus points for this pass: what matters most, what to keep, what to drop.\nSend - to rebuild without extra focus.",
        "ru": "🧠 Пересборка долгосрочной памяти\n\nЯ пройду все сохраненные записи в Notion от старых к новым и пересоберу профиль автора заметка за заметкой — один AI-запрос на заметку, как при обычной отправке.\n\n{stored}\n\nОтветь фокусом для этого прохода: что важнее всего, что сохранить, что убрать.\nОтправь - чтобы пересобрать без фокуса.",
    },
    "memory.voice_retry": {
        "en": "Error: {error}\n\nRun /memory again to retry.",
        "ru": "Ошибка: {error}\n\nЗапусти /memory снова для повтора.",
    },
    "message.gone": {
        "en": "This message is no longer available.",
        "ru": "Это сообщение уже недоступно.",
    },
    "not_saved": {
        "en": "Not saved to Notion: {error}\nDraft kept. Press Save to retry or Cancel to discard.",
        "ru": "Не сохранено в Notion: {error}\nЧерновик сохранен. Нажми Сохранить для повтора или Отмена для удаления.",
    },
    "original_already": {
        "en": "This draft already shows the original text.",
        "ru": "Этот черновик уже показывает оригинальный текст.",
    },
    "original_missing": {
        "en": "Original text is no longer available.",
        "ru": "Оригинальный текст больше недоступен.",
    },
    "preparing": {
        "en": "Preparing preview...",
        "ru": "Готовлю превью...",
    },
    "preview.date": {
        "en": "Date: <code>{date}</code>",
        "ru": "Дата: <code>{date}</code>",
    },
    "preview.fallback": {
        "en": "<code>Preview is too long for Telegram. Full text is kept for Save/Edit/Format.</code>",
        "ru": "<code>Превью слишком длинное для Telegram. Полный текст сохранен для Сохранить/Правка/Формат.</code>",
    },
    "preview.truncated": {
        "en": "\n\n<code>Preview truncated. Page {page}/{page_count}. Full text is kept for Save/Edit/Format.</code>",
        "ru": "\n\n<code>Превью обрезано. Страница {page}/{page_count}. Полный текст сохранен для Сохранить/Правка/Формат.</code>",
    },
    "processing": {
        "en": "This message is already processing.",
        "ru": "Это сообщение уже обрабатывается.",
    },
    "retrying": {
        "en": "Retrying...",
        "ru": "Повторяю...",
    },
    "roast.empty": {
        "en": "Nothing to roast — the text is empty.",
        "ru": "Нечего разбирать — текст пустой.",
    },
    "roast.failed": {
        "en": "Roast failed: {error}",
        "ru": "Разъёб упал: {error}",
    },
    "roast.status": {
        "en": "🔥 Roasting...",
        "ru": "🔥 Разбираю...",
    },
    "roast.thinking": {
        "en": "🔥 Thinking...",
        "ru": "🔥 Думаю...",
    },
    "roast.unavailable": {
        "en": "🔥 Roast is unavailable: set ANTHROPIC_API_KEY in .env.",
        "ru": "🔥 Разъёб недоступен: укажи ANTHROPIC_API_KEY в .env.",
    },
    "rules.empty": {
        "en": "🧠 No rules yet. Tell me in a roast reply how to behave — I'll remember it.",
        "ru": "🧠 Правил пока нет. Скажи в ответе на разъёб, как мне себя вести — я запомню.",
    },
    "rules.header": {
        "en": "🧠 Rules",
        "ru": "🧠 Правила",
    },
    "saved": {
        "en": "✓ Saved to Notion and verified",
        "ru": "✓ Сохранено в Notion и проверено",
    },
    "saving": {
        "en": "Saving to Notion...",
        "ru": "Сохраняю в Notion...",
    },
    "source.failed": {
        "en": "I couldn't open that source message. It may have been deleted or is no longer available.",
        "ru": "Не смог открыть исходное сообщение. Возможно, оно удалено или больше недоступно.",
    },
    "source.message": {
        "en": "Source message",
        "ru": "Исходное сообщение",
    },
    "speech.empty": {
        "en": "{model} did not recognize any speech in this message.",
        "ru": "{model} не распознал речь в этом сообщении.",
    },
    "stat.counting": {
        "en": "Counting saved audio stats...",
        "ru": "Считаю сохраненные аудио...",
    },
    "stat.error": {
        "en": "Error generating audio stats.",
        "ru": "Ошибка подсчета аудио-статистики.",
    },
    "stats.all_time": {
        "en": "all time",
        "ru": "все время",
    },
    "stats.audio_count": {
        "en": "{count} audio",
        "ru": "{count} аудио",
    },
    "stats.audio_header": {
        "en": "*Audio statistics*",
        "ru": "*Аудио статистика*",
    },
    "stats.audio_line": {
        "en": "Audio: {duration} · {count}",
        "ru": "Аудио: {duration} · {count}",
    },
    "stats.busiest_day": {
        "en": "Busiest day: {day}, {duration}",
        "ru": "Самый насыщенный день: {day}, {duration}",
    },
    "stats.daily_header": {
        "en": "*By day for the last 7 days*",
        "ru": "*По дням за последние 7 дней*",
    },
    "stats.day_header": {
        "en": "*Day stats*",
        "ru": "*Цифры дня*",
    },
    "stats.duration.hours": {
        "en": "{hours} h",
        "ru": "{hours} ч",
    },
    "stats.duration.hours_minutes": {
        "en": "{hours} h {minutes} min",
        "ru": "{hours} ч {minutes} мин",
    },
    "stats.duration.minutes": {
        "en": "{minutes} min",
        "ru": "{minutes} мин",
    },
    "stats.duration.zero": {
        "en": "0 min",
        "ru": "0 мин",
    },
    "stats.entries_line": {
        "en": "Entries: {count}",
        "ru": "Записи: {count}",
    },
    "stats.last_7_days": {
        "en": "last 7 days",
        "ru": "последние 7 дней",
    },
    "stats.monthly_header": {
        "en": "*By month for the last 6 months*",
        "ru": "*По месяцам за последние 6 месяцев*",
    },
    "stats.total_line": {
        "en": "Total: {duration} · {count}",
        "ru": "Всего: {duration} · {count}",
    },
    "stats.week_header": {
        "en": "*Week stats*",
        "ru": "*Цифры недели*",
    },
    "stats.week_line": {
        "en": "Week: {duration} · {count}",
        "ru": "За неделю: {duration} · {count}",
    },
    "transcribing": {
        "en": "Transcribing...",
        "ru": "Распознаю...",
    },
    "voice.gone": {
        "en": "This voice message is no longer available.",
        "ru": "Это голосовое уже недоступно.",
    },
    "weekly.empty": {
        "en": "No entries this week.",
        "ru": "На этой неделе записей нет.",
    },
    "weekly.empty_push": {
        "en": "No entries this week — next week is a fresh start!",
        "ru": "На этой неделе записей нет — следующая неделя чистая.",
    },
    "weekly.error": {
        "en": "Error generating weekly report.",
        "ru": "Ошибка генерации недельного отчета.",
    },
    "weekly.generating": {
        "en": "Generating weekly report...",
        "ru": "Генерирую недельный отчет...",
    },
    "weekly.header": {
        "en": "*Weekly highlights*",
        "ru": "*Итоги недели*",
    },
    "welcome": {
        "en": "👋 Diary bot is online.\n\nSend voice or text. I'll transcribe, add title and tags, and show a preview. You edit, press Save, and the note goes to Notion.\n\nDaily digest at 21:00. More: /help.",
        "ru": "👋 Пиздабол на связи.\n\nПрисылай голос или текст. Я распознаю, добавлю заголовок и теги, покажу превью. Ты правишь, жмешь Сохранить, запись улетает в Notion.\n\nДайджест дня в 21:00. Остальное: /help.",
    },
}


def t(key: str, language: str | None = None, **kwargs) -> str:
    lang = normalize_language(language)
    translations = MESSAGES.get(key)
    if not translations:
        text = key
    else:
        text = translations.get(lang) or translations.get(DEFAULT_LANGUAGE) or key
    return text.format(**kwargs) if kwargs else text
