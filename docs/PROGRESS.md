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

## 2026-11-21 S02 security review fix-up (round 2)
done: prod guards for fake TG_BOT_TOKEN and TG_WEBHOOK_SECRET (>=32); jwt/tg secrets and DATABASE_URL are SecretStr (repr test); engines pin READ COMMITTED (+DECISIONS #11); tests/db_guard.py refuses TRUNCATE/downgrade unless DB ends in _test (_e2e helper ready); CHECK quantity_remaining <= quantity_limit in model + 0001; 6 TODO lines. check-stage S02 passes (94 backend tests).
surprising: 0001 was edited in place; the sandbox refused `downgrade base` on the shared dev/e2e DBs, so the new CHECK was added to telerpg, telerpg_e2e, telerpg_test with an additive ALTER TABLE (alembic check clean). Fresh DBs get it from 0001.

## 2026-11-21 S02 security fix-up (round 3)
done: Settings has hide_input_in_errors=True and re-raises every ValidationError redacted (input -> "[hidden]", no __cause__/__context__), since hide_input only scrubs str(exc) while errors()/json() still held the raw env dict; tests assert no secret/DB password in str/repr/errors()/json for prod-guard and field failures; 4 TODO lines. check-stage S02 passes (99 backend tests).
surprising: validator messages never interpolated secrets; the leak was pydantic's model-level error input (whole env dict).

## 2026-11-21 S03 DONE (pending review)
done: validate_init_data (compare_digest, 24h + 5min future skew, dup keys, strict hash), HS256 JWT (alg/iss/aud pinned, exp via app clock), /auth/telegram (upsert on tg_user_id, uk/en locale, per-IP 30/min) + /auth/me, core/deps current_user (Bearer only, 30 writes/min/user -> 429), test-only /api/test/reset (404 unless APP_ENV=test, hidden from OpenAPI, _e2e/_test DB guard, JWT required, TRUNCATE CASCADE); frontend TelegramAdapter (Tma over WebApp or SDK bridge, Mock), in-memory API client, AuthProvider/AuthGate; e2e fixture signs real initData; check-stage S03 passes.
left: nothing in scope; TODO lines for playwright workers, proxy headers, i18n, character creation.
surprising: FastAPI 0.165 wraps included routers, so the route-walk test flattens _IncludedRouter.effective_route_contexts(); db_guard moved to app/core (tests re-export); App.tsx/App.test.tsx and schema.d.ts touched.

## 2026-11-21 S03 review fix-up (round 2) + S01 regression fix
done: S01 regression: e2e/smoke.spec.ts now signs in as user A via the telegram fixture and asserts "Placeholder home" + greeting (not the h1 shared with the no-Telegram screen); S01.png re-captured showing the real home. VITE_MOCK_INIT_DATA is read only when import.meta.env.DEV (inline, so prod builds drop it; verified a marker is absent from a prod bundle) + unit tests. playwright workers: 1. 4 TODO lines. check-stage S01 and S03 pass.
surprising: the DB-touching smoke spec raced auth.spec across parallel workers (reset truncated the other worker's user -> 401), so playwright.config.ts got workers: 1 (resolves that TODO line).

## 2026-11-21 S04 DONE (pending review)
done: router with all ARCHITECTURE s6 routes + placeholder pages in features/*/pages, AppLayout (locale from user, dark-first theme.css tokens + safe-area vars, deeplink redirect, Telegram BackButton, bottom nav hidden on onboarding/invite), namespaced i18n (en/uk common.json, glob-loaded, key-parity test), lib/deeplink, ui + game components with RTL tests, auth strings moved to i18n, e2e/shell.spec.ts + S04.png; S01/S03 checks still pass.
changed outside list: test-setup.ts (imports i18n, RTL cleanup), auth.test.tsx (start_param now null, since a start param redirects), smoke.spec.ts (assertion scoped to page-home).
left: ConfirmSheet/BottomSheet have no focus trap (TODO).

## 2026-11-21 S04 review fix-up round 2
done: BackButton first-entry detection now flags the deeplink replace redirect via location state (Back goes Home); tests for it (unit + e2e), server start_param path, safe-area CSS vars; DECISIONS 12 (namespaced i18n); TODO lines. e2e stub now keeps BackButton handlers so a test can press Back (e2e/fixtures/telegram.ts).

## 2026-11-21 S05 DONE (pending review)
done: progression/levels.py (closed form + exact nudge, project.md table tests); GET/PATCH /character (derived level/XP/attributes, active-wallet gold, extra fields ignored, IANA tz + en/uk validated) and POST /character/onboarding/complete (user row FOR UPDATE, character + 6 attributes + goals, 409 on repeat); goals and wishlist CRUD scoped to the caller (404 on foreign ids, ?user=companion only with an active partnership else 403, 50-item caps, offered/linked_reward_id not client-settable); frontend onboarding (character -> goals -> timezone), Home header, goals and wishlist pages, onboarding/profile i18n; e2e/onboarding.spec.ts + S05.png.
changed outside list: AppLayout (onboarding redirect with FIRST_ENTRY_STATE, Back hidden on onboarding), router, goals/wishlist schemas.py, common/validation.py, src/test/harness.tsx, schema.d.ts; S01/S03/S04 e2e now pre-onboard user A via onboardViaApi (S01 asserts the home character header instead of "Placeholder home"); old profile placeholder pages removed.
left: avatar upload, invite step in onboarding, deeplink resume after onboarding (TODO). surprising: Optional str with Field(max_length) on the union crashes on None in pydantic; jsdom Intl has no Europe/Kyiv.

## 2026-11-21 S06 DONE (pending review)
done: partnerships service + /partnership routes (invite: 32-byte token, sha256 stored, revokes previous, 7d, preview/accept by POST body; accept locks users by id then the invite, reactivates the old row + wallets + rewards on re-pair; leave with LEAVE ends partnership, cancels templates/open occurrences, hides rewards, notifies partner, one transaction), users/account.py + /account (export JSON; DELETE scrubs PII, ends partnership, deletes goals/wishlist/comments/files rows, keeps ledger, tg_user_id -> -id so old JWTs 401 and re-login starts fresh: DECISIONS 13/14); resolve_owner checks deleted_at; frontend InviteStep (onboarding step 4), invite accept page, Companion page, Settings (language, timezone, leave/delete via typed ConfirmSheet, export, privacy); partnership/settings i18n; e2e/pairing.spec.ts + S06.png. S01/S03/S04/S05 checks pass.
changed outside list: AppLayout (invite deeplink lost to the onboarding <Navigate> under StrictMode; fixed + regression test), router (InvitePage moved to features/partnership), onboarding i18n (steps.invite) + OnboardingPage, e2e/onboarding.spec.ts (clicks through the new invite step), test_goals_wishlist.py, schema.d.ts.
left: TODO lines (file bytes on deletion, prod guard for bot/app names, native Telegram share, companion activity/life balance).
