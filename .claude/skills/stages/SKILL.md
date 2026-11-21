---
name: stages
description: Stage 2.1 — engineering manager splits ARCHITECTURE.md into 6-15 stages in docs/stages.json (validated against the schema) and docs/STAGES.md. Fresh session, Opus.
disable-model-invocation: true
model: opus
---

Pre-check: run `jq -r '.permissions.deny[]' .claude/settings.json`. If it contains
"Edit(./docs/stages.json)", stop and tell me to run `scripts/lock-stages.sh unlock` in my
terminal first.

Read docs/ARCHITECTURE.md and docs/DECISIONS.md.

You are the engineering manager. Split the implementation into 6-15 stages and write
them to docs/stages.json using exactly the schema in scripts/stages.schema.json
(plain JSON, no comments). Then validate:
  npx --yes ajv-cli validate -s scripts/stages.schema.json -d docs/stages.json
and fix until it is valid. Also verify with jq that every depends_on id exists and that
there are no cycles. Then generate docs/STAGES.md as a human-readable summary
of the same data.

The template files already exist in the repo and must not be rewritten:
CLAUDE.md, AGENTS.md, scripts/*, .claude/settings.json, .claude/agents/*, .claude/skills/*,
.worktreeinclude, playwright.config.ts, ralph.sh, docs/LOOP-PROMPT.md.

Constraints:
- A stage fits one agent session without running out of context: roughly 5-15 files.
  If bigger, split it.
- Each stage leaves the repo working and tested. depends_on must reference existing
  ids and be acyclic.
- S01 is always the skeleton and nothing else: repo layout, Docker Compose, CI, test
  runner, lint, init.sh that brings everything up idempotently, scripts/smoke.sh that
  proves the app is alive (exits non-zero when it is not).
  If the project has a web UI: Playwright wired in: @playwright/test installed,
  chromium installed, an "e2e": "playwright test" script in package.json, and
  e2e/smoke.spec.ts tagged @S01 that opens the home page and saves
  docs/screens/S01.png. S01 is then ui:true with browser_check "pnpm e2e --grep @S01".
  If there is no web UI (e.g. a pure Telegram bot), S01 is ui:false and its dod_command
  runs init.sh + smoke.sh + the test suite.
- An early stage holds all shared contracts (DB schema, API types, shared packages)
  so parallel stages build on the same base.
- For every stage: goal, files, dod_command (a real command that exits non-zero on
  failure), 3-6 test_steps written as observable behaviour, complexity, risk, ui.
- ui: true requires browser_check "pnpm e2e --grep @<id>": a Playwright test tagged
  @<id> that walks the screen as a user and saves docs/screens/<id>.png.
- risk: sensitive for anything touching auth, payments, migrations on existing data,
  personal data, or public API contracts.
- Do not mark everything high: use low/medium/high honestly, or routing stops working.
- All stages start with passes: false, attempts: 0, blocked_reason: null.
- Before writing, tell me where you expect agents to struggle and what rule or context
  would prevent it; put that into the stage's test_steps or propose a CLAUDE.md line.

Do not start implementing.

At the end print the human checklist:
- run 1-2 dod_commands now and confirm they FAIL (functionality does not exist yet);
- no "build the whole backend" stage;
- stages that could run in parallel do not overlap in `files`;
- risk: sensitive everywhere it belongs;
- complexity not inflated.
Then: "When approved: commit, run `scripts/lock-stages.sh lock` in your terminal, /clear,
then /next-stage (step by step) or /lead (loop)."
