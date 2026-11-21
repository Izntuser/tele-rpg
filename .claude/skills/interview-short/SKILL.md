---
name: interview-short
description: Stage 1.3 — short interview (10-15 questions) for a landing page, small site or a single feature, then a plan in docs/ARCHITECTURE.md.
argument-hint: <task>
disable-model-invocation: true
model: opus
---

Here is the task: $ARGUMENTS

Do not write code. Interview me with AskUserQuestion, 10-15 questions max (2-4 options
each plus your recommended default), then write the plan to docs/ARCHITECTURE.md
(goal, scope in/out, architecture, data, screens, verification command, [ASSUMPTION]
marks) and 3-5 lines to docs/DECISIONS.md. Fill the "## Stack" and the test/lint lines
of "## Commands" in CLAUDE.md (only those placeholders). Wait for my approval before
anything else. Next step after approval: /clear, then /stages.
