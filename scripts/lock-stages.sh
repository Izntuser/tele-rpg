#!/usr/bin/env bash
# usage: scripts/lock-stages.sh lock|unlock
# lock   = add "Edit(./docs/stages.json)" to permissions.deny (after you approve stages.json)
# unlock = remove it (only for /stages and /feedback, which legally write stages.json)
# Run by the human only. Agents must never run this.
set -euo pipefail
S=.claude/settings.json; RULE='Edit(./docs/stages.json)'; tmp=$(mktemp)
case "${1:?lock|unlock}" in
  lock)   jq --arg r "$RULE" '.permissions.deny |= ((. + [$r]) | unique)' "$S" > "$tmp" ;;
  unlock) jq --arg r "$RULE" '.permissions.deny |= map(select(. != $r))' "$S" > "$tmp" ;;
  *) echo "usage: $0 lock|unlock" >&2; exit 2 ;;
esac
mv "$tmp" "$S"
jq -e --arg r "$RULE" '.permissions.deny | index($r)' "$S" >/dev/null && echo "stages.json: LOCKED" || echo "stages.json: UNLOCKED"
