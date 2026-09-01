# CLAUDE.md

MANDATORY: every task runs through the `manager` skill first — no exception. It decomposes, routes via the catalogs below, validates, and closes out. Never edit files, run commands, or answer a task request without it. Each agent and skill has a frontmatter `description` with triggers; read it before invoking.

## Mirror

- `AGENTS.md` and `CLAUDE.md` stay content-synced; tree-specific link paths differ.
- Files under `.agents/` and `.claude/` stay in sync. Change both in the same diff.
- `.codex/agents/*.toml` are Codex-side prompts parallel to `.claude/agents/*.md`. Update them when behavior changes.
- `.codex/hooks.json` and `.codex/hooks/` configure Codex hooks. Hooks must stay local-only and non-production.
- Keep repo rules compact. Move project specifics to `.claude/skills/diary-bot/SKILL.md` when details grow.

## Agents

Autonomous workers invoked by the agent runtime. Source: [.claude/agents/](.claude/agents/).

| Agent | Use when |
|---|---|
| [`researcher`](.claude/agents/researcher.md) | Generate 2-3 implementation options with codebase evidence |
| [`critic`](.claude/agents/critic.md) | Verify researcher claims, score options, select winner |
| [`architect`](.claude/agents/architect.md) | Produce concrete plan: touched files, steps, criteria, risks, tests |
| [`developer`](.claude/agents/developer.md) | Implement, fix after review, fix after test |
| [`reviewer`](.claude/agents/reviewer.md) | Static diff review plus local validation gate |
| [`tester`](.claude/agents/tester.md) | Run targeted Python tests, compile checks, offline behavior checks |
| [`operator`](.claude/agents/operator.md) | Review runtime, deployment, systemd, environment, and production-safety changes |

## Skills

Capabilities loaded by description match. Source: [.claude/skills/](.claude/skills/).

| Skill | Load when |
|---|---|
| [`manager`](.claude/skills/manager/SKILL.md) | Mandatory orchestrator for repo tasks |
| [`diary-bot`](.claude/skills/diary-bot/SKILL.md) | Task touches bot behavior, Telegram UX, OpenAI formatting, Notion writes, state, env, tests, or deploy |
| [`shallow-scoring`](.claude/skills/shallow-scoring/SKILL.md) | Score task complexity 1-5 |
| [`skill-writer`](.claude/skills/skill-writer/SKILL.md) | Edit skills, agents, prompts, or orchestrator instructions |
| [`code-simplifier`](.claude/skills/code-simplifier/SKILL.md) | Reduce diff overhead before review |
| [`self-verify`](.claude/skills/self-verify/SKILL.md) | Final manager close-out validation |

## Always-on rules

- Caveman style, always, everywhere: prompts, docs, skills, comments, commit messages, PR bodies, replies. Minimal text, maximum meaning density. Short declaratives, no filler, no hedging, no preambles, no restating context, no politeness padding. Cut every word that carries no information. Meaning beats prose — if it reads shorter and says the same, ship the shorter one.
- Reply in the user's language.
- English-only repo: author all code, comments, identifiers, user-facing strings, docs, tests, commit messages, PR titles/bodies, and git interactions in English. Make AI response language a runtime setting (e.g. `ROAST_LANGUAGE`) instead of hardcoding a non-English prompt.
- Prefer the repo's current Python style: small functions, explicit constants, `unittest`, async tests via `unittest.IsolatedAsyncioTestCase`.
- Run `make test` before sign-off for code changes. For narrow edits, run the targeted `python -m unittest ...` first, then `make test`.
- Tests must be offline. Mock Telegram, OpenAI, Notion, network, filesystem state, and sleeps at the changed boundary.
- Keep secrets in `.env`; never commit tokens, chat IDs beyond test values, API keys, Notion IDs, or production state.
- Do not run `make dev`, `make deploy`, or remote `ssh` commands unless the user explicitly asks. They stop/restart the VPS bot.
- Codex Stop hook may run local syntax/frontmatter checks only. Do not add hooks that push, deploy, call live APIs, or mutate production state.
- Keep `.env.example`, `README.md`, tests, and code in sync when env vars, Notion schema, commands, or user-visible bot flows change.
- Feature parity: any user-visible feature change updates, in the same PR, `README.md` + `docs/`, the bot `/help` text and command list in `bot.py`, and both landing pages (`landing/index.html`, `landing/ru/index.html`). Missing surface = unfinished change.
- Landing stays sexy: distinctive, minimal, deliberate. No templated hero, no stock card grid, no generic AI-default look. Static HTML + CSS only — no client-side rendering, no framework, no build step — and SEO surface intact: semantic markup, meta, OG, JSON-LD, canonical, hreflang, sitemap.
- Landing is bilingual: EN at `landing/`, RU at `landing/ru/`. Copy changes land in both, with matching hreflang. This is the only place non-English user-facing text is allowed.
- Preserve diary behavior unless the task says otherwise: original transcription/text is previewed by default; Format changes only draft text; Save writes one Notion row.
- For Notion schema changes, update constants in `services/notion.py`, schema tests, duplicate tests when relevant, and README database docs.
- For OpenAI formatting changes, keep JSON-only responses, Russian diary prompt behavior, long-transcription metadata-only path, and fallback tests.
- For state changes, use temp paths in tests; never read or mutate `.data/message_state.json` during tests.
- Avoid broad rewrites. One behavior path, one source of truth, no speculative fallback branches.
- Autonomous delivery: from a feature branch (never `main`), commit, push, `gh pr create`, `gh pr checks --watch`, then `gh pr merge --squash --delete-branch` once green — no asking. Docs-only changes may merge without waiting for CI. Never merge on red/pending CI, push to `main`, force-push, or deploy. Skip only if `gh` is unavailable or the user opts out — say so.
