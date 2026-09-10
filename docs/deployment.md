# Development & deployment

## Local development

```bash
make dev        # stop the running service and run the bot in the foreground
make stop-dev   # hand the bot back to the service
make logs       # follow service logs
make test       # offline validation — no Telegram/OpenAI/Notion calls
```

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
