#!/usr/bin/env bash
# usage: scripts/check-stage.sh <id> [--mark]
set -euo pipefail
ID="${1:?stage id}"; MARK="${2:-}"
J=docs/stages.json
jq -e --arg id "$ID" '.stages[] | select(.id==$id)' "$J" >/dev/null \
  || { echo "unknown stage: $ID" >&2; exit 2; }
get() { jq -r --arg id "$ID" ".stages[] | select(.id==\$id) | $1" "$J"; }
CMD=$(get '.dod_command // empty'); UI=$(get '.browser_check // empty')
[ -n "$CMD" ] || { echo "$ID has no dod_command" >&2; exit 2; }
echo "== $ID dod: $CMD"; bash -c "$CMD"
if [ -n "$UI" ]; then echo "== $ID browser: $UI"; bash -c "$UI"; fi
echo "== $ID PASSED"
if [ "$MARK" = "--mark" ]; then
  tmp=$(mktemp)
  jq --arg id "$ID" '(.stages[] | select(.id==$id) | .passes) = true' "$J" > "$tmp" && mv "$tmp" "$J"
  echo "== $ID marked passes=true"
fi
