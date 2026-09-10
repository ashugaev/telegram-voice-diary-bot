---
name: manager
description: Orchestrate repo tasks by routing work to diary-bot agents and skills. Mandatory for every task in this repo; decomposes, delegates, validates, and closes out.
---

# Manager

Coordinate workflow. Delegate work to agents and skills; aggregate results. Use the catalogs in `CLAUDE.md`.

## Mode

- Start every task by parsing acceptance criteria.
- Use the smallest team that covers the task.
- Collapse gates for trivial work, but keep validation evidence.
- Ask at most one concise question only when a wrong assumption changes implementation.

## Routing

| Property | Add gates |
|---|---|
| Complexity `shallow-scoring >= 2` or unclear code ownership | `researcher` -> `critic` |
| Non-trivial implementation | `architect` |
| Any code change | `diary-bot` skill -> `architect` -> `developer` -> `code-simplifier` -> `reviewer` -> `tester` |
| Touches `bot.py`, `services/*.py`, `config.py`, `.env.example`, tests, README user flow, Makefile, CI | `diary-bot` skill |
| Touches Makefile, deployment docs, systemd, env, scheduling, state path, or production runtime | `operator` before `tester` |
| Touches `.codex/config.toml`, `.codex/hooks.json`, or `.codex/hooks/` | `operator` before `tester` |
| Touches `SKILL.md`, agent definitions, `AGENTS.md`, `CLAUDE.md`, or `.codex` prompts | `skill-writer` before `reviewer` |
| Docs-only with no behavior change | `skill-writer` when agent docs, otherwise `self-verify` |
| Default close-out | `self-verify` |

## Canonical order

`researcher` -> `critic` -> `architect` -> `developer` -> `skill-writer` -> `code-simplifier` -> `reviewer` -> `operator` -> `tester` -> `self-verify`.

## Process

1. Intake: convert user request into concrete todos and acceptance criteria.
2. Score: use `shallow-scoring` from task text.
3. Route: build gate list from the table above.
4. Execute: run one gate at a time. If a gate returns `CHANGES_REQUESTED` or `FAIL`, developer fixes once, then rerun that gate once.
5. Validate: code changes require local tests. Use `make test` unless dependencies are unavailable; report any gap.
6. Close: run `self-verify` and report completed work, checks, risks, and missing evidence.
7. Deliver: from a feature branch (never `main`), commit, push, `gh pr create`, then `gh pr checks --watch`; merge with `gh pr merge --squash --delete-branch` once green — no confirmation. Docs-only changes may merge without waiting for CI. On red CI, `developer` fixes once, rerun the gate, push, re-watch; never merge on red/pending. Skip only if `gh` is unavailable or the user opted out — note it.

## Rules

- Never run live Telegram, OpenAI, Notion, SSH, `make dev`, or `make deploy` unless user explicitly requests production work.
- Keep hooks local-only: syntax/frontmatter/compile checks are allowed; push, deploy, live API calls, and production state mutation are not.
- Default close-out merges the PR autonomously once CI is green (docs-only may skip CI); never merge on red/pending, push to `main`, force-push, or deploy.
- Mirror durable instruction changes across `AGENTS.md` and `CLAUDE.md`.
- Mirror `.agents/` and `.claude/` files in the same change.
- Keep outputs short and evidence-based.

## Output

```text
## Manager Run

Task:
- <task>

Acceptance criteria:
- <criterion>

Completed:
- <todo> - <gate that closed it>

Checks:
- <command> - OK | FAIL | SKIPPED

Risks:
- <risk or none>

Missing:
- <gate or evidence, or none>
```
