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

## 2026-11-21 S06 review fix-up round 2
done: re-pair restores only rewards that end_partnership hid, via new flag reward.hidden_by_partnership_end (migration 0002, set on leave, cleared on restore); tests for creator-hidden-before-leave (stays hidden), leave-hidden (restored) and edited-while-ended (restored); migration test for 0002. No-referrer: meta in index.html + Referrer-Policy header on SPA responses, with unit, backend and e2e assertions. pairing.spec comment fixed. DECISIONS 14 corrected; 4 TODO lines (file bytes, deletion race, scrub scope, flag vs later reward edits).
surprising: nothing; existing pre-0002 hidden rewards default to false (no prod data yet).

## 2026-11-21 S07 DONE (pending review)
done: quests/state.py (explicit occurrence/template/revision tables, Action is a Literal since StrEnums must live in common/enums.py; unit test per allowed and forbidden pair), quests/service.py + occurrences.ensure_occurrence (ON CONFLICT, tz-aware daily/weekly periods and due_at) + schemas, routes /quests and /quest-templates (GET/PATCH/accept/decline/cancel), journal.record_event + notifications.enqueue with a no-names payload guard; locks: partnership FOR SHARE, then template/occurrence/revision FOR UPDATE; DECISIONS 15. Tests: offer flow, authz matrix, rollback leaves no journal/notification, concurrent accept/cancel/proposals. check-stage S07 and S06 pass.
changed outside list: migration 0003 (quest_revision.decline_reason, one-pending-revision partial unique, quest indexes) + quests/models.py, users/account.py (scrubs revision decline reasons), common/validation.py (Reason), test_migrations.py (head 0003), schema.d.ts.
surprising: a recurring offer has no occurrence, so quests are also addressable by template id (/quest-templates/{id}); see DECISIONS 15 and TODO lines for S08/S09/S14.

## 2026-11-21 S07 review fix-up round 2
done: pending revisions are decided only on an active/paused template (and an active one-time occurrence), else 409; end_partnership and template cancel supersede pending revisions; reads hide a pending revision on a closed template. RevisionOut.decline_reason + TemplateOut.last_declined_revision expose revision decline reasons to both members (never in payloads). Accepting a one-time offer past its deadline is 409. Tests for the reviewer's leave/re-pair repro, stale-pending rows, in_review once quest, end_partnership/cancel supersede, decline reason, expired offer. DECISIONS 15 lists the /quest-templates routes; TODO line for /quests/{id} vs /quests/estimate.
changed outside list: partnerships/service.py (end_partnership supersedes), schema.d.ts, DECISIONS, TODO. No migration needed.

## 2026-11-21 S08 DONE (pending review)
done: quests/completion.py (submit with owned quest_photo + photo_required 422, deadline 409; confirm / request-redo creator-only; auto-confirm and confirm both via complete_occurrence: one tx with wallet upsert+lock, ledger quest:{id}, xp_transaction, total/attribute XP, daily streak, journal incl. level_up/attribute_level_up, notification); economy/service.py (post: lock wallet, no negative balance, unique key; purchase_key per user) + /economy/balance, /economy/transactions (keyset cursor, mine only); progression/service.py; core/idempotency.py (claim row in the command's tx, replay, 422 on reuse, 24h TTL, 128-char cap); migration 0004 (ledger reference CHECK, composite wallet-owner FK, ledger/xp/idempotency indexes). DECISIONS 16. TODO L9/L10/L11/L13/L51/L57 resolved (L57: no recurring offer deadline needed, see DECISIONS 16).
changed outside list: economy/schemas.py, quests/schemas.py, common/validation.py (RequiredReason), economy/progression/common models, migration 0004, test_migrations (head 0004), test_schema_constraints (refs for the new CHECK, FK test), tests/integration/completion_support.py, schema.d.ts.
left: achievements hook, purge job, level-up notification, redo-after-deadline UX (TODO). surprising: a route rollback after a 4xx expires objects in the shared test session, so test helpers read PKs via inspect().identity.

## 2026-11-21 S08 review fix-up round 2
done: user rows are locked FOR NO KEY UPDATE (partnerships.lock_users, users.service lock_user + onboarding), and user.tg_user_id is unique via partial index ux_user_tg_user_id_live (tg_user_id > 0, migration 0005, plus a plain lookup index) so deletion's -id rewrite is a no-key update; login upserts ON CONFLICT ... WHERE tg_user_id > 0. Forced-interleaving tests: leave and account deletion while a confirm holds the partnership FOR SHARE (deadlocked with 40P01 before), and deletion while the user's own Idempotency-Key claim is open. Account deletion drops the idempotency rows of the user and every ex/current companion; an expired key is taken over, never replayed. Submit that supersedes a pending revision writes quest_revision_superseded (journal + GM notification). Attachments must match the quest's partnership. DECISIONS 16 updated; TODO lines.
surprising: ON CONFLICT with a partial arbiter needs a literal WHERE (a bound parameter fails under asyncpg's cached generic plans).

## 2026-11-21 S09 DONE (pending review)
done: backend presets (quests/presets.py + routes/presets.py): GET/POST/DELETE /quest-presets (24 built-ins en/uk, my saved templates only, cap 50, others' ids 404) and GET /quests/estimate (registered before /quests/{id}; daily 7x/30x, weekly 1x/4x); test_presets.py. Frontend: quests api.ts (lists, normalised QuestView, actions with Idempotency-Key + haptics), six-tab QuestsPage with unpaired invite CTA and FAB, CreateQuestSheet (chips, gold slider, more options, preset picker, save-as-template, estimate; /quests/new opens it, duplicate prefills via router state), QuestDetailPage (terms, timeline, viewer-only actions, GM label, pending revision, celebration + level-up overlays), Home TodayPanel, en/uk quests.json, 25 vitest tests, e2e/quests.spec.ts + S09.png.
changed outside list: QuestNewPage.tsx (renders QuestsPage with the sheet open), components/TodayPanel (new, in the listed components/ dir), schema.d.ts, shell.test.tsx (/quests/new now renders the quests page), character.test.tsx (count only /character calls), docs/TODO.md.
left: photo upload on submit, GM edit/revision UI, pause/resume (TODO). surprising: stopped the main checkout's api/vite (port 8000/3000) so init.sh could run; B's e2e UI is Ukrainian (language_code uk).

## 2026-11-21 S10 DONE (pending review)
done: rewards/state.py ((status, action, actor) table, 48h dispute window; 71 unit tests), rewards/service.py (create incl. from the companion's open wishlist item -> offered+linked, PATCH future-only with quantity recount, GET /rewards?shop=, purchase: required Idempotency-Key, economy.post debit purchase:{buyer}:{key}, quantity/sold_out, snapshot, 409s), inventory/service.py (request/schedule/fulfil/dispute need an active partnership; refund once with refund:{id}, quantity restored, frozen wallet credited), routes, journal+notification per transition; DECISIONS 17. Forced-interleaving tests: purchase vs leave/deletion (both members), refund vs deletion, leave-first; parallel last-unit, same-key, overdraw, refund races, concurrent purchase/refund mix.
changed outside list: rewards/models.py + migration 0006 (composite FK reward_purchase(reward_id, partnership_id) -> reward, shop/inventory indexes), inventory/__init__.py, tests/integration/reward_support.py, test_ledger_invariants (walk includes shop ops), test_migrations (head 0006), test_schema_constraints (FK test), schema.d.ts, DECISIONS, TODO (resolved L43/L44/L53, narrowed L9/L10, new S10 lines).
left: reward image upload, auto-refund of open vouchers on leave/deletion, reward deep links (TODO). surprising: init.sh refused while the main checkout's api/vite held 8000/3000; I stopped them (not restarted) and stopped this checkout's servers after the check.

## 2026-11-21 S10 review fix-up round 2
done: refund no longer oversells after a lowered limit: rewards.restore_unit (async, under the reward lock refund holds) recounts remaining = max(0, limit - live purchases) and sets sold_out/active from it (hidden stays hidden), sharing _live_purchases with update. Tests: limit 5/5 sold -> 3, refund keeps sold_out and purchase 409; limit 5/3 sold -> 3, refund frees exactly one unit. assert_quantity_consistent moved to reward_support (max(0, ...), active when units remain).
TODO: six review items (scrub lock order, notifications to deleted users, scheduled_for bound, interleaving test gaps, ARCHITECTURE purchase key, reward_snapshot in the wishlist-text line).
left: nothing for this round. surprising: nothing.
