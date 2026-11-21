---
name: hygiene
description: Stage 5.1 — weekly context cleanup proposal for CLAUDE.md, PROGRESS, LEAD-LOG, stages.json, TODO, DECISIONS. Proposes a plan, applies nothing without approval.
disable-model-invocation: true
model: opus
---

Read CLAUDE.md, docs/ARCHITECTURE.md, docs/DECISIONS.md, docs/TODO.md, docs/PROGRESS.md,
docs/LEAD-LOG.md and docs/stages.json. Also run `git worktree list` and `git branch`.
Act as a skeptical editor. Propose, do not apply:
- CLAUDE.md: keep only rules whose removal would cause a concrete mistake. Target under 50 lines.
- PROGRESS.md: collapse entries older than 7 days into a 5-line summary at the top.
- LEAD-LOG.md: list every FALLBACK and PARTIAL with the stage's complexity; suggest
  which stages were misclassified or too big.
- stages.json: list passed stages to archive into docs/stages-archive.json; for blocked
  ones propose a split.
- TODO.md: drop items already done (check the code); group the rest into proposed
  new stages with a dod_command each.
- DECISIONS.md: group [AUTO] lines, flag those contradicting ARCHITECTURE.md.
- ARCHITECTURE.md: flag places that no longer match the code.
- Leftover worktrees and branches to remove.
Show the diff as a plan. Wait for my approval. Changes to docs/stages.json need
`scripts/lock-stages.sh unlock` by me first.
