# STAGES — tele-rpg

Generated from `docs/stages.json` (source of truth; never edit by hand). Status: `scripts/stages-status.sh`.

## Overview

| ID | Goal | Depends on | Cplx | Risk | UI |
|---|---|---|---|---|---|
| S01 | Skeleton only | — | medium | normal | yes |
| S02 | Shared contracts | S01 | high | sensitive | — |
| S03 | Telegram auth end to end | S02 | high | sensitive | yes |
| S04 | Frontend shell and design system | S03 | medium | normal | yes |
| S05 | Character and personal profile | S04 | medium | sensitive | yes |
| S06 | Partnership and account lifecycle | S05 | medium | sensitive | yes |
| S07 | Quest offer flow (backend) | S06 | high | normal | — |
| S08 | Quest completion and the economy (backend) | S07 | high | sensitive | — |
| S09 | Quest UI | S08 | medium | normal | yes |
| S10 | Reward shop and inventory (backend) | S08 | high | sensitive | — |
| S11 | Shop UI and the P0 acceptance test | S09, S10 | medium | normal | yes |
| S12 | Files and photo proof | S11 | medium | sensitive | yes |
| S13 | Recurring quests and the scheduler | S09 | medium | normal | yes |
| S14 | Telegram bot and notifications | S13 | high | normal | yes |
| S15 | Progress and insights plus the P1 acceptance test | S12, S14 | high | normal | yes |

**Parallelizable after deps:** S09 ∥ S10 · S10/S11 ∥ S13/S14 · S12 ∥ S13 · S12 ∥ S14 (no shared files).

**Shared conventions every stage relies on (set in S01–S04):**
- E2E runs against the stack from `./init.sh`: Vite :3000 (Playwright default baseURL), API :8000, `APP_ENV=test`, DB `telerpg_e2e`, fake bot token.
- Backend routes are autodiscovered from `backend/app/api/routes/`; i18n strings live in `frontend/src/i18n/{en,uk}/<feature>.json`.
- `frontend/src/lib/api/schema.d.ts` is generated (`pnpm gen:api`), never hand-edited, and not listed in stage files.
- Services take time from `app.core.clock`; outbound Telegram only via the notification dispatcher (FakeBot in tests).
- Dependencies are all installed in S01; later stages do not edit package.json / pyproject.toml.

## S01 — medium / normal / UI

Skeleton only: pnpm workspace + uv backend, Docker Compose Postgres 17, FastAPI with /healthz and SPA serving, Vite placeholder home, lint/test/e2e runners, CI, Dockerfile, idempotent init.sh and scripts/smoke.sh. All libraries from ARCHITECTURE §3 are installed now so later stages never edit dependency manifests.

**Depends on:** —

**Files:**
- `package.json`
- `pnpm-workspace.yaml`
- `docker-compose.yml`
- `scripts/db-init.sql`
- `.env.example`
- `init.sh`
- `scripts/smoke.sh`
- `.github/workflows/ci.yml`
- `backend/pyproject.toml`
- `backend/alembic.ini`
- `backend/migrations/env.py`
- `backend/app/main.py`
- `backend/app/export_openapi.py`
- `backend/tests/test_health.py`
- `backend/Dockerfile`
- `frontend/package.json`
- `frontend/vite.config.ts`
- `frontend/eslint.config.js`
- `frontend/src/main.tsx`
- `frontend/src/app/App.tsx`
- `frontend/src/app/App.test.tsx`
- `e2e/smoke.spec.ts`

**Definition of done:** `./init.sh && ./init.sh && scripts/smoke.sh && pnpm lint && pnpm test && docker build -q -f backend/Dockerfile . >/dev/null`

**Browser check:** `pnpm e2e --grep @S01`

**Test steps:**
1. Running ./init.sh twice in a row exits 0 both times without blocking: it leaves Postgres (5432), uvicorn (8000) and Vite (port 3000, strictPort, proxying /api and /healthz to 8000) running in the background with PID files and logs under logs/, and the second run starts no duplicate processes. It works when .env is absent by falling back to the .env.example defaults.
2. The stack started by init.sh runs with APP_ENV=test against DB telerpg_e2e and a fixed fake TG bot token from .env.example, and it makes no real Telegram calls. pytest uses telerpg_test. scripts/db-init.sql creates telerpg, telerpg_test and telerpg_e2e.
3. scripts/smoke.sh exits 0 when the stack is up: GET :8000/healthz returns 200 with db ok, GET :3000/ returns HTML containing the root div, and alembic current equals heads. After the uvicorn process is killed, it exits non-zero and names the failed check.
4. pnpm lint passes: eslint with no-alert as an error, tsc strict, ruff check and format --check, and mypy strict. pnpm test passes (one vitest test plus pytest test_health). pnpm gen:api generates frontend/src/lib/api/schema.d.ts.
5. pnpm e2e --grep @S01 opens / on the unchanged playwright.config.ts baseURL http://localhost:3000 and saves docs/screens/S01.png showing the placeholder home.
6. The CI workflow runs lint, test, build and e2e against a Postgres 17 service. backend/Dockerfile builds the frontend, copies dist into the image and serves it at / with an SPA fallback.

## S02 — high / sensitive

Shared contracts: backend core (settings, clock, async DB session, route autodiscovery), every SQLAlchemy model from ARCHITECTURE §4, a single initial Alembic migration, shared enums, and test fixtures/factories that all later stages build on.

**Depends on:** S01

**Files:**
- `backend/app/core/config.py`
- `backend/app/core/clock.py`
- `backend/app/db/base.py`
- `backend/app/db/session.py`
- `backend/app/api/router.py`
- `backend/app/modules/common/enums.py`
- `backend/app/modules/*/models.py`
- `backend/migrations/versions/0001_initial_schema.py`
- `backend/tests/conftest.py`
- `backend/tests/factories.py`
- `backend/tests/integration/test_schema_constraints.py`
- `backend/tests/integration/test_migrations.py`

**Definition of done:** `./init.sh && scripts/smoke.sh && (cd backend && uv run alembic check && uv run pytest -q tests/integration/test_schema_constraints.py tests/integration/test_migrations.py) && pnpm lint && pnpm test`

**Test steps:**
1. alembic upgrade head on an empty DB creates every table, Postgres enum, CHECK, unique and partial unique index listed in ARCHITECTURE §4. downgrade base followed by upgrade head round-trips cleanly, and alembic check reports no drift between the models and the migration.
2. Constraint tests show the DB rejects each of these: wallet.balance < 0, reward.quantity_remaining < 0, a duplicate gold_transaction.idempotency_key, a duplicate (template_id, scheduled_date) occurrence, a second active partnership for one user, a second pending invitation per creator, and a partnership with user_a_id >= user_b_id.
3. tests/conftest.py provides a per-test isolated async session, a fixture that yields independent connections for concurrency tests, and a fixture that freezes app.core.clock. tests/factories.py builds a user with a character and its 6 attribute rows, a partnership, a wallet, a quest template and occurrence, and a reward.
4. app/api/router.py includes every module in app/api/routes/ that exposes `router`, so a later stage adds a route file without editing a shared file. A test adds a dummy module and confirms it gets mounted.
5. Attribute, difficulty, recurrence and all status enums are defined once in app/modules/common/enums.py, and both the models and the Pydantic schemas import them from there.

## S03 — high / sensitive / UI

Telegram auth end to end: initData HMAC validation, JWT, /auth/telegram and /auth/me, current_user dependency, rate limiting, test-only DB reset, plus the frontend TelegramAdapter (Tma + Mock), the API client and the auth bootstrap, and a Playwright fixture that signs real initData.

**Depends on:** S02

**Files:**
- `backend/app/modules/auth/telegram.py`
- `backend/app/modules/auth/jwt.py`
- `backend/app/modules/auth/service.py`
- `backend/app/modules/auth/schemas.py`
- `backend/app/api/routes/auth.py`
- `backend/app/api/routes/test_support.py`
- `backend/app/core/deps.py`
- `backend/app/core/ratelimit.py`
- `backend/tests/unit/test_init_data.py`
- `backend/tests/unit/test_ratelimit.py`
- `backend/tests/integration/test_auth.py`
- `frontend/src/lib/telegram/*`
- `frontend/src/lib/api/client.ts`
- `frontend/src/features/auth/*`
- `frontend/src/app/providers.tsx`
- `frontend/src/main.tsx`
- `e2e/fixtures/telegram.ts`
- `e2e/auth.spec.ts`

**Definition of done:** `./init.sh && scripts/smoke.sh && (cd backend && uv run pytest -q tests/unit/test_init_data.py tests/unit/test_ratelimit.py tests/integration/test_auth.py) && pnpm -C frontend exec vitest --run src/lib/telegram src/lib/api && pnpm lint && pnpm test`

**Browser check:** `pnpm e2e --grep @S03`

**Test steps:**
1. POST /api/auth/telegram with initData signed as the Telegram docs describe returns {jwt, user, start_param} and upserts the user, with locale uk when language_code is uk and en otherwise. A tampered hash, a missing hash, or an auth_date older than 24h returns 401, and the hash is compared with hmac.compare_digest.
2. A parametrized test walks app.routes and checks that every /api route except /auth/telegram returns 401 with no JWT, an expired JWT, or a JWT with the wrong signature. Because the test walks the route table, routes added in later stages are covered automatically.
3. POST /api/test/reset truncates the DB only when APP_ENV=test and returns 404 for every other APP_ENV. Write routes return 429 after 30 requests per minute per user, tested with a frozen clock.
4. On the frontend, TelegramAdapter picks TmaAdapter inside Telegram and MockAdapter in a plain browser, and neither throws. The API client keeps the JWT in memory only (no localStorage, no cookies), sends it as a Bearer header, re-authenticates once on a 401, and sends an Idempotency-Key header when asked.
5. e2e/fixtures/telegram.ts injects a window.Telegram.WebApp stub with genuinely signed initData for users A and B, using the fake bot token of the init.sh stack, and calls /api/test/reset before each test. pnpm e2e --grep @S03 shows A's Telegram first name on the home page and saves docs/screens/S03.png.

## S04 — medium / normal / UI

Frontend shell and design system: the router with every ARCHITECTURE §6 route (placeholder pages), layout with bottom nav and Telegram BackButton, dark-first theme tokens, namespaced i18n EN/UK, the deeplink mapper, and the shared game components.

**Depends on:** S03

**Files:**
- `frontend/src/app/App.tsx`
- `frontend/src/app/router.tsx`
- `frontend/src/app/layout/AppLayout.tsx`
- `frontend/src/app/layout/BottomNav.tsx`
- `frontend/src/styles/theme.css`
- `frontend/src/components/ui/*`
- `frontend/src/components/game/*`
- `frontend/src/i18n/index.ts`
- `frontend/src/i18n/en/common.json`
- `frontend/src/i18n/uk/common.json`
- `frontend/src/i18n/i18n.test.ts`
- `frontend/src/lib/deeplink.ts`
- `frontend/src/lib/deeplink.test.ts`
- `frontend/src/features/*/pages/*Page.tsx`
- `e2e/shell.spec.ts`

**Definition of done:** `./init.sh && scripts/smoke.sh && pnpm -C frontend exec vitest --run src/i18n src/lib/deeplink src/components && pnpm lint && pnpm test`

**Browser check:** `pnpm e2e --grep @S04`

**Test steps:**
1. Every route in ARCHITECTURE §6 resolves to a page in frontend/src/features/<domain>/pages/ (placeholders are fine), and an unknown route redirects to Home. The bottom nav (Home, Quests, Shop, Stats, Companion) highlights the active tab.
2. The Telegram BackButton shows on non-root routes and navigates back. Safe-area insets come from CSS variables, and the theme is dark by default with AA-contrast tokens for both dark and light.
3. i18n loads namespaced catalogs from frontend/src/i18n/{en,uk}/<feature>.json, so later stages add their own files and never edit a shared catalog. A vitest checks that en and uk have identical key sets across all namespaces.
4. lib/deeplink.ts maps invite_<token> to /invite/<token>, q_<id> to /quests/<id>, r_<id> to /shop/inventory?item=<id>, and anything unknown to /. Each mapping has a unit test.
5. Each shared component has an RTL test: XpBar, GoldBadge, AttributeChip, DifficultyChip, StatusPill, BottomSheet, ConfirmSheet (with an optional typed-confirmation mode and no window.confirm), CelebrationOverlay (no animation under reduced motion), EmptyState and Avatar.
6. pnpm e2e --grep @S04 taps all 5 bottom-nav tabs as authenticated user A and saves docs/screens/S04.png.

## S05 — medium / sensitive / UI

Character and personal profile: character API with derived levels, onboarding (character, goals, timezone), development goals and wishlist CRUD with their pages, and a Home header showing level, XP and gold.

**Depends on:** S04

**Files:**
- `backend/app/modules/progression/levels.py`
- `backend/app/modules/users/service.py`
- `backend/app/modules/users/schemas.py`
- `backend/app/api/routes/character.py`
- `backend/app/modules/goals/service.py`
- `backend/app/api/routes/goals.py`
- `backend/app/modules/wishlist/service.py`
- `backend/app/api/routes/wishlist.py`
- `backend/tests/unit/test_levels.py`
- `backend/tests/integration/test_character.py`
- `backend/tests/integration/test_goals_wishlist.py`
- `frontend/src/features/onboarding/*`
- `frontend/src/features/character/*`
- `frontend/src/features/goals/*`
- `frontend/src/features/wishlist/*`
- `frontend/src/features/home/pages/HomePage.tsx`
- `frontend/src/i18n/{en,uk}/onboarding.json`
- `frontend/src/i18n/{en,uk}/profile.json`
- `e2e/onboarding.spec.ts`

**Definition of done:** `./init.sh && scripts/smoke.sh && (cd backend && uv run pytest -q tests/unit/test_levels.py tests/integration/test_character.py tests/integration/test_goals_wishlist.py) && pnpm lint && pnpm test`

**Browser check:** `pnpm e2e --grep @S05`

**Test steps:**
1. A user with onboarded_at null is redirected to /onboarding. The flow is a Character step (name required; nickname and bio optional; avatar defaults to the Telegram photo_url), then a Goals step (pick or type development goals), then a timezone pre-filled from the browser and editable. Finishing calls POST /character/onboarding/complete and lands on Home.
2. GET /api/character returns the level, XP into the current level, XP to the next level, the 6 attributes each with a level, and the gold of the active wallet (0 when there is none). levels.py matches the table in project.md §9, and a unit test checks L1=0, L2=100 and L3=250.
3. PATCH /character returns 422 for an invalid IANA timezone or a locale other than en/uk. Client-sent total_xp, level or gold fields are ignored.
4. Goals and wishlist CRUD work on my own items. Editing or deleting another user's item returns 404. GET ?user=companion returns the partner's items only while a partnership is active, and 403 otherwise.
5. pnpm e2e --grep @S05 completes onboarding as user A, adds a goal and a wishlist item, and saves docs/screens/S05.png of Home with avatar, name, level, XP bar and gold.

## S06 — medium / sensitive / UI

Partnership and account lifecycle: invite link, accept, leave with all side effects, re-pair reactivation, data export and account deletion, plus the onboarding invite step, the invite accept screen, the Companion page and the Settings page (language, timezone, danger zone).

**Depends on:** S05

**Files:**
- `backend/app/modules/partnerships/service.py`
- `backend/app/modules/partnerships/schemas.py`
- `backend/app/api/routes/partnership.py`
- `backend/app/modules/users/account.py`
- `backend/app/api/routes/account.py`
- `backend/tests/integration/test_partnership.py`
- `backend/tests/integration/test_account.py`
- `frontend/src/features/onboarding/InviteStep.tsx`
- `frontend/src/features/partnership/*`
- `frontend/src/features/companion/*`
- `frontend/src/features/settings/*`
- `frontend/src/i18n/{en,uk}/partnership.json`
- `frontend/src/i18n/{en,uk}/settings.json`
- `e2e/pairing.spec.ts`

**Definition of done:** `./init.sh && scripts/smoke.sh && (cd backend && uv run pytest -q tests/integration/test_partnership.py tests/integration/test_account.py) && pnpm lint && pnpm test`

**Browser check:** `pnpm e2e --grep @S06`

**Test steps:**
1. POST /partnership/invitations returns a link of the form https://t.me/<bot>/<app>?startapp=invite_<token>. Only the sha256 of the token is stored, and a new invite revokes the previous pending one. Accepting creates an active partnership and a wallet for each user. An expired (>7d), revoked, own or already-used token returns 4xx, as does accepting while already in an active partnership.
2. POST /partnership/leave rejects a wrong confirm_text. With the correct text, a single transaction ends the partnership, cancels templates and offered/active/in_review occurrences, hides rewards, freezes wallets and enqueues a notification row for the partner. The test seeds these rows with factories.
3. Re-pairing the same two users reactivates the old partnership row together with its wallets, rewards and history, and no new partnership row is created.
4. GET /account/export returns JSON with all of my data. DELETE /account with the correct confirm_text scrubs PII (display_name becomes 'Deleted user'; nickname, bio, goals, wishlist and submission comments are removed), ends the partnership, and keeps ledger rows so wallet.balance still equals the sum of the ledger.
5. /settings changes the language (UI re-renders in uk) and the timezone. Leave partnership and delete account sit behind a ConfirmSheet with typed confirmation, and the Companion page shows the partner's profile, attributes, goals and wishlist.
6. pnpm e2e --grep @S06 uses two browser contexts: A creates an invite, B opens with startapp=invite_<token> and accepts, and both see each other on Companion. The test saves docs/screens/S06.png.

## S07 — high / normal

Quest offer flow (backend): quest state machine, create, accept, decline, cancel, revisions, list and detail endpoints, the shared ensure_occurrence helper, and the journal/notification helpers that every later domain uses.

**Depends on:** S06

**Files:**
- `backend/app/modules/quests/state.py`
- `backend/app/modules/quests/service.py`
- `backend/app/modules/quests/occurrences.py`
- `backend/app/modules/quests/schemas.py`
- `backend/app/api/routes/quests.py`
- `backend/app/modules/journal/service.py`
- `backend/app/modules/notifications/service.py`
- `backend/tests/unit/test_quest_state.py`
- `backend/tests/integration/test_quest_offer_flow.py`
- `backend/tests/integration/test_quest_authz.py`

**Definition of done:** `./init.sh && scripts/smoke.sh && (cd backend && uv run pytest -q tests/unit/test_quest_state.py tests/integration/test_quest_offer_flow.py tests/integration/test_quest_authz.py) && pnpm lint && pnpm test`

**Test steps:**
1. POST /quests creates a template plus an offered occurrence (once) or a template plus revision 1 (recurring), assigned to the active partner. Gold outside 0–1000, a deadline on a recurring quest, or a deadline in the past returns 422. XP comes from difficulty via Settings.difficulty_xp, and any client-sent xp is ignored.
2. quests/state.py holds an explicit transition table, and a unit test covers every allowed and every forbidden transition.
3. The assignee can accept or decline (reason optional). Accepting a recurring offer activates the template and creates today's occurrence through quests/occurrences.ensure_occurrence, which is idempotent. Either party can cancel an offered or active occurrence.
4. While a quest is offered, PATCH edits it freely. While it is active, PATCH creates a pending revision that the assignee must accept. An accepted revision applies only to future occurrences, and existing terms_snapshot values stay unchanged.
5. GET /quests?role=player|gm&status=… returns the right occurrences for each tab. In the authz matrix, non-participants get 404 and wrong-role actions (creator accepting, assignee editing) get 403 or 409.
6. Each transition writes a journal_event (journal.service.record_event) and enqueues a notification (notifications.service.enqueue) in the same transaction, and a rolled-back transaction leaves neither row.

## S08 — high / sensitive

Quest completion and the economy (backend): submit, confirm, request-redo and auto-confirm in one transaction with the Gold ledger, XP and attribute progression, Idempotency-Key handling, the economy endpoints, and the concurrency and ledger-invariant tests.

**Depends on:** S07

**Files:**
- `backend/app/modules/quests/completion.py`
- `backend/app/modules/quests/service.py`
- `backend/app/api/routes/quests.py`
- `backend/app/modules/economy/service.py`
- `backend/app/modules/progression/service.py`
- `backend/app/core/idempotency.py`
- `backend/app/api/routes/economy.py`
- `backend/tests/unit/test_progression.py`
- `backend/tests/integration/test_quest_completion.py`
- `backend/tests/integration/test_idempotency.py`
- `backend/tests/integration/test_concurrency.py`
- `backend/tests/integration/test_ledger_invariants.py`

**Definition of done:** `./init.sh && scripts/smoke.sh && (cd backend && uv run pytest -q tests/unit/test_progression.py tests/integration/test_quest_completion.py tests/integration/test_idempotency.py tests/integration/test_concurrency.py tests/integration/test_ledger_invariants.py) && pnpm lint && pnpm test`

**Test steps:**
1. The assignee submits a comment and an optional attachment_id, which must be a file they own; a photo_required quest without an attachment returns 422. The creator confirms, and one transaction completes the occurrence, credits the wallet with gold_transaction key quest:{id}, writes an xp_transaction, and updates character total_xp and attribute XP. A level-up writes a journal event.
2. request-redo requires a reason and returns the occurrence to active with review_status redo. Only the creator can confirm or request a redo (403 otherwise), and the assignee cannot confirm their own quest.
3. An auto-confirm quest completes on submit through the same completion function. A test asserts that both paths call it.
4. test_concurrency.py fires 10 parallel confirms over separate connections and gets exactly one gold transaction and one XP transaction. Repeating /submit or /confirm with the same Idempotency-Key returns the stored response without applying the effect twice.
5. test_ledger_invariants.py runs a random sequence of operations and then checks wallet.balance == sum(gold_transaction.amount), total_xp == sum(xp_transaction.xp), and that no balance is negative.
6. GET /economy/balance returns the active wallet plus any frozen wallets. GET /economy/transactions is cursor-paginated and returns only my own ledger.

## S09 — medium / normal / UI

Quest UI: quest tabs, the create sheet with presets and an inflation estimate, quest detail with every lifecycle action, the Home today panel and the completion celebration, plus the backend for presets, saved templates and the estimate.

**Depends on:** S08

**Files:**
- `backend/app/modules/quests/presets.py`
- `backend/app/api/routes/presets.py`
- `backend/tests/integration/test_presets.py`
- `frontend/src/features/quests/api.ts`
- `frontend/src/features/quests/components/*`
- `frontend/src/features/quests/pages/QuestsPage.tsx`
- `frontend/src/features/quests/pages/QuestDetailPage.tsx`
- `frontend/src/features/quests/CreateQuestSheet.tsx`
- `frontend/src/features/home/pages/HomePage.tsx`
- `frontend/src/i18n/{en,uk}/quests.json`
- `e2e/quests.spec.ts`

**Definition of done:** `./init.sh && scripts/smoke.sh && (cd backend && uv run pytest -q tests/integration/test_presets.py) && pnpm -C frontend exec vitest --run src/features/quests && pnpm lint && pnpm test`

**Browser check:** `pnpm e2e --grep @S09`

**Test steps:**
1. The /quests tabs (My active, Offers, Recurring, Assigned by me, To confirm, Completed) show real data. An unpaired user sees the invite CTA instead.
2. The create sheet has a title, attribute chips, difficulty chips and a gold slider. 'More options' adds recurrence, deadline, confirmation and photo. It also offers a preset picker (about 24 localized built-ins plus my saved ones), save-as-template, duplicate quest, and the weekly/monthly gold estimate from GET /quests/estimate.
3. Quest detail shows the terms, a status timeline and only the actions valid for the viewer: accept/decline, submit, confirm/redo, cancel, accept pending revision. GM actions carry the 'You are the Game Master' label. Mutations send an Idempotency-Key and trigger haptics.
4. Confirming shows the CelebrationOverlay, plus a level-up overlay when the player levels up. Home lists today's quests, offers and pending confirmations. POST/DELETE /quest-presets act only on my own templates.
5. pnpm e2e --grep @S09: A creates a Normal / Physical / 50 Gold quest, B accepts and submits, A confirms, and B sees 50 Gold and 50 XP. The test saves docs/screens/S09.png.

## S10 — high / sensitive

Reward shop and inventory (backend): reward CRUD (including from a wishlist item), purchase with locks and idempotency, the voucher state machine (request, schedule, fulfil, dispute), and the refund rules.

**Depends on:** S08

**Files:**
- `backend/app/modules/rewards/state.py`
- `backend/app/modules/rewards/service.py`
- `backend/app/modules/rewards/schemas.py`
- `backend/app/modules/inventory/service.py`
- `backend/app/api/routes/rewards.py`
- `backend/app/api/routes/inventory.py`
- `backend/tests/unit/test_reward_state.py`
- `backend/tests/integration/test_rewards.py`
- `backend/tests/integration/test_inventory.py`
- `backend/tests/integration/test_purchase_concurrency.py`

**Definition of done:** `./init.sh && scripts/smoke.sh && (cd backend && uv run pytest -q tests/unit/test_reward_state.py tests/integration/test_rewards.py tests/integration/test_inventory.py tests/integration/test_purchase_concurrency.py tests/integration/test_ledger_invariants.py) && pnpm lint && pnpm test`

**Test steps:**
1. A creates rewards in their own shop with price > 0 and optional quantity_limit, cooldown_days and availability. A can also create one from B's wishlist_item_id, which must belong to the active partner; that item then becomes offered and linked. PATCH affects only future purchases, and existing snapshots stay unchanged.
2. B purchases with an Idempotency-Key: the wallet is debited with key purchase:{key}, quantity is decremented (sold_out at 0), and the reward is snapshotted. Insufficient gold, sold out, hidden, within cooldown, ended partnership (frozen wallet) and buyer = creator each return 409.
3. rewards/state.py has a unit test for every allowed and forbidden transition. The flow is purchased → requested (buyer) → scheduled (provider, scheduled_for) → fulfilled (provider). The buyer can dispute only within 48h of fulfilled_at, which returns the voucher to requested.
4. The provider can refund before fulfilled, and the buyer only while purchased. A refund writes exactly one credit with key refund:{purchase_id} and restores quantity, and a refund to a frozen wallet still credits it.
5. Parallel purchases of the last unit produce exactly one sale, and the ledger invariant holds after a mix of purchases and refunds. Every transition writes a journal event and enqueues a notification.

## S11 — medium / normal / UI

Shop UI and the P0 acceptance test: companion shop, my inventory and manage-my-shop screens, with e2e/core-loop.spec.ts proving the full two-user core loop.

**Depends on:** S09, S10

**Files:**
- `frontend/src/features/shop/*`
- `frontend/src/features/inventory/*`
- `frontend/src/i18n/{en,uk}/shop.json`
- `e2e/shop.spec.ts`
- `e2e/core-loop.spec.ts`

**Definition of done:** `./init.sh && scripts/smoke.sh && pnpm -C frontend exec vitest --run src/features/shop src/features/inventory && pnpm lint && pnpm test && pnpm e2e --grep @P0`

**Browser check:** `pnpm e2e --grep @S11`

**Test steps:**
1. /shop lists the companion's active rewards with price, remaining quantity, cooldown state and my balance. Purchase goes through a ConfirmSheet. When gold is insufficient, the button is disabled with an explanation.
2. /shop/inventory groups my vouchers by status and offers request, dispute (within 48h) and refund only when allowed.
3. /shop/manage supports CRUD on my rewards, creating a reward from the companion's wishlist, and a requests queue with schedule (date and note), fulfil and refund.
4. A purchase shows the CelebrationOverlay, and the balance updates without a reload through query invalidation.
5. e2e/core-loop.spec.ts, tagged @P0 @S11, implements ARCHITECTURE §10 steps 1–8 with two browser contexts and ends with B's inventory showing Fulfilled. pnpm e2e --grep @S11 saves docs/screens/S11.png.

## S12 — medium / sensitive / UI

Files and photo proof: StorageBackend with LocalStorage, an authorized upload/stream API with EXIF stripping and re-encoding, avatar upload, reward image, and photo submit on quests.

**Depends on:** S11

**Files:**
- `backend/app/storage/base.py`
- `backend/app/storage/local.py`
- `backend/app/storage/images.py`
- `backend/app/api/routes/files.py`
- `backend/app/api/routes/character.py`
- `backend/app/api/routes/rewards.py`
- `backend/tests/integration/test_files.py`
- `frontend/src/features/files/*`
- `frontend/src/features/quests/components/SubmitForm.tsx`
- `frontend/src/features/character/AvatarPicker.tsx`
- `frontend/src/features/shop/RewardImageField.tsx`
- `e2e/photo.spec.ts`

**Definition of done:** `./init.sh && scripts/smoke.sh && (cd backend && uv run pytest -q tests/integration/test_files.py) && pnpm lint && pnpm test`

**Browser check:** `pnpm e2e --grep @S12`

**Test steps:**
1. POST /api/files (multipart, ≤10MB, jpeg/png/webp/heic) re-encodes the image and strips EXIF; a test checks that a GPS tag is gone after upload. Other MIME types return 415, oversize files return 413, and more than 5 uploads per minute returns 429.
2. GET /api/files/{id} streams the file only to its owner or the active partner. Everyone else gets 404, including the former partner once the partnership ends.
3. StorageBackend (put/open/delete/exists) has a LocalStorage implementation under STORAGE_DIR, and tests use a tmp dir. Account deletion removes the user's files from storage.
4. Avatar upload (onboarding and character), reward image (manage shop) and quest photo proof (submit form, compressed client-side with browser-image-compression) all work. A photo_required quest cannot be submitted without a photo.
5. pnpm e2e --grep @S12: B submits a photo-required quest with a fixture image, and A sees the photo on the quest detail page. The test saves docs/screens/S12.png.

## S13 — medium / normal / UI

Recurring quests and the scheduler: an advisory-locked APScheduler runner, timezone-aware daily/weekly occurrence generation, expiry, daily streaks, template pause/resume, and the Recurring tab controls.

**Depends on:** S09

**Files:**
- `backend/app/jobs/runner.py`
- `backend/app/jobs/generate_occurrences.py`
- `backend/app/jobs/expire_occurrences.py`
- `backend/app/modules/quests/streaks.py`
- `backend/app/modules/quests/completion.py`
- `backend/app/api/routes/quest_templates.py`
- `backend/tests/unit/test_recurrence_dates.py`
- `backend/tests/integration/test_jobs.py`
- `backend/tests/integration/test_pause_resume.py`
- `frontend/src/features/quests/templatesApi.ts`
- `frontend/src/features/quests/components/RecurringTab.tsx`
- `e2e/recurring.spec.ts`

**Definition of done:** `./init.sh && scripts/smoke.sh && (cd backend && uv run pytest -q tests/unit/test_recurrence_dates.py tests/integration/test_jobs.py tests/integration/test_pause_resume.py) && pnpm lint && pnpm test`

**Browser check:** `pnpm e2e --grep @S13`

**Test steps:**
1. python -m app.jobs.runner starts jobs only after pg_try_advisory_lock succeeds. A second runner started in parallel runs no jobs, and a test proves it.
2. generate_occurrences creates today's occurrence for daily templates and this ISO week's (Monday) for weekly ones, in the assignee's timezone. It never backfills, skips paused and cancelled templates, and produces no duplicates when run repeatedly or after a restart.
3. Unit tests with a frozen clock cover the day boundary in Europe/Kyiv vs UTC, both DST transitions, week start, and users in UTC+14 and UTC−12.
4. expire_occurrences moves active occurrences past due_at to expired and never touches in_review. The daily streak's current and best values update on confirm, and a missed day resets current.
5. Pause and resume (creator only) stop and restart generation. pnpm e2e --grep @S13 pauses and resumes a daily quest in the Recurring tab, which shows the streak, and saves docs/screens/S13.png.

## S14 — high / normal / UI

Telegram bot and notifications: aiogram webhook and polling, /start with deep-link payloads, an outbox dispatcher with preferences, quiet hours and can_message, reminder and daily-summary jobs, the inbox API and UI, the header bell and the notification settings section.

**Depends on:** S13

**Files:**
- `backend/app/bot/dispatcher.py`
- `backend/app/bot/handlers/start.py`
- `backend/app/bot/polling.py`
- `backend/app/bot/fake.py`
- `backend/app/bot/i18n/{en,uk}.json`
- `backend/app/api/routes/tg_webhook.py`
- `backend/app/api/routes/notifications.py`
- `backend/app/modules/notifications/dispatcher.py`
- `backend/app/modules/notifications/service.py`
- `backend/app/jobs/notification_jobs.py`
- `backend/app/jobs/runner.py`
- `backend/tests/unit/test_quiet_hours.py`
- `backend/tests/integration/test_outbox.py`
- `backend/tests/integration/test_bot.py`
- `frontend/src/features/notifications/*`
- `frontend/src/features/settings/NotificationSettings.tsx`
- `frontend/src/app/layout/AppLayout.tsx`
- `frontend/src/i18n/{en,uk}/notifications.json`
- `e2e/notifications.spec.ts`

**Definition of done:** `./init.sh && scripts/smoke.sh && (cd backend && uv run pytest -q tests/unit/test_quiet_hours.py tests/integration/test_outbox.py tests/integration/test_bot.py) && pnpm lint && pnpm test`

**Browser check:** `pnpm e2e --grep @S14`

**Test steps:**
1. POST /tg/webhook/{TG_WEBHOOK_SECRET} accepts updates, and a wrong secret returns 404. /start replies with a welcome and a WebApp button, and the payloads invite_<token> and q_<id> are passed through to startapp. Tests feed aiogram updates and assert on FakeBot.
2. The dispatcher sends pending notifications after commit (through an API post-commit hook) and again in a 30 s scheduler sweep. It skips a disabled category or can_message=false, defers sends during quiet hours via send_after, and retries failures up to an attempts cap. Each message carries an inline button to https://t.me/<bot>/<app>?startapp=q_<id> (or r_/inv_).
3. Deadline reminders and the 09:00-local daily summary are deduplicated per day and skipped during quiet hours. No test makes a real network call: FakeBot records every send.
4. The inbox API supports a cursor list, read, read-all, PATCH preferences and write-access. The UI has the /notifications page, an unread bell in the header, and a notification section in Settings with categories, quiet hours, daily summary and enabling bot messages via requestWriteAccess.
5. pnpm e2e --grep @S14: after A offers a quest, B sees an inbox item, taps it, and lands on the quest detail. The test saves docs/screens/S14.png.

## S15 — high / normal / UI

Progress and insights plus the P1 acceptance test: Adventure Journal, stats, Life Balance radar with targets and suggestions, code-defined achievements, and e2e/p1-features.spec.ts.

**Depends on:** S12, S14

**Files:**
- `backend/app/modules/journal/service.py`
- `backend/app/api/routes/journal.py`
- `backend/app/modules/stats/service.py`
- `backend/app/modules/stats/life_balance.py`
- `backend/app/api/routes/stats.py`
- `backend/app/modules/achievements/definitions.py`
- `backend/app/modules/achievements/service.py`
- `backend/app/api/routes/achievements.py`
- `backend/tests/unit/test_life_balance.py`
- `backend/tests/integration/test_stats_journal.py`
- `backend/tests/integration/test_achievements.py`
- `frontend/src/features/stats/*`
- `frontend/src/features/journal/*`
- `frontend/src/features/companion/LifeBalanceSection.tsx`
- `frontend/src/i18n/{en,uk}/stats.json`
- `e2e/stats.spec.ts`
- `e2e/core-loop.spec.ts`
- `e2e/p1-features.spec.ts`

**Definition of done:** `./init.sh && scripts/smoke.sh && (cd backend && uv run pytest -q tests/unit/test_life_balance.py tests/integration/test_stats_journal.py tests/integration/test_achievements.py) && pnpm lint && pnpm test && pnpm e2e --grep '@P0|@P1'`

**Browser check:** `pnpm e2e --grep @S15`

**Test steps:**
1. GET /journal?scope=me|shared is cursor-paginated, and private events never appear in the companion's shared scope. GET /stats?period=7d|30d|all returns counts, xp/day, quests/day and gold earned/spent, and the Stats and Journal pages render them.
2. GET /stats/life-balance?period=7d|30d&user=me|companion returns per-attribute scores against targets (formula from project.md §11) and rule-based suggestions. PUT targets changes only my own. The radar shows on Stats and on the Companion page.
3. About 14 achievements in achievements/definitions.py are evaluated from journal.record_event, and each unlocks once (PK). An unlock shows a toast, and GET /achievements returns definitions plus unlocks.
4. e2e/core-loop.spec.ts is extended with ARCHITECTURE §10 step 9: the journal shows every event.
5. e2e/p1-features.spec.ts, tagged @P1 @S15, covers life balance, journal, an achievement toast, photo submit, goals, wishlist→reward, the notification inbox, and switching the language to uk. pnpm e2e --grep @S15 saves docs/screens/S15.png of Stats.

