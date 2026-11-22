# ARCHITECTURE — tele-rpg (Modern Life RPG)

Source brief: `project.md`. Interview decisions are folded in below. Where the two conflict, this file wins.

## 1. Goal and users

- A Telegram Mini App where two paired companions act as Game Masters for each other. Each one creates quests for the other, confirms completion and runs a real-life reward shop.
- First users: the owner and one partner (dogfooding). It is a personal project with no monetization.
- Done means: P0 + P1 (brief §27) deployed on Railway and usable from real Telegram (iOS, Android, Desktop).
- UI languages: English and Ukrainian.

## 2. Scope

### In

- Telegram initData auth, character profile, onboarding (name, avatar, goals, timezone), invite link pairing, leaving a partnership, re-pair reactivation.
- Quests: one-time / daily / weekly. "Open" is a UI label for a one-time quest with no deadline.
  - Lifecycle: offer → accept / decline → submit (comment, photo) → confirm / request redo. Auto-confirm is available.
  - Either party can cancel. Edits after acceptance become a pending revision that the player must accept.
  - Recurring templates can be paused or resumed. Each daily quest has a streak counter (display only).
- Progression: general XP and levels, 6 attributes with attribute XP and levels, a Gold ledger per partnership wallet.
- Reward shop: the companion creates rewards with price, quantity limit, cooldown and availability; the player purchases them.
  - Inventory: Purchased → Requested → Scheduled → Fulfilled.
  - Dispute within 48h of fulfilment. Refunds follow the rules in §4.
- Quest templates: a built-in preset library, user-saved templates, and "duplicate quest".
- Life Balance radar (7 and 30 days), owner-editable targets, rule-based quest suggestions.
- Stats, Adventure Journal, about 14 code-defined achievements.
- Personal development goals ("I Want to Improve") and a wishlist that can be turned into a shop reward.
- Telegram bot: /start, Open App button, notifications with deep links, daily summary, deadline reminders, per-category preferences, quiet hours. In-app notification inbox.
- Photo proof and avatar uploads (local volume behind `StorageBackend`).
- i18n EN/UK, dark-first theme, Motion animations, confetti, Telegram haptics.
- GDPR-lite: privacy note, JSON data export, account deletion.

### Out

- Payments, Telegram Stars, ads, premium tier.
- Character classes, skill trees, shared quests, boss battles, questlines, mystery quests, random events, quest negotiation, shared currency, Game Master progression.
- More than one active companion per user; groups and guilds.
- AI assistance.
- Admin UI. Operations are done with SQL and the CLI scripts in `backend/app/cli.py`.
- Redis, S3 object storage, a staging environment, horizontal scaling.
- Weekly progress counters (x/N). A weekly quest is a single submit.
- Native `alert()`, `confirm()` and `prompt()`.

## 3. Architecture

A modular monolith with three backend processes from one codebase and one Postgres database.

```
Telegram client ──(opens)──► Mini App SPA (React, served by FastAPI at /)
        │                         │  REST /api/*  (Bearer JWT)
        │                         ▼
        │                 FastAPI "api" process ──► PostgreSQL 17
        │  webhook POST           │   ▲                 ▲
        └──/tg/webhook/{secret}──►│   │ domain services │
                                  │ aiogram dispatcher  │
                                  ▼                     │
                         Telegram Bot API ◄── "scheduler" process (APScheduler)
                                                 recurring generation, expiry,
                                                 reminders, notification outbox
```

**Processes**

- `api`: `uvicorn app.main:app`. Runs FastAPI, mounts the aiogram webhook route `/tg/webhook/{TG_WEBHOOK_SECRET}`, and serves the built SPA from `frontend/dist` with an SPA fallback.
- `scheduler`: `python -m app.jobs.runner`. A single APScheduler `AsyncIOScheduler`.
- `bot-dev` (local only): `python -m app.bot.polling`. Uses aiogram long polling instead of the webhook.

**Communication**

- SPA → API over same-origin REST with JSON. Auth is `Authorization: Bearer <JWT>`.
- Telegram → API through the bot webhook.
- API and scheduler → Telegram through the aiogram `Bot` client, called only from the notification outbox dispatcher.
- There is no direct process-to-process communication; Postgres is the only shared state.

**Layering (backend)**

- `app/api/routes/*.py` and `app/bot/handlers/*.py` are thin. They parse input and call services in `app/modules/<domain>/service.py`.
- Services own the transactions and the business rules.
- Models live in `app/modules/<domain>/models.py` and Pydantic schemas in `schemas.py`.

**Notifications** use a transactional outbox:

1. A service inserts a `notification` row in the same transaction as the state change.
2. `app/modules/notifications/dispatcher.py` sends pending rows after commit. The API calls it from a post-commit hook, and the scheduler sweeps every 30 s as a fallback.
3. The dispatcher applies preferences, quiet hours and `can_message`.

**Concurrency and idempotency**

- `SELECT … FOR UPDATE` on the quest occurrence, wallet and reward rows.
- Unique constraints on `gold_transaction.idempotency_key` and on `(template_id, scheduled_date)` for occurrences.
- Writes to `/confirm`, `/submit` and `/purchase` accept an `Idempotency-Key` header, stored in the `idempotency_key` table with a 24h TTL.

**Why this over the obvious alternatives**

- **Bot as a separate service (as in the brief)?** At ≤100 users a second deploy unit adds operational cost and nothing else. The webhook inside FastAPI shares services and a database pool.
- **Separate static frontend host (Vercel / Railway static)?** Same-origin serving removes CORS and the cookie/webview issues, and it is one fewer service.
- **Redis for locks and rate limits?** At a single API instance, Postgres row locks and advisory locks plus in-process rate limiting are enough. Redis can be added later behind `app/core/ratelimit.py`.
- **APScheduler inside the API process?** Rejected so that deploys or a second API replica can never double-run jobs. Jobs are idempotent anyway.
- **S3/R2 for files?** The client chose a Railway volume. `app/storage/base.py::StorageBackend` (`put`, `open`, `delete`, `exists`) has one implementation, `LocalStorage`. An `S3Storage` can be swapped in later without route changes.

**Frontend structure** (`frontend/src`)

- `app/`: router, providers, layout, bottom nav.
- `lib/telegram/`: `TelegramAdapter` interface with `getInitData`, `haptic`, `backButton`, `mainButton`, `theme`, `viewport`, `requestWriteAccess`, `startParam` and `closingConfirmation`. Implementations: `TmaAdapter` on `@telegram-apps/sdk-react`, and `MockAdapter` for dev and tests.
- `lib/api/`: fetch client with JWT and Idempotency-Key, plus `schema.d.ts` generated by `openapi-typescript`.
- `features/<domain>/`: TanStack Query hooks, components and pages.
- `components/ui/`: shadcn components.
- `i18n/en.json` and `i18n/uk.json`.
- `stores/`: Zustand, UI-only state such as the celebration queue and sheet state.

**Libraries**

- Frontend: React 19, TypeScript strict, Vite, Tailwind v4, shadcn/ui, `motion`, `@tanstack/react-query`, `zustand`, `react-router` v7, `react-hook-form`, `zod`, `recharts`, `lucide-react`, `@telegram-apps/sdk-react`, `react-i18next`, `canvas-confetti`, `browser-image-compression`.
- Backend: FastAPI, Pydantic v2, `pydantic-settings`, SQLAlchemy 2 async with `asyncpg`, Alembic, aiogram 3, APScheduler 3.x, `pyjwt`, `pillow` (EXIF strip and re-encode), `pillow-heif`, `structlog`, `sentry-sdk`.

**Initial repo layout:** brief §21, plus:

- root `package.json` (scripts and Playwright)
- `e2e/`
- `scripts/`
- `backend/pyproject.toml` and `backend/uv.lock`
- `frontend/package.json`

## 4. Data model

PostgreSQL 17. All timestamps are `timestamptz` in UTC. IDs are `bigint identity`. Telegram IDs are `bigint`. Enums are Postgres enums managed by Alembic.

| Table | Key fields | Relations / constraints |
|---|---|---|
| `user` | id, tg_user_id (unique), tg_username, display_name, avatar_url, avatar_file_id, locale (`en`/`uk`), timezone (IANA), can_message bool, notification_prefs jsonb (categories, quiet_hours_start/end, daily_summary), onboarded_at, deleted_at, created_at, updated_at | 1:1 character |
| `character` | id, user_id (unique), name, nickname, bio, total_xp int ≥0, created_at | level derived from total_xp |
| `character_attribute` | character_id, attribute (`physical, intellectual, discipline, social, creativity, wellbeing`), xp int ≥0 | PK(character_id, attribute); 6 rows created with the character |
| `partnership` | id, user_a_id, user_b_id (a < b), status (`active, ended`), created_at, accepted_at, ended_at, ended_by | unique(user_a_id, user_b_id); partial unique index per user over active partnerships, so each user has at most one active |
| `partnership_invitation` | id, creator_id, token_hash (sha256, unique), status (`pending, accepted, revoked, expired`), expires_at (+7d), accepted_by, accepted_at | partial unique: one pending per creator |
| `wallet` | id, user_id, partnership_id, balance int CHECK ≥0 | unique(user_id, partnership_id). Cached balance; the ledger is truth |
| `gold_transaction` | id, wallet_id, user_id, partnership_id, type (`quest_reward, reward_purchase, reward_refund, adjustment`), amount (signed), quest_occurrence_id?, purchase_id?, idempotency_key (unique), created_at | invariant: wallet.balance = sum(amount) |
| `xp_transaction` | id, user_id, quest_occurrence_id (unique), xp, attribute, attribute_xp, created_at | one per completed occurrence |
| `quest_template` | id, partnership_id, creator_id, assignee_id (≠ creator), title, description, attribute, difficulty (`easy, normal, hard, epic`), gold int 0–1000, recurrence (`once, daily, weekly`), deadline_at? (once only), confirmation (`manual, auto`), photo_required, status (`offered, active, paused, declined, cancelled, completed`), current_revision_id, created_at | 1:N occurrence, 1:N revision |
| `quest_revision` | id, template_id, version, terms jsonb (title, description, attribute, difficulty, gold, xp, deadline, confirmation, photo_required), status (`pending, accepted, declined, superseded`), proposed_by, created_at, decided_at | the accepted revision is what occurrences snapshot |
| `quest_occurrence` | id, template_id, assignee_id, status (`offered, active, in_review, completed, declined, expired, cancelled`), scheduled_date (local date; week-start Monday for weekly), due_at, terms_snapshot jsonb (incl. xp, gold), accepted_at, submitted_at, completed_at, cancelled_by, decline_reason | unique(template_id, scheduled_date) |
| `quest_submission` | id, occurrence_id, submitted_by, comment, attachment_id?, created_at, review_status (`pending, approved, redo`), review_comment, reviewed_at | redo requires review_comment |
| `quest_streak` | template_id (PK), current, best, last_completed_date | daily templates only |
| `saved_quest_template` | id, owner_id, title, description, attribute, difficulty, gold, recurrence, confirmation, photo_required | user-saved presets. Built-in presets are static data in `app/modules/quests/presets.py` |
| `reward` | id, partnership_id, creator_id, title, description, price int >0, image_file_id?, quantity_limit?, quantity_remaining?, cooldown_days?, status (`active, hidden, sold_out`), source_wishlist_item_id?, created_at, updated_at | `CHECK quantity_remaining ≥ 0` |
| `reward_purchase` | id, reward_id, partnership_id, buyer_id, provider_id, price_paid, reward_snapshot jsonb, status (`purchased, requested, scheduled, fulfilled, cancelled, refunded`), scheduled_for?, schedule_note, purchased_at, requested_at, scheduled_at, fulfilled_at, disputed_at, refunded_at, refunded_by, idempotency_key (unique) | acts as the inventory item |
| `journal_event` | id, user_id, partnership_id?, type, visibility (`private, shared`), entity_type, entity_id, payload jsonb (denormalized titles and amounts so history survives edits), created_at | index (partnership_id, created_at) |
| `achievement_unlock` | user_id, code, unlocked_at | PK(user_id, code). Definitions live in `app/modules/achievements/definitions.py` |
| `development_goal` | id, user_id, title, description, attribute?, status (`active, archived`), created_at | |
| `wishlist_item` | id, user_id, title, description, status (`open, offered, archived`), linked_reward_id? | |
| `life_balance_target` | user_id, attribute, weekly_xp_target (default 100) | PK(user_id, attribute) |
| `notification` | id, recipient_id, type, category (`quests, reviews, rewards, reminders, summary`), entity_type, entity_id, payload jsonb, deep_link, status (`pending, sent, skipped, failed`), attempts, read_at, send_after, created_at, delivered_at | outbox + inbox; dedupe unique(recipient_id, type, entity_id, send_after::date) for reminders and summaries |
| `file` | id, owner_id, partnership_id?, kind (`avatar, quest_photo, reward_image`), storage_key, mime, size, created_at | served via `/api/files/{id}` with an authorization check |
| `idempotency_key` | key, user_id, endpoint, response jsonb, created_at | PK(user_id, key); purged after 24h |

**Rules encoded in services**

- **Progression** (`app/modules/progression/levels.py`):
  - XP to reach level L = `100(L−1) + 25(L−1)(L−2)`.
  - `level_for_xp(xp)` is computed by closed form or loop. The same function is used for attributes.
  - XP per difficulty comes from `Settings.difficulty_xp` = {easy 20, normal 50, hard 100, epic 250}.
- **Confirm transaction** (`QuestService.confirm`), all in one transaction:
  1. Lock the occurrence and check status `in_review`.
  2. Check the reviewer is the creator.
  3. Set the occurrence to `completed`.
  4. Upsert the wallet and lock it, then add Gold.
  5. Insert `gold_transaction` with key `quest:{occurrence_id}` and `xp_transaction`.
  6. Update `character.total_xp` and the attribute XP.
  7. Write journal events (including level-ups), check achievements, update the streak, insert notifications.
  8. Commit, then dispatch.
- **Auto-confirm:** `submit` runs the same path immediately.
- **Purchase** (`RewardService.purchase`), in one transaction:
  1. Lock the reward and the buyer wallet.
  2. Check: active partnership, buyer ≠ creator, status active, quantity, cooldown (the last non-refunded purchase by the buyer is older than `cooldown_days`), and balance ≥ price.
  3. Debit the wallet with key `purchase:{idempotency_key}`, decrement quantity (`sold_out` at 0), insert the purchase with a snapshot.
- **Refund:**
  - The provider can refund any status before `fulfilled`. The buyer can refund only while `purchased`.
  - A positive `reward_refund` transaction is written with key `refund:{purchase_id}`.
  - Quantity is restored.
- **Dispute:** the buyer can dispute within 48h of `fulfilled_at`. Status goes back to `requested`, with a journal event and no Gold change.
- **Partnership end** (`PartnershipService.leave`):
  - Template statuses become `cancelled`. Offered, active and in_review occurrences become `cancelled`.
  - Wallets are frozen: no new purchases, though refunds still credit them.
  - Rewards are hidden.
  - The partner is notified.
  - Re-pairing the same two users reactivates the row, along with the wallets, shop and history.
- **Account deletion:**
  - Delete PII on `user` and `character`, plus files, goals, wishlist and submission comments.
  - Set display_name to "Deleted user".
  - Keep the ledger rows so the companion's history and balances stay consistent.
  - End the partnership.
- **Recurrence** (`app/jobs/generate_occurrences.py`), every 10 min plus at startup:
  - For each active daily or weekly template, create today's (or this ISO week's) occurrence in the assignee's timezone if it is missing, with `ON CONFLICT DO NOTHING`.
  - Occurrences are `active` because the template is already accepted.
  - The job does not backfill missed past days: a missed day is not generated, and that is not a penalty.
- **Expiry** (`expire_occurrences.py`, every 5 min): `active` and past `due_at` → `expired`. Never `in_review`.

## 5. API surface

All routes are under `/api`, return JSON, and require JWT except `POST /auth/telegram`. All write routes are rate-limited per user (`app/core/ratelimit.py`, in-memory token bucket).

```
POST   /auth/telegram                     validate initData (HMAC per Telegram docs, auth_date ≤24h) → upsert user → {jwt, user, start_param}
GET    /auth/me                           current user + character + partnership summary

GET    /character                         my character: level, xp progress, attributes, gold (active wallet), counts
PATCH  /character                         name, nickname, bio, locale, timezone
POST   /character/avatar                  upload avatar (multipart) → file id
POST   /character/onboarding/complete     mark onboarded (goals chosen)

POST   /partnership/invitations           create invite (revokes previous pending) → {token, link}
DELETE /partnership/invitations/current   revoke pending invite
POST   /partnership/invitations/accept    {token} → activate/reactivate partnership
GET    /partnership                       active partnership + companion public profile
GET    /partnership/companion             companion character, attributes, recent shared activity, goals, wishlist, life balance
POST   /partnership/leave                 {confirm_text} → end partnership

GET    /quests?role=player|gm&status=…    occurrences list (filters for tabs)
POST   /quests                            create quest template + first offered occurrence (or revision 1 for recurring)
GET    /quests/{occurrence_id}            detail incl. submissions, pending revision
PATCH  /quests/{occurrence_id}            propose revision (if active) or edit freely (if still offered)
POST   /quests/{id}/accept                accept offer or pending revision
POST   /quests/{id}/decline               {reason?}
POST   /quests/{id}/submit                {comment?, attachment_id?} (Idempotency-Key); auto-confirm path completes
POST   /quests/{id}/confirm               {feedback?} (Idempotency-Key)
POST   /quests/{id}/request-redo          {reason}
POST   /quests/{id}/cancel                either party
POST   /quest-templates/{id}/pause        
POST   /quest-templates/{id}/resume       
GET    /quest-presets                     built-in presets (localized) + my saved templates
POST   /quest-presets                     save a template
DELETE /quest-presets/{id}
GET    /quests/estimate?gold=&recurrence= weekly/monthly gold estimate

GET    /rewards?shop=companion|mine       rewards list
POST   /rewards                           create reward (optionally from wishlist_item_id)
PATCH  /rewards/{id}                      price/availability/etc (future purchases only)
POST   /rewards/{id}/image                upload image
POST   /rewards/{id}/purchase             (Idempotency-Key)

GET    /inventory?side=buyer|provider     purchases
POST   /inventory/{id}/request            buyer
POST   /inventory/{id}/schedule           provider {scheduled_for, note?}
POST   /inventory/{id}/fulfill            provider
POST   /inventory/{id}/dispute            buyer, ≤48h after fulfill
POST   /inventory/{id}/refund             provider (before fulfilled) / buyer (only while purchased)

GET    /economy/balance                   active wallet balance (+ frozen wallets)
GET    /economy/transactions?cursor=      my ledger (private)

GET    /stats?period=7d|30d|all           counts, xp/day, quests/day, gold earned/spent, rewards
GET    /stats/life-balance?period=7d|30d&user=me|companion   scores + suggestions
PUT    /stats/life-balance/targets        my targets
GET    /achievements                      definitions + unlocks
GET    /journal?scope=me|shared&cursor=   journal events

GET/POST/PATCH/DELETE /goals[/{id}]       my development goals (GET ?user=companion allowed)
GET/POST/PATCH/DELETE /wishlist[/{id}]    my wishlist (GET ?user=companion allowed)

GET    /notifications?cursor=             inbox
POST   /notifications/{id}/read
POST   /notifications/read-all
PATCH  /notifications/preferences         categories, quiet hours, daily summary
POST   /notifications/write-access        record can_message after requestWriteAccess

GET    /files/{id}                        authorized file stream (owner or active partner)
POST   /files                             upload quest photo (multipart, ≤10MB, jpeg/png/webp/heic → re-encoded jpeg/webp, EXIF stripped)

GET    /account/export                    JSON export of my data
DELETE /account                           {confirm_text} delete account

GET    /healthz                           liveness + DB ping (no auth)
POST   /tg/webhook/{secret}               aiogram webhook (outside /api)
POST   /api/test/reset                    ONLY when APP_ENV=test: truncate DB for Playwright
```

**Bot**

- `/start [payload]` sends a welcome message and a `WebAppInfo` button.
- Payloads `invite_<token>` and `q_<id>` are passed through to the Mini App `startapp`.
- Notification messages carry an inline button to `https://t.me/<BOT>/<APP>?startapp=q_<id>` (or `r_<id>`, `inv_<id>`).
- The frontend's `lib/deeplink.ts` maps `startParam` to a route.

## 6. Screens

Every user is both Player and Game Master. "Role" below means the role the screen serves. GM actions get a distinct accent and a "You are the Game Master" label.

| Route | Screen | Role |
|---|---|---|
| `/onboarding/*` | Character (name, avatar, nickname, bio) → Goals → Invite companion (share link via `switchInlineQuery`/copy) → Waiting/Start | new user |
| `/invite/:token` | Accept invitation (shows inviter's character) | invitee |
| `/` | Home: avatar, level, XP bar, gold, today's quests, offers, pending confirmations, bell, recent activity, quick actions, gear | both |
| `/quests` | Tabs: My active · Offers · Recurring · Assigned by me · To confirm · Completed; FAB "New quest" | Player + GM |
| `/quests/new` (bottom sheet) | Create quest: title, attribute chips, difficulty chips, gold slider; "More options" (recurrence, deadline, confirmation, photo); preset picker; inflation estimate | GM |
| `/quests/:id` | Quest detail: terms, status timeline, submit (comment + photo), confirm / redo / cancel, pending revision accept | Player or GM by relation |
| `/shop` | Companion's rewards, gold balance, filters | Player |
| `/shop/inventory` | My vouchers by status; request; dispute; refund | Player |
| `/shop/manage` | My shop CRUD; create from wishlist; requests to fulfill (schedule / fulfill / refund) | GM (provider) |
| `/stats` | Attributes, level progress, Life Balance radar (7d/30d, targets editor), charts, achievements | both (self) |
| `/stats/journal` | Adventure Journal | both |
| `/companion` | Companion profile, attributes, life balance + suggestions, recent activity, goals, wishlist, "Create quest", "Create reward" | GM |
| `/me/goals`, `/me/wishlist` | Manage my goals and wishlist | Player |
| `/notifications` | Inbox | both |
| `/settings` | Language, timezone, notification categories + quiet hours + daily summary, enable bot messages, export data, privacy note, leave partnership (typed confirm sheet), delete account (typed confirm sheet) | both |

Bottom nav: Home · Quests · Shop · Stats · Companion.

Unpaired users can use profile, goals, wishlist, settings and manage-shop. The Quests and Companion tabs show the invite CTA.

**Reusable components:** `XpBar`, `GoldBadge`, `AttributeChip`, `DifficultyChip`, `QuestCard`, `RewardCard`, `VoucherCard`, `StatusPill`, `BottomSheet`, `ConfirmSheet` (replaces `confirm()`), `LifeBalanceRadar`, `CelebrationOverlay` (level up, quest complete, purchase), `EmptyState`, `Avatar`.

## 7. Non-functional requirements

| Requirement | How it is satisfied |
|---|---|
| Authoritative backend | The frontend never sends XP, Gold amounts, prices or identity. Services read the terms from DB snapshots. |
| Auth security | `app/modules/auth/telegram.py::validate_init_data` checks the HMAC-SHA256 (secret = HMAC("WebAppData", BOT_TOKEN)) with a constant-time compare and `auth_date` ≤ 24h. The JWT is HS256 with 24h expiry and `JWT_SECRET` from env. The bot token is backend-only. |
| Authorization | `app/core/deps.py`: `current_user` and `active_partnership`. Each service checks participation, the assignee ≠ creator rule, the reviewer = creator rule, and buyer ≠ provider. Tests cover every forbidden path. |
| Transaction integrity | One DB transaction per command, `FOR UPDATE` locks, CHECK constraints (balance ≥ 0, quantity ≥ 0), unique idempotency keys, a unique occurrence per date. Tested by `tests/integration/test_concurrency.py`, which fires parallel confirm and purchase requests over separate connections, and `tests/integration/test_ledger_invariants.py`, which checks `wallet.balance == sum(ledger)` and XP totals == sum of `xp_transaction`. |
| State machine validity | `app/modules/quests/state.py` and `app/modules/rewards/state.py` hold explicit transition tables, with a unit test per allowed and forbidden transition. |
| Scheduled work survives restarts | Jobs are pure functions of DB state (generate-if-missing, expire-if-past, outbox sweep), so a restart catches up. The single scheduler process takes a Postgres advisory lock at start (`pg_try_advisory_lock`). |
| Notifications after commit | Outbox table and dispatcher. Tests assert that a rolled-back transaction leaves no notification. |
| Timezones | `user.timezone` (IANA) uses `zoneinfo`. Times are stored in UTC, and calendar maths (day and week boundaries, quiet hours, 7/30-day windows) runs in the user's timezone. |
| Privacy | Files are only reachable through `/api/files/{id}` with an owner or active-partner check, and access is revoked when the partnership ends. EXIF is stripped. Minimal Telegram fields are stored (id, username, first/last name, photo_url, language_code). Export and delete endpoints exist. |
| Load (≤100 users) | 1 uvicorn worker on Railway, an asyncpg pool of 10, and a static SPA. No caching layer. |
| Rate limiting | Per-user token bucket in memory: 30 writes/min, 5 uploads/min. |
| Accessibility | Semantic HTML, focus rings, contrast AA on dark and light palettes, `useReducedMotion()` gating Motion and confetti. |
| i18n | `react-i18next` (`frontend/src/i18n/{en,uk}.json`). Bot strings live in `backend/app/bot/i18n/{en,uk}.json`. Locale comes from `user.locale`, defaulted from Telegram `language_code` (`uk` → uk, else en). A test asserts both catalogs have the same keys. |
| Telegram UX | `TelegramAdapter` handles safe-area insets (CSS vars from `viewport`), the BackButton bound to router history, haptics on actions, `enableClosingConfirmation` while forms are dirty, theme params (header and background colour), and refetch on `visibilitychange` / activation. Feature detection falls back to `MockAdapter` behaviour. |
| Observability | `structlog` JSON logs with request id and user id. `sentry-sdk` (backend) and `@sentry/react` (frontend) are enabled when `SENTRY_DSN` is set. |
| Type safety | mypy strict and tsc strict. `pnpm gen:api` regenerates `frontend/src/lib/api/schema.d.ts`, and CI fails on a diff. |

## 8. Infrastructure and environments

**Environments**

- **local** uses dev bot `@<name>_dev_bot` [ASSUMPTION: name chosen by the client].
- **prod** runs on Railway with the prod bot.
- **test** is CI and local Playwright with `APP_ENV=test`, a separate DB `telerpg_test`, and a fake bot token. Outbound Telegram calls go to `FakeBot`, which records them.

**Local** (`./init.sh`, idempotent)

1. `docker compose up -d postgres`. `docker-compose.yml` runs `postgres:17` on port 5432 and creates the `telerpg` and `telerpg_test` DBs via `scripts/db-init.sql`. A `full` profile also containerizes api, scheduler and frontend.
2. `uv sync` in `backend/` and `pnpm install` at the root (pnpm workspace: `frontend`).
3. `uv run alembic upgrade head`.
4. Start the dev processes. `pnpm dev` uses `concurrently` to run Vite (5173, proxying `/api` → 8000), uvicorn `--reload` (8000), `app.bot.polling` and `app.jobs.runner`.

- To use real Telegram from local, run `cloudflared tunnel --url http://localhost:5173` and set the dev bot's Mini App URL [ASSUMPTION: cloudflared installed by the developer].
- `.env.example` lists `DATABASE_URL`, `TEST_DATABASE_URL`, `TG_BOT_TOKEN`, `TG_BOT_USERNAME`, `TG_APP_SHORT_NAME`, `TG_WEBHOOK_SECRET`, `JWT_SECRET`, `APP_ENV`, `PUBLIC_BASE_URL`, `STORAGE_DIR`, `SENTRY_DSN`, `VITE_SENTRY_DSN`.

**Railway (prod)**

| Service | Details |
|---|---|
| `api` | Dockerfile `backend/Dockerfile`, multi-stage: builds the frontend with pnpm and copies `dist` into the image. Runs `uvicorn app.main:app` (image `CMD`). Pre-deploy command `alembic upgrade head`, health check `/healthz`, restart On Failure, 1 replica. Volume mounted at `/data/files` (`STORAGE_DIR`). The webhook is set on startup with `setWebhook(PUBLIC_BASE_URL/tg/webhook/<secret>)`. |
| `scheduler` | Same image, start command `python -m app.jobs.runner`, 1 replica, no health check. |
| database | Supabase Postgres (not a Railway service), via the session pooler (port 5432, `?ssl=require`); backups on the Supabase side. No Railway Postgres. |

- HTTPS uses the Railway domain [ASSUMPTION: no custom domain initially].
- Secrets live in Railway variables only. Services are configured in the Railway dashboard (no `railway/*.json`: Config as Code is deprecated and Infrastructure as Code has no Dockerfile or restart field yet); both set `RAILWAY_DOCKERFILE_PATH=backend/Dockerfile`. The api refuses to start in prod without a mounted volume at `STORAGE_DIR`. Step-by-step: [DEPLOY.md](DEPLOY.md).

**CI** (`.github/workflows/ci.yml`, on PR and push to main)

- Postgres 17 service, uv and pnpm setup.
- Runs `pnpm lint`, `pnpm test` and `pnpm gen:api --check`.
- Then `pnpm build` and `pnpm e2e` (Playwright chromium, mobile viewport 390×844). Screenshots are uploaded as artifacts.
- Railway auto-deploys `main` once checks pass.

**Root scripts** (`package.json`)

```
dev       concurrently vite + api + bot polling + scheduler
build     pnpm -C frontend build
test      pnpm -C frontend test --run && (cd backend && uv run pytest -q)
lint      pnpm -C frontend lint && pnpm -C frontend typecheck && (cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app)
gen:api   (cd backend && uv run python -m app.export_openapi) && openapi-typescript backend/openapi.json -o frontend/src/lib/api/schema.d.ts
e2e       playwright test   (playwright.config.ts starts api with APP_ENV=test + vite preview; saves docs/screens/<id>.png)
```

### Running live from Telegram

`scripts/live.sh start|stop|status|logs|check` runs a second stack next to the test stack
(`init.sh`, 8000/3000): uvicorn on `LIVE_API_PORT` (8010), vite on `LIVE_WEB_PORT` (3010, proxies
`/api` and `/healthz` to the live API via `API_PROXY_TARGET`/`VITE_DEV_PORT`), the bot and the
scheduler, with `APP_ENV=development`. `check` validates only. `start` and `check` refuse:
an unset `DATABASE_URL`; `DATABASE_URL` equal to `E2E_DATABASE_URL` or ending in `_e2e`; a scheme
other than `postgresql://`, `postgres://` or `postgresql+asyncpg://`; port 6543 (Supabase transaction pooler); an unset or fake
`TG_BOT_TOKEN`; an unset `JWT_SECRET`, the dev default or one shorter than 32 characters
(`openssl rand -hex 32`); non-numeric ports, ports outside 1024-65535, 8000/3000 (test stack) or
`LIVE_API_PORT == LIVE_WEB_PORT`. `/api/test/reset` answers 404 outside `APP_ENV=test`.

`.env` format: plain `KEY=VALUE` lines read by a line parser, never sourced, so there is no shell
expansion (`$`, `&`, backticks, `$(...)` are literal). Blank lines and `#` lines are skipped, an
optional `export ` prefix is accepted, one matching pair of surrounding single or double quotes is
stripped, inline comments are not supported. Only known keys are read (database/e2e URLs, `TG_*`,
`PUBLIC_BASE_URL`, `JWT_*`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `STORAGE_DIR`, `IMAGE_PROCESS_CONCURRENCY`,
`SENTRY_DSN`, `FRONTEND_DIST`, `LIVE_*_PORT`); `APP_ENV` is forced to `development`.

Secrets: never printed. The DB password is masked (everything between `user:` and the last `@`),
xtrace is switched off while secrets are parsed or compared (so `bash -x` does not leak them), and
child processes get them through the environment, not argv. `stop`/`start` verify a pidfile's pid
with `ps -o command=` against the expected service (uvicorn `app.main:app` with the live port, vite,
`app.bot.polling`, `app.jobs.runner`); a mismatch means pid reuse: the pidfile is dropped and
nothing is killed. If `start` fails partway (port busy, migration error, health timeout) the
services it started are stopped. `init.sh` migrates the dev DB only when `DATABASE_URL` is local and
unsets `VITE_DEV_PORT`/`API_PROXY_TARGET` before starting the test stack.
Then: `ngrok http 3010`, set the URL in BotFather (Main App, Menu Button, Direct Link) and
`PUBLIC_BASE_URL`, `live.sh stop && live.sh start`.

Supabase notes: the app normalizes `postgres://` and `postgresql://` to `postgresql+asyncpg://` and
`?sslmode=X` to `?ssl=X` (asyncpg has no `sslmode`; `ssl` wins if both are given). The direct
host (`db.<ref>.supabase.co:5432`) is IPv6-only; use the session pooler
(`aws-0-<region>.pooler.supabase.com:5432`, user `postgres.<ref>`, `?ssl=require`). Never the transaction pooler
(port 6543): asyncpg prepared statements and the session-level advisory lock (scheduler) break
there. URL-encode special characters in the password (`@` is `%40`, `/` is `%2F`).

## 9. Open questions for the client

1. Bot usernames and the Mini App short name for dev and prod. These are needed for deep links (`TG_BOT_USERNAME`, `TG_APP_SHORT_NAME`).
2. Who writes the Ukrainian copy: is agent translation acceptable, or will you proofread `uk.json`?
3. Content of the built-in quest preset library. [ASSUMPTION: about 4 presets per attribute (24 total), taken from brief §10.]
4. HEIC uploads: iOS Telegram usually delivers JPEG already. Is server-side HEIC conversion with `pillow-heif` worth keeping, or should HEIC be rejected? [ASSUMPTION: keep it.]
5. Railway volumes pin the `api` service to one replica, and files are lost if the volume is deleted. Is that acceptable until S3 is introduced?
6. Daily summary send time. [ASSUMPTION: 09:00 local, skipped inside quiet hours.] Default quiet hours. [ASSUMPTION: 23:00–08:00.]
7. Does a dispute after the 48h window get any path, such as a free-text note to the companion? [ASSUMPTION: no.]
8. Sentry: will you create a project and provide the DSN, or should Sentry stay off until later?
9. Privacy note text: is a short agent-written note in Settings sufficient?

## 10. Verification

**The whole system:** `pnpm lint && pnpm test && pnpm e2e`. CI runs the same.

**`pnpm test`**

- Frontend: Vitest + React Testing Library for components, hooks, the deeplink mapper and i18n key parity.
- Backend: pytest + pytest-asyncio + HTTPX `AsyncClient` against the real Postgres `telerpg_test`.
  - Unit: levels formula (table from brief §9), state machines, `validate_init_data` (valid, tampered, expired), recurrence date maths across timezones and DST.
  - Integration:
    - full quest lifecycle
    - auto-confirm
    - revisions
    - authorization matrix: every forbidden action returns 403/409
    - purchase / refund / dispute
    - quantity and cooldown limits
    - partnership end and re-pair
    - account deletion
    - outbox after commit
  - `test_concurrency.py`: 10 parallel confirms give exactly one reward, and parallel purchases of the last unit give exactly one sale.
  - `test_ledger_invariants.py`: balances equal the ledger, and the balance is never negative.
  - `test_jobs.py`: generation is idempotent across repeated runs and restarts; expiry skips in_review.

**`pnpm e2e`** (Playwright)

- `e2e/fixtures/telegram.ts` builds validly signed initData for users A and B with the test bot token. It injects a `window.Telegram.WebApp` stub before the page loads, and calls `/api/test/reset` before each test.
- Each test is tagged `@<stage-id>` and saves `docs/screens/<id>.png`.
- The P0 acceptance test `e2e/core-loop.spec.ts @P0`, with two browser contexts, does the following:
  1. A and B authenticate automatically.
  2. A and B complete onboarding.
  3. A creates an invite; B opens `startapp=invite_<token>` and accepts.
  4. A creates a Normal / Physical / 50 Gold quest; B accepts.
  5. B submits; A confirms.
  6. B sees 50 Gold, 50 XP and Physical XP 50.
  7. A creates the reward "Movie night" at 40 Gold; B purchases it, and the balance is 10.
  8. B requests the reward; A schedules and fulfills it.
  9. B's inventory shows Fulfilled, and the journal shows every event.
- A P1 acceptance test `e2e/p1-features.spec.ts @P1` covers life balance, journal, achievements toast, photo submit, goals and wishlist→reward, notification inbox, and the language switch to `uk`.

**Manual:** before each milestone sign-off, do a walkthrough in real Telegram (iOS and Desktop) on prod, using the `core-loop` steps above.

**Smoke:** `scripts/smoke.sh` checks `GET /healthz` = 200 with the DB ok, `GET /` serves the SPA, and `alembic current` == head.
