---
name: spec
description: Stage 1.2 — after INTERVIEW COMPLETE, write docs/ARCHITECTURE.md and docs/DECISIONS.md, and fill the Stack/Commands placeholders in CLAUDE.md. Same session as /interview, outside plan mode.
disable-model-invocation: true
model: opus
---

Now write docs/ARCHITECTURE.md based on everything we discussed. Structure:

1. Goal and users (5 lines max)
2. Scope: in / out, as two lists
3. Architecture: components, how they talk, why this choice over the obvious alternative
4. Data model: entities with key fields and relations
5. API surface: list of endpoints or server actions with one line each
6. Screens/pages with the role that sees each
7. Non-functional requirements and how each is satisfied
8. Infrastructure and environments
9. Open questions for the client (things I could not answer)
10. Verification: how we will prove the whole system works end to end
   (the exact command or script, e.g. `pnpm test:e2e`, and what it checks)

Rules: name concrete files, packages and interfaces. No marketing language.
If you had to assume something, mark it [ASSUMPTION].
Then write docs/DECISIONS.md with the 5-10 key decisions, one line each: decision, reason.

Then update CLAUDE.md, touching ONLY these placeholders:
- "## Stack": one or two lines with the chosen stack.
- "## Commands": the `test:` and `lint:` lines (real commands for this stack). If the
  project has no web UI, replace the e2e line with "e2e: none (no web UI)".
Keep the rest of CLAUDE.md byte-for-byte.

If the stack does not use pnpm (e.g. npm, bun, uv, go), list the exact allow rules that
should replace "Bash(pnpm *)" in .claude/settings.json and ask me before editing it.

Finish by printing: "Spec written. Review docs/ARCHITECTURE.md, then /clear and run /stages."
