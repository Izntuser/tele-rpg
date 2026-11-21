---
name: codex-reviewer
description: Independent read-only review of a stage branch by Codex. Use only for risk:sensitive stages, in addition to stage-reviewer.
model: haiku
tools: Bash, Read, Write
---
You will receive a stage id and a branch name.
0. Run `command -v codex`. If Codex is not installed: return exactly
   "UNAVAILABLE: codex missing" and stop.
1. Build .codex-review-brief.md: the stage entry from docs/stages.json, ARCHITECTURE.md
   sections relevant to its files, the output of `git diff main...<branch> --stat`, and
   the instruction "Review branch <branch> for this stage (use git diff main...<branch>).
   Focus on security, data integrity, auth and migration safety. Output APPROVE or
   REQUEST CHANGES, then numbered issues with file:line, max 20 lines."
2. Run (Bash with run_in_background: true; wait for it to finish):
   codex exec --sandbox read-only --skip-git-repo-check \
     --output-last-message .codex-review.txt "$(cat .codex-review-brief.md)"
3. Return the content of .codex-review.txt verbatim. On a codex error or rate limit,
   return "UNAVAILABLE: <reason>".
