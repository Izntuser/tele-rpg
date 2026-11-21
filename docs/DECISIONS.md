# Key decisions

1. **Modular monolith: one FastAPI app plus a separate scheduler process, bot webhook mounted in FastAPI.** Reason: at ≤100 users, extra deploy units cost more than they give. The scheduler stays separate so jobs never double-run.
2. **FastAPI serves the built SPA from the same origin.** Reason: no CORS, no cross-site cookie problems in Telegram webviews, and one fewer Railway service.
3. **Telegram initData validated server-side, then a 24h JWT held in memory (no cookies).** Reason: cookies are unreliable in Telegram webviews, and re-validating initData on every launch is cheap.
4. **Gold wallet per (user, partnership); XP and levels global per user.** Reason: Gold from an ended partnership can't be spent with a new companion, and permanent progression stays with the user.
5. **Ledger is the source of truth; cached balance updated in the same transaction (CHECK ≥ 0, row locks, unique idempotency keys).** Reason: atomic, idempotent Gold and XP, with cheap balance reads.
6. **Recurring quest = template + accepted revision + one occurrence per local date (unique constraint).** Reason: generation is idempotent and catches up after restarts, and terms changes apply only to future occurrences through revisions.
7. **Transactional notification outbox in Postgres; no Redis.** Reason: messages are sent only after commit and survive restarts, with one fewer piece of infrastructure.
8. **Files on a Railway volume behind a `StorageBackend` interface, served through an authorized endpoint.** Reason: the client chose it for simplicity; S3 can be swapped in later without route changes.
9. **pnpm (frontend + root scripts) and uv (backend); TS types generated from OpenAPI.** Reason: fast installs and one set of commands (`pnpm test`, `pnpm lint`, `pnpm e2e`), with no hand-copied API types.
10. **Playwright authenticates with genuinely signed initData and a Telegram WebApp stub.** Reason: E2E tests exercise the real auth path without real Telegram.
