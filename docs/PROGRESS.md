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
