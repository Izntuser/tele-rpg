---
name: status
description: Show the current stage status table, blocked stages, Needs-human items and the last lead-log lines. Read-only.
disable-model-invocation: true
---

Run scripts/stages-status.sh, then `tail -15 docs/LEAD-LOG.md`, and show the
"## Needs human" section of docs/TODO.md. Print them as-is with a 2-line summary
(how many done / left / blocked, and what needs me). Change nothing.
