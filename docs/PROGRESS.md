# PROGRESS (append-only, 3-5 lines per session)
<!-- format: ## <YYYY-MM-DD> <stage id> <DONE|PARTIAL|BLOCKED>
done: ... / left: ... / broken or surprising: ... -->

## 2026-11-21 S01 DONE
done: pnpm workspace + uv backend (py3.13 pinned), compose Postgres 17, FastAPI /healthz + SPA fallback, Vite placeholder, init.sh/smoke.sh, CI, Dockerfile, gen:api, e2e @S01; check-stage S01 passes.
left: .env.example NOT committed (write blocked by permission settings; contents in scratchpad, see docs/TODO.md).
surprising: pnpm pinned via packageManager (latest pnpm rejects fresh lockfile entries in Docker); extra files app/core/{config,db}.py, frontend index.html/tsconfig/index.css/test-setup.ts, .gitignore additions.

## 2026-11-21 S01 review fix-up (round 2)
done: compose name tele-rpg; init.sh uses PID files, cleans stale ones, fails on foreign port holder, frozen-lockfile no fallback; CI playwright --with-deps; scripts/test-smoke.sh (in pnpm test) proves smoke.sh fails naming api /healthz via API_URL override; TODOs added.
left: .env.example pending (human).

## 2026-11-21 S02 DONE (pending review)
done: Settings (+prod JWT_SECRET guard, difficulty_xp), core/clock (freeze/advance), db/base (naming convention, pg_enum, load_models), db/session, /api router autodiscovery wired in main.py, all 24 §4 tables in app/modules/*/models.py, enums in common/enums.py, hand-tuned 0001 migration (explicit enum types, deferred cyclic FKs, partnership one-active trigger), conftest fixtures + factories, 74 backend tests; check-stage S02 passes.
left: nothing in scope; TODOs added (core/db.py consolidation, gold_transaction composite FK).
surprising: partial unique indexes cannot stop a user being user_a in one active partnership and user_b in another, so a trigger with per-user advisory locks covers it; init.sh now also migrates the dev DB because the dod's `alembic check` reads the default DATABASE_URL; FastAPI 0.165 wraps included routers (_IncludedRouter), so tests check openapi paths.
