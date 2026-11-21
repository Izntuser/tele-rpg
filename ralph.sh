#!/usr/bin/env bash
# ralph.sh: fresh lead session per iteration; state lives in stages.json, PROGRESS.md, git
# usage: MAX=30 ./ralph.sh      (run inside tmux: tmux new -s night)
set -e
cd "$(dirname "$0")"
MAX=${MAX:-30}
LOG="logs/ralph-$(date +%Y%m%d-%H%M).log"
left() { jq '[.stages[] | select(.passes==false and .blocked_reason==null)] | length' docs/stages.json; }
[ -f docs/stages.json ] || { echo "no docs/stages.json: run /stages first"; exit 1; }
for i in $(seq 1 "$MAX"); do
  echo "=== iteration $i, stages left: $(left) ===" | tee -a "$LOG"
  [ "$(left)" -eq 0 ] && { echo done | tee -a "$LOG"; exit 0; }
  claude -p "$(cat docs/LOOP-PROMPT.md)" --model opus --permission-mode acceptEdits \
    --max-turns 200 2>&1 | tee -a "$LOG" || true
  sleep 30
done
echo "MAX=$MAX iterations reached, stages left: $(left)" | tee -a "$LOG"
