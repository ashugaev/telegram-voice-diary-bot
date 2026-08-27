# Configuration

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

| Variable | Description |
|----------|-------------|
| `TELEGRAM_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather) |
| `OPENAI_API_KEY` | OpenAI API key. **Always required** — transcription (Whisper) is OpenAI-only, even with `AI_PROVIDER=anthropic` |
| `NOTION_TOKEN` | Internal integration secret from notion.so/profile/integrations |
| `NOTION_DATABASE_ID` | ID from the database URL: `notion.so/workspace/{ID}?v=...` |
| `ALLOWED_USER_ID` | Your Telegram user ID — from [@userinfobot](https://t.me/userinfobot) |
| `TIMEZONE` | Your timezone, e.g. `Asia/Bangkok`, `Europe/Moscow` |
| `AI_PROVIDER` | Optional. Chat provider for formatting/summaries/roast: `openai` (default) or `anthropic` |
| `ANTHROPIC_API_KEY` | Required only when `AI_PROVIDER=anthropic` |
| `DIARY_DAY_START_HOUR` | Optional. Hour the diary day starts in `TIMEZONE`, `0`-`23`; defaults to `0` |
| `SILENT_NOTIFICATIONS` | Optional. Send messages without push notifications; defaults to `true` |
| `ROAST_LANGUAGE` | Optional fallback roast language before `/language` is chosen; defaults to `Russian` |
| `ROAST_SYSTEM_PROMPT` | Optional. Overrides the built-in roast persona |

### Model overrides

All optional — sensible defaults are used when unset.

| Variable | Applies to | Default |
|----------|-----------|---------|
| `OPENAI_TRANSCRIPTION_MODEL` | Speech-to-text (always OpenAI) | `whisper-1` |
| `OPENAI_FORMATTER_MODEL` | Formatting (OpenAI mode) | `gpt-5.6-sol` |
| `OPENAI_SUMMARY_MODEL` | Summaries (OpenAI mode) | `OPENAI_FORMATTER_MODEL` |
| `OPENAI_PROFILE_MODEL` | Author profile (OpenAI mode) | `OPENAI_SUMMARY_MODEL` |
| `OPENAI_ROAST_MODEL` | Roast (OpenAI mode) | `gpt-5.6-sol` |
| `ANTHROPIC_FORMATTER_MODEL` | Formatting (Anthropic mode) | `claude-opus-5` |
| `ANTHROPIC_SUMMARY_MODEL` | Summaries (Anthropic mode) | `ANTHROPIC_FORMATTER_MODEL` |
| `ANTHROPIC_PROFILE_MODEL` | Author profile (Anthropic mode) | `ANTHROPIC_SUMMARY_MODEL` |
| `ANTHROPIC_ROAST_MODEL` | Roast (Anthropic mode) | `claude-opus-5` |

## Switching AI provider

Formatting, summaries, and the roast run through whichever provider `AI_PROVIDER` selects. To use Anthropic:

```bash
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

No code changes needed — restart the bot. Transcription always uses OpenAI Whisper, so `OPENAI_API_KEY` stays required in both modes.

## Notion setup

The bot works with the [Notion Journal](https://www.notion.com/help/guides/journal) database. It auto-creates any missing `Created`, `Tags`, `Day`, and metadata properties, so you mostly just need to connect the integration:

1. Open your database in Notion.
2. Click `...` → `Connections` → select your integration.

### Database properties

| Property | Type | Notes |
|----------|------|-------|
| `Name` | Title | Entry title |
| `Created` | Date | Set per entry; used for daily/weekly summaries |
| `Tags` | Multi-select | Auto-populated; `Daily` always added |
| `Day` | Select | Auto-populated `YYYY-MM-DD`; group your table by this |
| `Source` | Select | `voice` or `text` |
| `Telegram Chat ID` | Number | Source chat, for tracing and duplicate checks |
| `Telegram Message ID` | Number | Source message, for tracing and duplicate checks |
| `Source Message URL` | URL | Telegram link to the original message |
| `Voice File Unique ID` | Text | Stable Telegram voice file identifier |
| `Audio Duration` | Number | Voice duration in seconds |
| `Audio File Size` | Number | Voice file size in bytes |
| `Source Text SHA256` | Text | Exact hash for manually sent text notes |

**Duplicates:** before creating a row, the bot checks this metadata — voice notes by Telegram file id + duration/size, text notes by exact source-text hash — and offers **Add anyway** when it finds one.

**Reliability:** saves are retried on transient Notion/network errors and verified by re-reading the created page before the draft is marked saved.

**Source links:** private bot chats have no public message permalink, so `Source Message URL` uses a `https://t.me/<bot>?start=...` link — opening it makes the bot reply to the original message.

### Memory pages

Next to the database, inside the same parent page, the bot keeps two pages it creates on startup:

| Page | Holds |
|------|-------|
| `Memory — Author profile` | The durable facts the bot knows about you |
| `Memory — Bot rules` | The standing behavior rules you dictated to the bot |

Both sync in **both directions**, and a page you edited by hand wins. Each page is a bulleted list with an `Updated ... · N items` header — one bullet per item, and only the bullets count. The bot pulls before it reads its memory (every roast, `/rules`, `/memory`, and startup) and pushes after every change:

| On the page | What happens |
|---|---|
| Same list the bot holds | Nothing — no read costs a write |
| Changed since the bot's last write | **Notion wins** — the bullets are adopted into local state |
| Still what the bot last wrote, but stale | The page is rewritten from local state |

So editing bullets in Notion is a supported way to teach the bot: add, reword, reorder, or delete a bullet and the next roast uses your version. Emptying a page wipes that memory. Text you add outside the bullets is dropped on the next write.

A roast reuses the last pull for a minute, so a long back-and-forth does not re-read both pages on every turn. `/rules`, `/memory`, and startup always pull, so an edit you want picked up immediately is one `/rules` away. Nothing polls in the background — every read is triggered by something you did.

The parent is taken from the database itself, so there is nothing to configure; the database has to live inside a page rather than at the workspace root. Syncing is best-effort — an unreachable Notion never blocks the diary flow, and a write that failed is retried on the next sync rather than mistaken for a hand edit.
