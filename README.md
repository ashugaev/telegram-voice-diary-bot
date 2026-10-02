# Pizdabol

A Telegram bot that turns your voice (or text) messages into structured diary entries in Notion, and doubles as a personal coach/therapist: it learns who you are on its own, builds a knowledge base about you from every note, and digs deeper into anything you reply to. Built for the [Notion Journal](https://www.notion.com/help/guides/journal).

## Quick start

```bash
git clone https://github.com/ashugaev/pizdabol-ai.git
cd pizdabol-ai
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your tokens
python bot.py
```

You'll need a Telegram bot token, an OpenAI API key, and a Notion integration + database — see **[Configuration](docs/configuration.md)**.

## What you can do

- **Send a voice or text note** — it's transcribed, titled, tagged, previewed, and saved as a Notion row.
- **Retry failed voice requests** — use the Retry button on failed diary, Chat, Roast follow-up, draft edit, and `/memory` focus voice messages.
- **Edit before saving** — adjust title, text, tags, or date; nothing is written until you press Save.
- **🔥 Roast, your personal coach** — an honest take on your entry; reply to it to keep talking and go deeper. Tell it to behave differently and it remembers.
- **Learns you on its own** — builds a private knowledge base about you from every note, no extra input needed, and posts one short note when it learns something or you change a rule.
- **Summaries** — automatic daily recap and an on-demand weekly report.
- **Localization** — English (default) and Russian supported; `/start` suggests language selection, switch anytime with `/lang`.
- **Memory in Notion** — the knowledge base, the dated timeline of your life, and the behavior rules you gave it live on their own pages next to your diary database. Edit a page by hand and the bot adopts your version.

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome and quick overview |
| `/voice [on\|off]` | Toggle AI voice replies for Roast and Chat |
| `/help` | Commands and preview buttons |
| `/diary` | Switch to Diary mode (default) |
| `/chat` | Switch to Chat mode (roast prompt, no Notion save) |
| `/weekly` | Generate the weekly report now |
| `/stat` | Saved audio minutes overall, by day, and by month |
| `/memory` | Rebuild the author profile from every saved note, guided by focus points you supply |
| `/rules` | Show the behavior rules the bot learned from you |
| `/lang` | Switch language (English / Russian) |

The bot publishes this list to Telegram on startup, so typing `/` in the chat shows it.

Voice replies use OpenAI speech (`gpt-4o-mini-tts`, `cedar`) with the existing `OPENAI_API_KEY`, even with another chat provider. Override `OPENAI_TTS_MODEL` and `OPENAI_TTS_VOICE` in `.env`. Replies arrive as Telegram voice notes; long replies split into parts. Speech errors fall back to text. Diary previews and memory notes stay text. Voice preference persists per chat, independently of Diary/Chat mode; default off.

Telegram voice privacy restrictions produce text with instructions to allow the bot under Settings > Privacy and Security > Voice Messages. Startup and valid `/voice` commands refresh the chat command menu.

## Docs

- **[Usage](docs/usage.md)** — preview & editing, roast mode, behavior rules, author profile, tags, summaries.
- **[Configuration](docs/configuration.md)** — environment variables, AI provider, Notion setup.
- **[Development & deployment](docs/deployment.md)** — local dev, tests, systemd service, auto-update, project structure, costs.
