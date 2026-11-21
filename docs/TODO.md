# TODO
## Needs human
## Next agent
- backend/Dockerfile: pin the uv version (not :latest) and run the final image as a non-root user.
- init.sh: run `uv sync --frozen` (as CI does) so uv.lock drift fails loudly.
- scripts/test-smoke.sh: simulate API-down by killing uvicorn (per S01 test_step), not only a dead port.
- init.sh: PID liveness via `kill -0` can match a reused PID; also verify the process command line.
- backend/app/core/db.py (S01, NullPool engine used by /healthz) duplicates app/db/session.py; point /healthz at db.session and delete core/db.py.
- gold_transaction.(user_id, partnership_id) is not FK-tied to its wallet's (user_id, partnership_id); consider a composite FK to wallet(id, user_id, partnership_id).
- Purchase stage: namespace idempotency keys per user (e.g. `purchase:{user_id}:{key}`) and cap the Idempotency-Key header length to fit String(255).
- gold_transaction has no CHECK requiring quest_occurrence_id for quest_reward or purchase_id for purchase/refund.
- Schema does not enforce cross-partnership consistency (reward_purchase vs reward partnership, occurrence assignee vs template, wallet user membership); consider composite FKs.
- Account deletion must decide what happens to user.tg_user_id (NOT NULL unique) and to re-login.
- Add indexes on hot FK/filter columns (quest_occurrence(assignee_id,status), gold_transaction(wallet_id), notification(status,send_after), reward(partnership_id)) in the stages that write those queries.
- tests/integration/test_migrations.py round-trip (downgrade base) assumes pytest runs serially (no xdist).
- deploy: the prod image must set APP_ENV=prod (or require APP_ENV explicitly); today a deploy that forgets APP_ENV skips every prod guard.
- migrations/env.py: pin READ COMMITTED on the migration engine for consistency.
- anyone with a local DB from 603d5ff should rebuild it (downgrade base && upgrade head) to get ck_reward_quantity_remaining_within_limit.
- core/config.py: custom-error-type fallback drops ctx and downgrades a mixed error list entirely; cosmetic.
- playwright.config.ts: e2e specs share one DB and reset it per test; set `workers: 1` (or fullyParallel false + serial projects) before a second DB-touching spec file lands.
- prod: login rate limit keys on request.client.host; run uvicorn with --proxy-headers/--forwarded-allow-ips for Railway, or all users share one 30/min login bucket.
- features/auth strings (AuthGate, UserGreeting) are hard-coded English; move them to i18n in S04.
- /auth/telegram creates only the user row; /auth/me returns character=null until S05 onboarding creates the character (+6 attribute rows).
- InsecureKeyLengthWarning in pytest: DEV_JWT_SECRET (and .env.example JWT_SECRET) is 24 bytes; consider a >=32-byte dev default.
