# Project: tele-rpg

## Stack
Frontend: React 19 + TypeScript + Vite + Tailwind/shadcn + TanStack Query, Telegram Mini App (pnpm).
Backend: Python 3.13 + FastAPI + SQLAlchemy 2 (async) + Alembic + aiogram 3 + APScheduler, PostgreSQL 17 (uv).

## Commands
- bootstrap: ./init.sh            (idempotent: docker up, install, migrate, dev server)
- smoke: scripts/smoke.sh         (must pass before you start any work)
- test: pnpm test                 (vitest --run in frontend + uv run pytest in backend)
- lint: pnpm lint                 (eslint + tsc in frontend + ruff check/format --check + mypy in backend)
- e2e: pnpm e2e --grep @<id>      (Playwright; saves docs/screens/<id>.png; only if the project has a web UI)
- stage check: scripts/check-stage.sh <id>              (runs the stage's definition of done)
- stage done:  scripts/check-stage.sh <id> --mark        (the ONLY way to set passes=true)
- stage block: scripts/block-stage.sh <id> "<reason>"    (the ONLY way to block a stage)
- status: scripts/stages-status.sh

## Session start (every session, in this order)
1. pwd (you must be inside a git checkout; if the directory is gone, stop and report)
2. git log --oneline -15
3. tail -40 docs/PROGRESS.md
4. ./init.sh, then scripts/smoke.sh. If smoke fails, fixing it IS your task; do not
   start new work on a broken base. Exception: if init.sh or smoke.sh do not exist yet,
   S01 has not passed; skip this step (creating them is S01's job).
5. Read docs/ARCHITECTURE.md and your stage in docs/stages.json.

## Routing (tech lead only; mechanical, by fields in docs/stages.json)
| complexity | risk      | worker                 | review                                              |
| low        | normal    | codex-worker           | stage-reviewer                                      |
| medium     | normal    | stage-worker (sonnet)  | stage-reviewer                                      |
| high       | normal    | stage-worker (opus)    | stage-reviewer                                      |
| any        | sensitive | stage-worker (opus)    | stage-reviewer + codex-reviewer, merge on 2 APPROVE |
Pass the model as an override when launching stage-worker.
codex-worker reports FALLBACK -> re-dispatch to stage-worker (sonnet).
codex-reviewer reports UNAVAILABLE -> stage-reviewer alone, plus a second stage-reviewer
run with model opus told to focus on security; log it.

## Rules
- The main session never writes application code. It only delegates, reviews, merges, logs.
- One stage per session. Never start a second stage, even if context remains.
- docs/stages.json is NEVER edited by hand. Only scripts/check-stage.sh --mark and
  scripts/block-stage.sh may change it. Never delete, weaken or rewrite dod_command,
  browser_check or test_steps. This is not negotiable.
- Anything outside the current stage: one line in docs/TODO.md, not code.
- Every change has a test. Full suite green before commit.
- No native alert()/confirm()/prompt() in the UI; agents cannot see them.
- Never edit .env or secrets. Never run destructive git commands. Never git push.

## Session end (every session)
1. Commit with a conventional message. Repo must be mergeable: no broken tests, no
   half-done files.
2. Append to docs/PROGRESS.md: date, stage id, what was done, what is left, anything
   broken or surprising. 3-5 lines.
3. If you are running low on context: stop early, commit, write PROGRESS, and report
   the stage as PARTIAL. A clean partial beats a messy "done".
