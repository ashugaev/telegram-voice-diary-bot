# AGENTS.md

MANDATORY: every task runs through the `manager` skill first — no exception. It decomposes, routes via the catalogs below, validates, and closes out. Never edit files, run commands, or answer a task request without it. Each agent and skill has a frontmatter `description` with triggers; read it before invoking.

## Mirror

- `AGENTS.md` and `CLAUDE.md` stay content-synced; tree-specific link paths differ.
- Files under `.agents/` and `.claude/` stay in sync. Change both in the same diff.
- `.codex/agents/*.toml` are Codex-side prompts parallel to `.claude/agents/*.md`. Update them when behavior changes.
- `.codex/hooks.json` and `.codex/hooks/` configure Codex hooks. Hooks must stay local-only and non-production.
- Keep repo rules compact. Move project specifics to `.agents/skills/diary-bot/SKILL.md` when details grow.

## Agents

Autonomous workers invoked by the agent runtime. Source: [.agents/agents/](.agents/agents/).

| Agent | Use when |
|---|---|
| [`researcher`](.agents/agents/researcher.md) | Generate 2-3 implementation options with codebase evidence |
| [`critic`](.agents/agents/critic.md) | Verify researcher claims, score options, select winner |
| [`architect`](.agents/agents/architect.md) | Produce concrete plan: touched files, steps, criteria, risks, tests |
| [`developer`](.agents/agents/developer.md) | Implement, fix after review, fix after test |
| [`reviewer`](.agents/agents/reviewer.md) | Static diff review plus local validation gate |
| [`tester`](.agents/agents/tester.md) | Run targeted Python tests, compile checks, offline behavior checks |
| [`operator`](.agents/agents/operator.md) | Review runtime, deployment, systemd, environment, and production-safety changes |

## Skills

Capabilities loaded by description match. Source: [.agents/skills/](.agents/skills/).

| Skill | Load when |
|---|---|
| [`manager`](.agents/skills/manager/SKILL.md) | Mandatory orchestrator for repo tasks |
| [`diary-bot`](.agents/skills/diary-bot/SKILL.md) | Task touches bot behavior, Telegram UX, OpenAI formatting, Notion writes, state, env, tests, or deploy |
| [`shallow-scoring`](.agents/skills/shallow-scoring/SKILL.md) | Score task complexity 1-5 |
| [`skill-writer`](.agents/skills/skill-writer/SKILL.md) | Edit skills, agents, prompts, or orchestrator instructions |
| [`code-simplifier`](.agents/skills/code-simplifier/SKILL.md) | Reduce diff overhead before review |
| [`self-verify`](.agents/skills/self-verify/SKILL.md) | Final manager close-out validation |

## Always-on rules

- Caveman style, always, everywhere: prompts, docs, skills, comments, commit messages, PR bodies, replies. Minimal text, maximum meaning density. Short declaratives, no filler, no hedging, no preambles, no restating context, no politeness padding. Cut every word that carries no information. Meaning beats prose — if it reads shorter and says the same, ship the shorter one.
- English-only repo: author all code, comments, identifiers, user-facing strings, docs, tests, commit messages, PR titles/bodies, and git interactions in English. Make AI response language a runtime setting (e.g. `ROAST_LANGUAGE`) instead of hardcoding a non-English prompt.
- Prefer the repo's current Python style: small functions, explicit constants, `unittest`, async tests via `unittest.IsolatedAsyncioTestCase`.
- Run `make test` before sign-off for code changes. For narrow edits, run the targeted `python -m unittest ...` first, then `make test`.
- Tests must be offline. Mock Telegram, OpenAI, Notion, network, filesystem state, and sleeps at the changed boundary.
- Keep secrets in `.env`; never commit tokens, chat IDs beyond test values, API keys, Notion IDs, or production state.
- Do not run `make dev`, `make deploy`, or remote `ssh` commands unless the user explicitly asks. They stop/restart the VPS bot.
- Codex Stop hook may run local syntax/frontmatter checks only. Do not add hooks that push, deploy, call live APIs, or mutate production state.
- Keep `.env.example`, `README.md`, tests, and code in sync when env vars, Notion schema, commands, or user-visible bot flows change.
- Preserve diary behavior unless the task says otherwise: formatted text is previewed by default with an Original toggle; formatting changes only draft text; Save writes one Notion row.
- For Notion schema changes, update constants in `services/notion.py`, schema tests, duplicate tests when relevant, and README database docs.
- For OpenAI formatting changes, keep JSON-only responses, Russian diary prompt behavior, long-transcription metadata-only path, and fallback tests.
- For state changes, use temp paths in tests; never read or mutate `.data/message_state.json` during tests.
- Avoid broad rewrites. One behavior path, one source of truth, no speculative fallback branches.
- Autonomous delivery: from a feature branch (never `main`), commit, push, `gh pr create`, `gh pr checks --watch`, then `gh pr merge --squash --delete-branch` once green — no asking. Docs-only changes may merge without waiting for CI. Never merge on red/pending CI, push to `main`, force-push, or deploy. Skip only if `gh` is unavailable or the user opts out — say so.
