#!/usr/bin/env bash
# usage: scripts/block-stage.sh <id> "<reason>"  |  scripts/block-stage.sh <id> --clear
set -euo pipefail
ID="${1:?stage id}"; REASON="${2:?reason or --clear}"
J=docs/stages.json
jq -e --arg id "$ID" '.stages[] | select(.id==$id)' "$J" >/dev/null \
  || { echo "unknown stage: $ID" >&2; exit 2; }
tmp=$(mktemp)
if [ "$REASON" = "--clear" ]; then
  jq --arg id "$ID" '(.stages[] | select(.id==$id) | .blocked_reason) = null' "$J" > "$tmp"
else
  jq --arg id "$ID" --arg r "$REASON" \
    '(.stages[] | select(.id==$id)) |= (.blocked_reason = $r | .attempts += 1)' "$J" > "$tmp"
fi
mv "$tmp" "$J"
echo "== $ID blocked_reason: $(jq -r --arg id "$ID" '.stages[] | select(.id==$id) | .blocked_reason' "$J")"
