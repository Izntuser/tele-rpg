#!/usr/bin/env bash
# Live dev stack (real bot + real DB, e.g. Supabase) next to the test stack.
# Usage: scripts/live.sh start | stop | status | logs [api|web|bot|sched] | check
# Reads the repo-root .env (or LIVE_ENV_FILE). Never prints secrets.
set -euo pipefail
cd "$(dirname "$0")/.."

FAKE_TOKEN="123456789:AAFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE"
ENV_FILE="${LIVE_ENV_FILE:-.env}"
NAMES=(live-api live-web live-bot live-sched)

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi
: "${LIVE_API_PORT:=8010}"
: "${LIVE_WEB_PORT:=3010}"

mask_url() { # hide the password in scheme://user:pass@host/db
  printf '%s' "$1" | sed -E 's#(://[^:/@]*):[^@]*@#\1:****@#'
}

fail() { echo "live.sh: $*" >&2; exit 1; }

check_config() {
  local url="${DATABASE_URL:-}"
  [ -n "$url" ] || fail "DATABASE_URL is not set"
  case "$url" in
    postgresql+asyncpg://*) ;;
    postgresql://* | postgres://*)
      fail "DATABASE_URL must use the postgresql+asyncpg:// scheme (the app is async; plain postgresql:// or postgres:// would load the sync driver). Change the prefix to postgresql+asyncpg://" ;;
    *) fail "DATABASE_URL must start with postgresql+asyncpg://" ;;
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
    *:6543/*) fail "DATABASE_URL uses port 6543 (Supabase transaction pooler); use the session pooler or the direct host on port 5432" ;;
  esac
  [ -n "${TG_BOT_TOKEN:-}" ] || fail "TG_BOT_TOKEN is not set"
  [ "$TG_BOT_TOKEN" != "$FAKE_TOKEN" ] || fail "TG_BOT_TOKEN is the fake dev token; put a real bot token in .env"
  echo "config ok: db $(mask_url "$url"), api :$LIVE_API_PORT, web :$LIVE_WEB_PORT"
}

pid_alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }
port_busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

start_proc() { # name port command...  (port "-" = none)
  local name=$1 port=$2 pidfile="logs/$1.pid" pid=""
  shift 2
  [ -f "$pidfile" ] && pid=$(cat "$pidfile")
  if pid_alive "$pid"; then
    echo "$name already running (pid $pid)"
    return 0
  fi
  [ -f "$pidfile" ] && rm -f "$pidfile"
  if [ "$port" != "-" ] && port_busy "$port"; then
    echo "ERROR: port :$port is busy (not this live stack's $name)" >&2
    exit 1
  fi
  nohup "$@" >"logs/$name.log" 2>&1 </dev/null &
  echo $! >"$pidfile"
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

cmd_start() {
  check_config
  mkdir -p logs
  export APP_ENV=development
  export DATABASE_URL TG_BOT_TOKEN
  (cd backend && uv run alembic upgrade head)
  start_proc live-api "$LIVE_API_PORT" bash -c "cd backend && exec uv run uvicorn app.main:app --host 127.0.0.1 --port $LIVE_API_PORT"
  start_proc live-web "$LIVE_WEB_PORT" env VITE_DEV_PORT="$LIVE_WEB_PORT" API_PROXY_TARGET="http://127.0.0.1:$LIVE_API_PORT" \
    bash -c 'cd frontend && exec pnpm exec vite'
  start_proc live-bot - bash -c 'cd backend && exec uv run python -m app.bot.polling'
  start_proc live-sched - bash -c 'cd backend && exec uv run python -m app.jobs.runner'
  wait_for "http://127.0.0.1:$LIVE_API_PORT/healthz"
  wait_for "http://127.0.0.1:$LIVE_WEB_PORT/healthz"
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
  local name pid
  for name in "${NAMES[@]}"; do
    pid=""
    [ -f "logs/$name.pid" ] && pid=$(cat "logs/$name.pid")
    if pid_alive "$pid"; then
      pkill -TERM -P "$pid" 2>/dev/null || true
      kill "$pid" 2>/dev/null || true
      echo "stopped $name (pid $pid)"
    else
      echo "$name not running"
    fi
    rm -f "logs/$name.pid"
  done
}

cmd_status() {
  local name pid state
  for name in "${NAMES[@]}"; do
    pid=""
    [ -f "logs/$name.pid" ] && pid=$(cat "logs/$name.pid")
    if pid_alive "$pid"; then state=alive; else state=dead; fi
    echo "$name pid=${pid:--} $state"
  done
  echo "api http://127.0.0.1:$LIVE_API_PORT  web http://127.0.0.1:$LIVE_WEB_PORT"
  if [ -n "${DATABASE_URL:-}" ]; then echo "db $(mask_url "$DATABASE_URL")"; fi
}

cmd_logs() {
  if [ -n "${1:-}" ]; then
    tail -n 80 -f "logs/live-$1.log"
  else
    tail -n 40 -f logs/live-*.log
  fi
}

case "${1:-}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  logs) shift; cmd_logs "${1:-}" ;;
  check) check_config ;;
  *) echo "usage: scripts/live.sh start|stop|status|logs [api|web|bot|sched]|check" >&2; exit 2 ;;
esac
