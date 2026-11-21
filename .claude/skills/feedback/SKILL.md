---
name: feedback
description: Stage 6.1 — turn a client screen recording (transcript + frames in feedback/<date>/) into docs/FEEDBACK-<date>.md and new failing stages in docs/stages.json.
argument-hint: <date folder under feedback/, e.g. 2026-11-28>
disable-model-invocation: true
model: opus
---

Pre-check: if `jq -r '.permissions.deny[]' .claude/settings.json` contains
"Edit(./docs/stages.json)", stop and tell me to run `scripts/lock-stages.sh unlock` first.
If feedback/$ARGUMENTS/ has a video but no transcript.txt / frames/, tell me the commands:
  ffmpeg -i <video> -vf fps=1/3 feedback/$ARGUMENTS/frames/%04d.png
  whisper <video> --output_format txt --output_dir feedback/$ARGUMENTS
and stop.

In feedback/$ARGUMENTS/ there is transcript.txt and frames/*.png from the client's screen
recording (timestamps in file names). Map every remark to a screen and component.
Produce docs/FEEDBACK-$ARGUMENTS.md: a table with remark, screen, file(s), severity
(bug / UX / wish), proposed fix in one line.
Then append bugs and UX items to docs/stages.json as new stages following the schema
(next free ids): passes false, attempts 0, blocked_reason null, ui true where a screen is
involved, a dod_command or browser_check that reproduces the complaint and fails today.
Validate with `npx --yes ajv-cli validate -s scripts/stages.schema.json -d docs/stages.json`.
Wishes go to docs/TODO.md. Do not implement anything.
Finish with: "Review, commit, `scripts/lock-stages.sh lock`, then /lead or ./ralph.sh."
