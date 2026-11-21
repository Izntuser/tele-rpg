#!/usr/bin/env bash
# Smoke test for the stack started by init.sh. Exits non-zero naming the failed check.
set -uo pipefail
cd "$(dirname "$0")/.."

fail() { echo "SMOKE FAIL: $1" >&2; exit 1; }

# Same env as init.sh so alembic checks the stack's database.
for f in .env .env.example; do
  if [ -f "$f" ]; then set -a; . "./$f"; set +a; break; fi
done
export DATABASE_URL="${E2E_DATABASE_URL:-postgresql+asyncpg://telerpg:telerpg@localhost:5432/telerpg_e2e}"
export APP_ENV=test

health=$(curl -fsS --max-time 5 http://localhost:8000/healthz) || fail "api /healthz unreachable"
echo "$health" | grep -q '"db":"ok"' || fail "api /healthz db not ok: $health"
echo "ok: healthz"

page=$(curl -fsS --max-time 5 http://localhost:3000/) || fail "frontend :3000 unreachable"
echo "$page" | grep -q 'id="root"' || fail "frontend html lacks root div"
echo "ok: frontend"

current=$(cd backend && uv run alembic current 2>/dev/null | awk '/^[0-9a-f]+/ {print $1}' | sort) \
  || fail "alembic current errored"
heads=$(cd backend && uv run alembic heads 2>/dev/null | awk '/^[0-9a-f]+/ {print $1}' | sort) \
  || fail "alembic heads errored"
[ "$current" = "$heads" ] || fail "alembic current ($current) != heads ($heads)"
echo "ok: alembic"
echo "smoke passed"
