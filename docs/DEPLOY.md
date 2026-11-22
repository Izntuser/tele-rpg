# Deploy to Railway (Hobby) with Supabase Postgres

Two Railway services from one image (`backend/Dockerfile`, built from the repo root): `api` and `scheduler`.
The database is Supabase Postgres; there is no Railway Postgres (see the short appendix). Config lives in
`railway/api.json` and `railway/scheduler.json`.

## 1. First-deploy order

Do these in order; the first deploy must see a complete configuration.

1. Railway: New Project, **Empty Project**. Add two **empty services** (not from the repo yet): `api` and `scheduler`.
2. For each, Settings, "Config-as-code path" (Railway Config File): `/railway/api.json` for `api`, `/railway/scheduler.json` for `scheduler`.
3. `api`: Settings, Networking, **Generate Domain**. The scheduler gets no public domain.
4. `api`: add the volume (section 3).
5. Set **all variables** on both services (section 4), including `PUBLIC_BASE_URL` via the reference variables below.
6. Only now connect the GitHub repo to each service (Settings, Source) and deploy.

Why: `preDeployCommand` (`alembic upgrade head`) loads the same prod `Settings` guards as the app, so every prod
variable (`DATABASE_URL`, `JWT_SECRET`, `TG_*`, `PUBLIC_BASE_URL`, ...) must already exist before the first deploy,
or the pre-deploy step fails and the release never starts.

Other settings in the config files:

- **Exactly 1 replica each** (`numReplicas: 1`; do not scale up). The scheduler takes a Postgres advisory lock, so extra replicas would only idle. The API keeps in-process state (image-decode semaphores, rate limiters, the post-commit notification dispatcher), so a second replica would split that state.
- `api` runs `alembic upgrade head` as `preDeployCommand` before each release and is health-checked on `/healthz`. `scheduler` has neither.
- `requiredMountPath: "/data/files"` (api only): Railway refuses to deploy `api` unless a volume is mounted at that path. This turns "forgot the volume, uploads vanish on every deploy" into a failed deploy instead of silent data loss.

## 2. Database: Supabase (session pooler)

`DATABASE_URL` (same value on `api` and `scheduler`):

```
postgresql://postgres.<project-ref>:<URL-ENCODED-PASSWORD>@aws-0-<region>.pooler.supabase.com:5432/postgres?ssl=require
```

- Host `aws-0-<region>.pooler.supabase.com`, port **5432** (session pooler), user `postgres.<project-ref>`. Copy it from Supabase, Connect, "Session pooler".
- `?ssl=require` is required. `?sslmode=require` also works: the app (and alembic, which reads the same Settings) rewrites `sslmode=X` to `ssl=X` because asyncpg has no `sslmode` argument. If both are present, `ssl` wins.
- The `postgresql://` scheme is normalized to `postgresql+asyncpg://` by the app and by alembic.
- **Never port 6543** (transaction pooler): asyncpg prepared statements and the scheduler's session-level advisory lock break there.
- **Do not use the direct host** (`db.<ref>.supabase.co`): it is IPv6-only, and outbound IPv6 is opt-in on Railway.
- **URL-encode the password** (`@` is `%40`, `/` is `%2F`, `:` is `%3A`, `#` is `%23`, `?` is `%3F`, `%` is `%25`). Easiest: reset the DB password to letters and digits only.
- **Backups are on the Supabase side.** Check what your plan includes (daily backups are a paid-plan feature; PITR is an add-on); on a plan without them run `pg_dump` against the session pooler on a schedule and before risky migrations.
- **Free projects pause after about a week of inactivity** (the app then fails its health check and DB calls). Use a paid plan for prod, or keep the project active.

### Connection budget

Postgres connections used per process:

| Process | Connections |
|---|---|
| `api` pooled engine | up to `DB_POOL_SIZE + DB_MAX_OVERFLOW` |
| `api` `/healthz` | 1 transient (NullPool, not pooled) |
| `scheduler` | 1 held for its whole life (leader lock) + about 1 per running job (NullPool); allow 3 in total |
| `preDeploy` migration | 1 for the few seconds it runs (NullPool) |

Railway deploys the new `api` while the old one still runs, so for a short time **two api instances** hold connections. Budget:

```
peak = 2 * (DB_POOL_SIZE + DB_MAX_OVERFLOW)   # old and new api
     + 2                                        # healthz + migration
     + 3                                        # scheduler
```

Worked example with the recommended `api` `DB_POOL_SIZE=4`, `DB_MAX_OVERFLOW=2`: 2 * 6 + 2 + 3 = **17** connections at peak. With `DB_POOL_SIZE=3`, `DB_MAX_OVERFLOW=1`: 2 * 4 + 5 = **13**.

Compare the peak with the Supabase pooler's pool size and keep it below, with room for the Supabase dashboard and your own `psql`/`pg_dump`. **Do not trust a number from this document:** check your project's pool size in Supabase, Database, Settings, connection pooling (it depends on plan and compute size; small instances have a small default). If it is about 15, use `3`/`1`; if it is 20 or more, `4`/`2` is fine. A small pool is safe for this app (at most 100 users, one worker); requests only wait briefly for a free connection.

Both settings apply to the **api only**. The scheduler builds its engine with NullPool (`app.core.db.make_engine`), so `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` have no effect there; its footprint is the fixed ~3 above. Set the pool variables per service, not in shared variables: if the scheduler ever moves to a pooled engine it reads its own `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` from its own service variables.

### Appendix: Railway Postgres (optional)

If you do not want Supabase: add the Railway Postgres plugin and set `DATABASE_URL=${{Postgres.DATABASE_URL}}` on both services (enable Backups on that service). The same connection budget applies against its `max_connections`. This is not the supported prod path.

## 3. Volume and domain

- Volume on `api` only, mount path `/data/files` (the image sets `STORAGE_DIR=/data/files`; `requiredMountPath` enforces it).
- Public domain for `api` only (generated in step 3 of the first-deploy order).

### Photos volume

- Hobby volumes are limited to **5 GB** each. Avatars and uploads are re-encoded and size-capped, but watch usage in the volume's metrics.
- The volume is **not covered by Supabase backups** (those are database only). Photos live only on this volume.
- Back up or download: use Railway volume backups if your plan offers them (volume Settings), or open a shell on the service (`railway ssh` with the project linked, service `api`) and stream a tar out, for example `railway ssh -- tar czf - -C /data files > photos.tgz`. Railway's CLI and volume features change; check the current Railway docs (volumes and CLI `ssh`) before relying on these commands, and test a restore once.
- `StorageBackend` is an interface, so an object-storage backend (S3-compatible, Supabase Storage) can replace the volume later without touching callers.

## 4. Secrets and variables

Generate secrets: `openssl rand -hex 32` (one for `JWT_SECRET`, another for `TG_WEBHOOK_SECRET`).

Both services refuse to start with `APP_ENV=prod` unless: real `TG_BOT_TOKEN`, `JWT_SECRET` non-default and at least 32 chars, `TG_WEBHOOK_SECRET` at least 32 chars, `TG_BOT_USERNAME`, `TG_APP_SHORT_NAME`, `PUBLIC_BASE_URL` starting with `https://`. Put the shared ones in Railway shared variables (or reference them: `${{shared.NAME}}`).

`PUBLIC_BASE_URL` is a reference variable, set before the first deploy:

- on `api`: `PUBLIC_BASE_URL=https://${{RAILWAY_PUBLIC_DOMAIN}}`
- on `scheduler`: `PUBLIC_BASE_URL=https://${{api.RAILWAY_PUBLIC_DOMAIN}}`

(Not a shared variable: the reference differs per service.)

| Variable | api | scheduler | Notes |
|---|---|---|---|
| `APP_ENV` | `prod` | `prod` | shared |
| `DATABASE_URL` | yes | yes | Supabase session pooler URL with `?ssl=require`, shared |
| `TG_BOT_TOKEN` | yes | yes | prod bot token, shared |
| `TG_BOT_USERNAME` | yes | yes | without `@`, shared |
| `TG_APP_SHORT_NAME` | yes | yes | BotFather Main App short name, shared |
| `TG_WEBHOOK_SECRET` | yes | yes | shared |
| `JWT_SECRET` | yes | yes | shared |
| `PUBLIC_BASE_URL` | yes | yes | reference variables above, per service |
| `DB_POOL_SIZE` | `4` | unused | api only, see Connection budget |
| `DB_MAX_OVERFLOW` | `2` | unused | api only |
| `STORAGE_DIR` | optional | optional | defaults to `/data/files` in the image; only api has the volume |
| `SENTRY_DSN` | optional | optional | |
| `PORT` | set by Railway | unused | |

## 5. BotFather (prod bot, not the local dev bot)

Use a separate bot for prod; the local dev bot (`@..._dev_bot`) keeps its own token in your local `.env`. For the prod bot in BotFather: Main App (`/newapp` or `/myapps`), Menu Button (`/setmenubutton`) and the Direct Link URL all set to `https://<api domain>`. The short name must equal `TG_APP_SHORT_NAME`.

## 6. Webhook (automatic) and polling

On start, `api` with `APP_ENV=prod` calls `setWebhook(PUBLIC_BASE_URL/tg/webhook/<secret>)`. Polling must not run anywhere for the prod bot: `getUpdates` and a webhook conflict. If `scripts/live.sh` (or `pnpm dev`) uses the same token, stop it (`scripts/live.sh stop`) or switch it to the dev bot token.

## 7. Verify

```
curl -s https://<domain>/healthz                      # {"status":"ok","db":"ok"}
curl -s "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"   # url ends with /tg/webhook/<secret>, no last_error_message
```

Then send `/start` to the prod bot, open the app from the menu button, log in, create a quest. Check the scheduler logs for `leader lock acquired`.

## 8. Proxy notes

Railway terminates TLS at its proxy. The start command runs uvicorn with `--proxy-headers --forwarded-allow-ips='*'` so `request.client` (the login rate-limit key) is the real client IP, not the proxy's. Trade-off: with `*` the app trusts `X-Forwarded-For` from any peer, but the container is only reachable through Railway's proxy, and the worst a spoofed header does is rotate the login rate-limit bucket (login still needs valid signed initData). Upload and write limits are per user, not per IP. The webhook route and SPA fallback use only paths, so they are unaffected.

## 9. Rollback

Railway, `api` (and `scheduler`), Deployments, pick the last good one, Redeploy/Rollback. Migrations are not reverted automatically: if a release added a migration, either keep it (additive) or run `alembic downgrade -1` from a one-off shell against the DB before rolling back. Roll the scheduler back with the api so both run the same schema expectations.

## 10. Backups

- Database: Supabase backups (check your plan; see section 2) plus `pg_dump` against the session pooler before risky migrations.
- Volume `/data/files`: see "Photos volume" in section 3; Supabase backups do not cover it.
