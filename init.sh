#!/usr/bin/env bash
# Idempotent bootstrap: Postgres, deps, migrations, then uvicorn (8000) and Vite (3000) in the
# background with PID files and logs under logs/. Safe to run repeatedly.
# SKIP_DOCKER=1 skips `docker compose` (CI provides Postgres as a service).
set -euo pipefail
cd "$(dirname "$0")"

# Config: .env if present, else .env.example, else the built-in defaults below.
for f in .env .env.example; do
  if [ -f "$f" ]; then
    set -a
    # shellcheck disable=SC1090
    . "./$f"
    set +a
    break
  fi
done
: "${E2E_DATABASE_URL:=postgresql+asyncpg://telerpg:telerpg@localhost:5432/telerpg_e2e}"
: "${TG_BOT_TOKEN:=123456789:AAFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE}"

# The stack started here is the e2e/test stack: no real Telegram calls, separate DB.
export APP_ENV=test
export DATABASE_URL="$E2E_DATABASE_URL"
export TG_BOT_TOKEN

mkdir -p logs docs/screens

if [ "${SKIP_DOCKER:-0}" != "1" ]; then
  docker compose up -d --wait postgres
fi

pnpm install --frozen-lockfile 2>/dev/null || pnpm install
(cd backend && uv sync)
pnpm exec playwright install chromium >/dev/null

(cd backend && uv run alembic upgrade head)

port_busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

start() { # name port command...
  local name=$1 port=$2
  shift 2
  if port_busy "$port"; then
    echo "$name already listening on :$port"
    return 0
  fi
  nohup "$@" >"logs/$name.log" 2>&1 </dev/null &
  echo $! >"logs/$name.pid"
  echo "started $name (pid $(cat "logs/$name.pid"))"
}

wait_for() { # url
  for _ in $(seq 1 60); do
    curl -fsS "$1" >/dev/null 2>&1 && return 0
    sleep 1
  done
  echo "timeout waiting for $1 (see logs/)" >&2
  return 1
}

start api 8000 bash -c 'cd backend && exec uv run uvicorn app.main:app --host 127.0.0.1 --port 8000'
start web 3000 bash -c 'cd frontend && exec pnpm exec vite'

wait_for http://localhost:8000/healthz
wait_for http://localhost:3000/
echo "init ok"
