#!/usr/bin/env bash
# Live dev stack (real bot + real DB, e.g. Supabase) next to the test stack.
# Usage: scripts/live.sh start | stop | status | logs [api|web|bot|sched] | check
# Reads the repo-root .env (or LIVE_ENV_FILE) with a plain KEY=VALUE parser (no shell
# expansion). Never prints secrets.
set -euo pipefail
cd "$(dirname "$0")/.."

FAKE_TOKEN="123456789:AAFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE"
ENV_FILE="${LIVE_ENV_FILE:-.env}"
NAMES=(live-api live-web live-bot live-sched)

DEV_JWT_SECRET="dev-jwt-secret-change-me"

# Keys taken from the env file (everything else is ignored): what this script needs plus the
# Settings fields of backend/app/core/config.py the app reads from the environment.
# APP_ENV is deliberately absent: the live stack always runs development.
ENV_KEYS=" DATABASE_URL E2E_DATABASE_URL TG_BOT_TOKEN TG_BOT_USERNAME TG_APP_SHORT_NAME TG_WEBHOOK_SECRET PUBLIC_BASE_URL JWT_SECRET JWT_TTL_SECONDS LIVE_API_PORT LIVE_WEB_PORT DB_POOL_SIZE STORAGE_DIR IMAGE_PROCESS_CONCURRENCY SENTRY_DSN FRONTEND_DIST "

# xtrace off while handling secrets; the caller restores it with xt_restore.
xt_off() { XT_WAS=0; case $- in *x*) XT_WAS=1 ;; esac; { set +x; } 2>/dev/null; }
xt_restore() { if [ "${XT_WAS:-0}" = 1 ]; then set -x; fi; }

# Plain KEY=VALUE parser: no shell evaluation, no expansion. Skips blank lines and # comments,
# accepts an optional leading "export ", strips one matching pair of surrounding quotes.
load_env() {
  local line key val
  [ -f "$ENV_FILE" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    line="${line#"${line%%[![:space:]]*}"}"
    case "$line" in '' | '#'*) continue ;; esac
    case "$line" in export[[:space:]]*) line="${line#export}"; line="${line#"${line%%[![:space:]]*}"}" ;; esac
    case "$line" in *=*) ;; *) continue ;; esac
    key="${line%%=*}"
    val="${line#*=}"
    key="${key%"${key##*[![:space:]]}"}"
    case "$ENV_KEYS" in *" $key "*) ;; *) continue ;; esac
    case "$val" in
      \"*\") [ "${#val}" -ge 2 ] && val="${val:1:${#val}-2}" ;;
      \'*\') [ "${#val}" -ge 2 ] && val="${val:1:${#val}-2}" ;;
      *) val="${val%"${val##*[![:space:]]}"}" ;;
    esac
    export "$key=$val"
  done <"$ENV_FILE"
}

xt_off
load_env
xt_restore
: "${LIVE_API_PORT:=8010}"
: "${LIVE_WEB_PORT:=3010}"

# Mask everything between "user:" and the LAST '@' (passwords may hold raw '@' and ':').
mask_url() {
  printf '%s' "$1" | sed -E 's#^([A-Za-z0-9+.-]+://[^:/@]*):.*@([^@]*)$#\1:****@\2#'
}

fail() { echo "live.sh: $*" >&2; exit 1; }

check_ports() {
  local p v
  for p in LIVE_API_PORT LIVE_WEB_PORT; do
    v="${!p}"
    case "$v" in '' | *[!0-9]*) fail "$p must be a number, got '$v'" ;; esac
    v=$((10#$v))
    { [ "$v" -ge 1024 ] && [ "$v" -le 65535 ]; } || fail "$p must be between 1024 and 65535"
    { [ "$v" -ne 8000 ] && [ "$v" -ne 3000 ]; } || fail "$p is $v, which belongs to the test stack (8000/3000); use another port"
    export "$p=$v"
  done
  [ "$LIVE_API_PORT" -ne "$LIVE_WEB_PORT" ] || fail "LIVE_API_PORT and LIVE_WEB_PORT are equal ($LIVE_API_PORT)"
}

check_config() {
  check_ports
  xt_off
  local url="${DATABASE_URL:-}"
  [ -n "$url" ] || fail "DATABASE_URL is not set"
  case "$url" in
    # The app normalizes postgres:// and postgresql:// to +asyncpg (Settings), so all pass.
    postgresql+asyncpg://* | postgresql://* | postgres://*) ;;
    *) fail "DATABASE_URL must start with postgresql://, postgres:// or postgresql+asyncpg://" ;;
  esac
  if [ -n "${E2E_DATABASE_URL:-}" ] && [ "$url" = "$E2E_DATABASE_URL" ]; then
    fail "DATABASE_URL equals E2E_DATABASE_URL; the live stack must not use the e2e database"
  fi
  local dbname="${url%%\?*}"
  dbname="${dbname##*/}"
  case "$dbname" in
    *_e2e) fail "DATABASE_URL points at an _e2e database ($dbname); refusing" ;;
  esac
  case "$url" in
    *:6543 | *:6543/* | *:6543\?*) fail "DATABASE_URL uses port 6543 (Supabase transaction pooler); use the session pooler or the direct host on port 5432" ;;
  esac
  [ -n "${TG_BOT_TOKEN:-}" ] || fail "TG_BOT_TOKEN is not set"
  [ "$TG_BOT_TOKEN" != "$FAKE_TOKEN" ] || fail "TG_BOT_TOKEN is the fake dev token; put a real bot token in .env"
  [ -n "${JWT_SECRET:-}" ] || fail "JWT_SECRET is not set; the live stack is internet-reachable. Generate one: openssl rand -hex 32"
  [ "$JWT_SECRET" != "$DEV_JWT_SECRET" ] || fail "JWT_SECRET is the dev default; generate one: openssl rand -hex 32"
  [ "${#JWT_SECRET}" -ge 32 ] || fail "JWT_SECRET is shorter than 32 characters; generate one: openssl rand -hex 32"
  echo "config ok: db $(mask_url "$url"), api :$LIVE_API_PORT, web :$LIVE_WEB_PORT"
  xt_restore
}

is_pid() { case "${1:-}" in '' | *[!0-9]*) return 1 ;; *) return 0 ;; esac; }
pid_alive() { is_pid "${1:-}" && kill -0 "$1" 2>/dev/null; }
port_busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

# Does the live process $2 look like the service $1? (guards against pid reuse)
pid_matches() {
  local cmd
  cmd=$(ps -o command= -p "$2" 2>/dev/null) || return 1
  case "$1" in
    live-api) case "$cmd" in *"uvicorn app.main:app"*) case "$cmd" in *"$LIVE_API_PORT"*) return 0 ;; esac ;; esac ;;
    live-web) case "$cmd" in *vite*) return 0 ;; esac ;;
    live-bot) case "$cmd" in *app.bot.polling*) return 0 ;; esac ;;
    live-sched) case "$cmd" in *app.jobs.runner*) return 0 ;; esac ;;
  esac
  return 1
}

read_pid() { # name -> pid on stdout (empty if none or not numeric)
  local pid=""
  [ -f "logs/$1.pid" ] && pid=$(cat "logs/$1.pid" 2>/dev/null || true)
  is_pid "$pid" && printf '%s' "$pid"
  return 0
}

# Running = pid alive AND its command matches the service. Prints a note for stale pidfiles.
is_running() { # name pid
  pid_alive "$2" && pid_matches "$1" "$2"
}

descendants() {
  local c
  for c in $(pgrep -P "$1" 2>/dev/null || true); do
    descendants "$c"
    echo "$c"
  done
}

stop_one() {
  local name=$1 pid
  pid=$(read_pid "$name")
  if [ -z "$pid" ]; then
    echo "$name not running"
  elif ! pid_alive "$pid"; then
    echo "$name not running (stale pidfile removed)"
  elif ! pid_matches "$name" "$pid"; then
    echo "$name: pid $pid is another process now (stale pidfile removed, not killing)"
  else
    local kids
    kids=$(descendants "$pid")
    # shellcheck disable=SC2086
    [ -n "$kids" ] && kill -TERM $kids 2>/dev/null || true
    kill "$pid" 2>/dev/null || true
    echo "stopped $name (pid $pid)"
  fi
  rm -f "logs/$name.pid"
}

STARTED_NAMES=""

start_proc() { # name port command...  (port "-" = none)
  local name=$1 port=$2 pidfile="logs/$1.pid" pid
  shift 2
  pid=$(read_pid "$name")
  if is_running "$name" "$pid"; then
    echo "$name already running (pid $pid)"
    return 0
  fi
  [ -f "$pidfile" ] && echo "$name: removing stale pidfile" && rm -f "$pidfile"
  if [ "$port" != "-" ] && port_busy "$port"; then
    echo "ERROR: port :$port is busy (not this live stack's $name)" >&2
    exit 1
  fi
  nohup "$@" >"logs/$name.log" 2>&1 </dev/null &
  echo $! >"$pidfile"
  STARTED_NAMES="$STARTED_NAMES $name"
  echo "started $name (pid $!)"
}

wait_for() {
  for _ in $(seq 1 60); do
    curl -fsS "$1" >/dev/null 2>&1 && return 0
    sleep 1
  done
  echo "timeout waiting for $1 (see logs/live-*.log)" >&2
  return 1
}

on_start_exit() {
  local rc=$?
  trap - EXIT
  if [ "$rc" -ne 0 ]; then
    echo "live.sh: start FAILED (exit $rc); stopping the services this run started" >&2
    local n
    for n in $STARTED_NAMES; do stop_one "$n" >&2; done
    echo "live.sh: nothing is left running from this run; see logs/live-*.log" >&2
  fi
  exit "$rc"
}

cmd_start() {
  check_config
  mkdir -p logs
  trap on_start_exit EXIT
  export APP_ENV=development
  (cd backend && uv run alembic upgrade head) || { echo "live.sh: migration failed" >&2; return 1; }
  start_proc live-api "$LIVE_API_PORT" bash -c 'cd backend && exec uv run uvicorn app.main:app --host 127.0.0.1 --port "$1"' _ "$LIVE_API_PORT"
  start_proc live-web "$LIVE_WEB_PORT" env VITE_DEV_PORT="$LIVE_WEB_PORT" API_PROXY_TARGET="http://127.0.0.1:$LIVE_API_PORT" \
    bash -c 'cd frontend && exec pnpm exec vite'
  start_proc live-bot - bash -c 'cd backend && exec uv run python -m app.bot.polling'
  start_proc live-sched - bash -c 'cd backend && exec uv run python -m app.jobs.runner'
  wait_for "http://127.0.0.1:$LIVE_API_PORT/healthz"
  wait_for "http://127.0.0.1:$LIVE_WEB_PORT/healthz"
  trap - EXIT
  cat <<N

Live stack is up: api http://127.0.0.1:$LIVE_API_PORT, web http://127.0.0.1:$LIVE_WEB_PORT
Next steps:
  1. Tunnel the web port:  ngrok http $LIVE_WEB_PORT
  2. In BotFather: Main App -> Menu Button -> Direct Link = the https tunnel URL.
  3. Set PUBLIC_BASE_URL=<tunnel URL> in .env.
  4. Restart: scripts/live.sh stop && scripts/live.sh start
N
}

cmd_stop() {
  local name
  for name in "${NAMES[@]}"; do stop_one "$name"; done
}

cmd_status() {
  local name pid state
  for name in "${NAMES[@]}"; do
    pid=$(read_pid "$name")
    if is_running "$name" "$pid"; then state=alive; elif pid_alive "$pid"; then state="stale (pid reused)"; else state=dead; fi
    echo "$name pid=${pid:--} $state"
  done
  echo "api http://127.0.0.1:$LIVE_API_PORT  web http://127.0.0.1:$LIVE_WEB_PORT"
  xt_off
  if [ -n "${DATABASE_URL:-}" ]; then echo "db $(mask_url "$DATABASE_URL")"; fi
  xt_restore
}

cmd_logs() {
  if [ -n "${1:-}" ]; then
    tail -n 80 -f "logs/live-$1.log"
  else
    tail -n 40 -f logs/live-*.log
  fi
}

case "${1:-}" in start | stop | status) check_ports ;; esac
case "${1:-}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  logs) shift; cmd_logs "${1:-}" ;;
  check) check_config ;;
  *) echo "usage: scripts/live.sh start|stop|status|logs [api|web|bot|sched]|check" >&2; exit 2 ;;
esac
