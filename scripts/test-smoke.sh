#!/usr/bin/env bash
# Proves smoke.sh fails (non-zero, naming the check) when the API is down.
# Points smoke.sh at a dead port via API_URL; touches no shared process.
set -uo pipefail
cd "$(dirname "$0")/.."

out=$(API_URL=http://127.0.0.1:9 scripts/smoke.sh 2>&1)
code=$?
[ "$code" -ne 0 ] || { echo "test-smoke FAIL: smoke.sh exited 0 with API down" >&2; exit 1; }
echo "$out" | grep -q "SMOKE FAIL: api /healthz unreachable" \
  || { echo "test-smoke FAIL: failing check not named: $out" >&2; exit 1; }
echo "test-smoke ok"
