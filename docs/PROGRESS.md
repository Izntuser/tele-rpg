# PROGRESS (append-only, 3-5 lines per session)
<!-- format: ## <YYYY-MM-DD> <stage id> <DONE|PARTIAL|BLOCKED>
done: ... / left: ... / broken or surprising: ... -->

## 2026-11-21 S01 DONE
done: pnpm workspace + uv backend (py3.13 pinned), compose Postgres 17, FastAPI /healthz + SPA fallback, Vite placeholder, init.sh/smoke.sh, CI, Dockerfile, gen:api, e2e @S01; check-stage S01 passes.
left: .env.example NOT committed (write blocked by permission settings; contents in scratchpad, see docs/TODO.md).
surprising: pnpm pinned via packageManager (latest pnpm rejects fresh lockfile entries in Docker); extra files app/core/{config,db}.py, frontend index.html/tsconfig/index.css/test-setup.ts, .gitignore additions.
