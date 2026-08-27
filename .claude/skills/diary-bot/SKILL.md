---
name: diary-bot
description: Work on this Telegram-to-Notion diary bot. Use when tasks touch bot behavior, Telegram UX, OpenAI transcription/formatting/summaries, Notion schema or writes, state storage, env config, tests, CI, or deployment. Do not use for unrelated repository metadata-only edits.
---

# Diary Bot

Use this as project memory for implementation and validation.

## Ownership map

| Area | Files |
|---|---|
| Telegram update flow, drafts, callbacks, scheduling | `bot.py` |
| Environment parsing and defaults | `config.py`, `.env.example` |
| AI provider selection (OpenAI/Anthropic) for chat tasks | `services/ai.py`, `tests/test_anthropic_provider.py` |
| Chat formatting (provider-neutral) | `services/formatter.py`, `tests/test_openai_services.py` |
| OpenAI transcription (always OpenAI, no Anthropic equivalent) | `services/whisper.py`, `tests/test_openai_services.py` |
| Daily and weekly summaries (provider-neutral) | `services/summary.py`, `tests/test_openai_services.py` |
| Notion schema, retries, duplicate checks, writes | `services/notion.py`, `tests/test_notion.py` |
| Retrospective profile rebuild (`/memory`) | `services/profile_rebuild.py`, `tests/test_profile_rebuild.py` |
| ID-addressed memory: ops protocol, ids, merge | `services/memory.py`, `tests/test_memory.py` |
| Roast persona, author profile, behavior rules | `services/roast.py`, `tests/test_roast.py` |
| Memory sync with Notion pages next to the database | `services/notion_memory.py`, `tests/test_notion_memory.py` |
| Local message and draft state | `services/state_store.py`, `tests/test_state_store.py` |
| Dev, test, deploy commands | `Makefile`, `README.md`, `.github/workflows/ci.yml` |
| Landing site, EN and RU | `landing/index.html`, `landing/ru/index.html`, `landing/styles.css`, `landing/sitemap.xml` |

## Behavior invariants

- Preview original transcription or typed text by default.
- Formatter-generated title and tags apply before save; formatted body applies only after the Format button.
- `Daily` tag is always present in rendered and saved entries.
- Date picker allows today plus previous 6 days.
- Duplicate voice notes use Telegram voice facts; duplicate text notes use exact source-text hash.
- Notion save retries transient errors and verifies created page before marking saved.
- Long transcriptions use metadata-only formatting and keep original text.
- `/memory` rebuild is two-step (focus prompt, then confirm), sequential, single-flight, and persists points after every note.
- Both memory stores (author profile, behavior rules) are accumulated `MemoryItem` lists edited only through `memory.apply_ops`: the model returns `create`/`modify`/`delete` operations addressing an item id, never a rewritten list. An unknown id is a logged no-op. Ids persist in state; list size and item length are guided in the prompt, never trimmed in code.
- The profile only shrinks when a fact went false or folds into a duplicate. Never drop a fact for being weak, small, or absent from the current note.
- Behavior rules outrank the roast persona, carry their ids into the roast system prompt, and are amended by the model in any turn via a trailing `RULES_MARKER` ops block that is stripped from the reply. No ops, or ops that change nothing, must never rewrite stored state.
- Both memory changes are announced by one renderer, `_render_memory_note`: `MEMORY_NOTE_HEADER` plus an `About you:` block for profile facts and a `Rules:` block for rules, each dropped when empty. Nothing changed sends no message. Long notes chunk through `_split_message`; a note failure never costs the stored change.
- Notion memory pages (`Memory — Author profile`, `Memory — Bot rules`) sync both ways in plain text — ids stay internal. A page whose bullets no longer match the stored `notion_mirror` was hand-edited and wins; otherwise the page is rewritten from local state. Adopt through `memory.adopt`, which keeps the id of every bullet whose text survived the edit. Pull before every read of memory (roast, `/rules`, `/memory`, startup), push after every change, never block the diary flow. The roast pull is throttled by `MEMORY_PULL_TTL_SECONDS`; explicit reads always pull. Nothing polls in the background. One `_memory_lock` guards every memory read-modify-write — take it via `_sync_*_memory`, or call `_sync_*_memory_held` when already holding it; never hold it across a model call. The profile rebuild pulls once at the start and pushes once at the end, not per note.

## External boundaries

- Tests stay offline. Patch OpenAI clients, Notion HTTP clients, Telegram update/context objects, sleeps, and state paths.
- Never require real `.env` values in tests; set test env before importing modules that read settings.
- Never mutate `.data/message_state.json` in tests.
- Do not run `make dev`, `make deploy`, `make stop-dev`, `ssh`, or systemd commands unless user explicitly asks.

## Validation

Use the narrowest targeted test first, then full local validation for code changes:

```bash
python -m py_compile bot.py config.py services/*.py tests/*.py
python -m unittest discover -s tests -v
make test
```

## Change checklist

- Env var changed: update `config.py`, `.env.example`, README config table, tests.
- Notion property changed: update constants, schema ensure logic, tests, README database table.
- Telegram flow changed: update `bot.py` tests for callbacks, preview text, prompt state, and cancel/save retry behavior.
- OpenAI prompt/model changed: update OpenAI service tests and fallback behavior.
- State shape changed: keep backward load defaults or explicit migration; test old/minimal state.
- User-visible feature changed: update `README.md` + `docs/`, `COMMANDS` and `WELCOME_TEXT` in `bot.py` (drive `/help` and the Telegram menu), and both landing pages.
- Landing changed: keep it static HTML + CSS, no JS; mirror EN and RU copy; keep meta, OG, JSON-LD, hreflang, and `sitemap.xml` correct; preview via the `landing` sidecar.
- Deployment changed: route through `operator`; validate without touching production unless requested.
