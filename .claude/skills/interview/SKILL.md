---
name: interview
description: Stage 1.1 — architect interviews the human (50+ questions via AskUserQuestion) about the client brief before any spec or code. Run in plan mode with Opus.
argument-hint: <client brief text or path to a brief file>
disable-model-invocation: true
model: opus
---

If the argument below is a path to a file, read that file and use its content as the brief.
If the argument is empty, ask me to paste the brief and wait.
If the domain looks unfamiliar or niche, first offer (one AskUserQuestion) to explain the
domain and typical solutions before the interview.

You are the lead architect on this project. Below is the raw brief from the client.
Do NOT write any code and do NOT propose an architecture yet.

First, interview me. Use the AskUserQuestion tool so I can pick from options.
Ask at least 50 questions in total, in batches of 4-6, covering in this order:
1. Business goal and who the users are; what "done" means for the client
2. Scope: must-have vs nice-to-have vs explicitly out of scope
3. Data model: entities, relationships, volumes, retention
4. Integrations and external APIs, auth, payments
5. Non-functional: load, security, compliance, languages, mobile
6. Infrastructure: hosting, CI/CD, environments, existing code we must reuse
7. UX: pages/screens, roles, admin needs, design source (Figma? none?)
8. Delivery: what the client sees first, demo cadence, acceptance criteria

Also make sure the answers pin down the tech stack and package manager, and whether the
project has any web UI (site, admin panel, Telegram Mini App) that Playwright can test.

For every question give 2-4 concrete options plus your recommended default,
so I can answer fast. Skip questions the brief already answers.
When you have no more material questions, say INTERVIEW COMPLETE and stop, and tell me:
"Leave plan mode (Shift+Tab) and run /spec in this same session."

<brief>
$ARGUMENTS
</brief>
