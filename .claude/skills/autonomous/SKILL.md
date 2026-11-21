---
name: autonomous
description: Stage 3.1 + 4.1 — unattended tech lead in the current session (no questions to the human, [AUTO] decisions, done only when the jq count is 0, writes NIGHT-REPORT.md). For multi-hour runs prefer ./ralph.sh.
argument-hint: [hours away, default 8]
disable-model-invocation: true
model: opus
---

Hours I will be away (8 if empty): $ARGUMENTS. Do not stop to ask me questions.

Read docs/LOOP-PROMPT.md and follow it exactly, from "## Start" to "## Before you stop".
It is your full instruction set for this run. Keep looping over stages until the jq count
in its "## Done" section prints 0 or no stage can be started; then write
docs/NIGHT-REPORT.md and stop.
