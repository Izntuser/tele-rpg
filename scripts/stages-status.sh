#!/usr/bin/env bash
# usage: scripts/stages-status.sh   — read-only status table of docs/stages.json
set -euo pipefail
J=docs/stages.json
[ -f "$J" ] || { echo "no $J yet (run /stages)"; exit 0; }
jq -r '
  (.stages | map({key:.id, value:.passes}) | from_entries) as $p
  | ["ID","PASS","CPLX","RISK","UI","ATT","STATE","GOAL"],
    (.stages[] | [ .id, (if .passes then "yes" else "no" end), .complexity, .risk,
      (if .ui then "ui" else "-" end), (.attempts|tostring),
      (if .passes then "done"
       elif .blocked_reason then "BLOCKED: " + .blocked_reason
       elif all(.depends_on[]; $p[.] == true) then "ready"
       else "waits " + ([.depends_on[] | select($p[.] != true)] | join(",")) end),
      (.goal | .[0:60]) ])
  | @tsv' "$J" | column -t -s $'\t'
echo
echo "left (passes=false, not blocked): $(jq '[.stages[] | select(.passes==false and .blocked_reason==null)] | length' "$J")"
