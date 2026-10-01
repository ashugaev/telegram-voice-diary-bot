# Development & deployment

## Local development

```bash
make dev        # stop the running service and run the bot in the foreground
make stop-dev   # hand the bot back to the service
make logs       # follow service logs
make test       # offline validation — no Telegram/OpenAI/Notion calls
```

## Safe validation sidecars

Inspect the command before launch. The existing `dev` sidecar stops production.
Use manual `check` instead; never start a second Telegram poller with the live token.

```bash
"$SPUR_SESSION_TOOL_DIR/spur-sidecar" --name check
```

`check` runs `scripts/check-sidecar.sh` once: test credentials, dotenv disabled,
unique state and logs under `SPUR_SESSION_ARTIFACTS_DIR`, offline `make test`.
Run fresh checks before merging. Failed or missing checks block release.

With explicit authorization for a real OpenAI call:

```bash
"$SPUR_SESSION_TOOL_DIR/spur-sidecar" --name speech-check
```

`speech-check` runs offline checks first, then standalone `scripts/speech-smoke.py`.
It reads only the OpenAI key from `.env` if absent in the environment, then calls
shipped `services.speech.synthesize` with test credentials and isolated state.
It validates Ogg Opus headers; never imports bot state or calls Telegram/Notion. Audio stays in session artifacts. Listen before claiming quality.
`SPEECH_SMOKE_TEXT`, `OPENAI_TTS_MODEL`, and `OPENAI_TTS_VOICE` override defaults.

Sidecars live in tracked `spur.yaml`; Spur reads the current worktree copy:
`check: bash scripts/check-sidecar.sh`,
`speech-check: bash scripts/check-sidecar.sh --speech`; both `autoStart: false`.
Keep the canonical project copy synced; `spur connect` registers it, but session launches read worktree settings.

## Deploy

```bash
make deploy     # push to main, then pull + restart on the host
```

The host also pulls `origin/main` on its own every 10 minutes, so a merged PR ships without `make deploy`.

## Host setup

The bot runs on `openclaw-dev` as a **systemd user service**, not on a VPS. One instance only — Telegram allows a single poller per token.

```
/home/alek/projects/diary-bot          checkout the service runs from, tracks main
/home/alek/projects/diary-bot/.env     secrets, never committed
/home/alek/projects/diary-bot/.data    local state (messages, drafts, profile, rules)
```

First-time setup:

```bash
git clone git@github.com:ashugaev/pizdabol-ai.git /home/alek/projects/diary-bot
cd /home/alek/projects/diary-bot
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env

cp deploy/diary-bot.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now diary-bot.service
sudo loginctl enable-linger "$USER"   # survive reboot without a login session
```

Auto-update, in the user crontab:

```
*/10 * * * * /home/alek/projects/diary-bot/scripts/bot-update.sh >> /tmp/diary-bot-update.log 2>&1
```

`scripts/bot-update.sh` fast-forwards `main`, reinstalls deps only when `requirements.txt` changed, and restarts the service. It skips when the checkout is dirty or on another branch.

Useful commands:

```bash
systemctl --user status diary-bot        # status
journalctl --user -u diary-bot -f        # live logs
systemctl --user restart diary-bot       # restart
```

## State

State lives in `.data/message_state.json`. The author profile and behavior rules are mirrored to Notion and re-adopted from those pages on startup, so Notion is the durable copy of memory; the local file additionally holds message mapping and unsaved drafts.

## Project structure

```
bot.py                  # Telegram bot entry point
config.py               # Settings loaded from .env
services/
├── whisper.py          # Audio transcription (OpenAI Whisper)
├── formatter.py        # Entry title/tags/text formatting
├── ai.py               # Chat client factory (OpenAI / Anthropic)
├── notion.py           # Notion API: create/read diary pages
├── notion_memory.py    # Mirrors the bot's memory to Notion pages next to the database
├── summary.py          # Daily summary & weekly report
├── memory.py           # ID-addressed memory: create/modify/delete ops on facts and rules
├── roast.py            # Roast mode + author profile
├── profile_rebuild.py  # Sequential profile rebuild over all notes (/memory)
├── stats.py            # Audio-minute stats
├── state_store.py      # Local JSON state (messages, drafts, profile, rules)
└── diary_dates.py      # Diary-day date logic
deploy/diary-bot.service  # systemd user unit
scripts/bot-update.sh     # cron auto-update
scripts/bot-watch.sh      # dev sidecar: restart on file change
Makefile                # Dev & deploy commands
requirements.txt
.env.example
```

## Estimated costs

Cheap for personal use — dominated by Whisper:

| Service | Price | Per entry (~1 min voice) |
|---------|-------|--------------------------|
| Whisper | $0.006 / minute | ~$0.006 |
| Chat models | depends on model | usually well below $0.001 |

100 entries/month ≈ **$0.60**.
