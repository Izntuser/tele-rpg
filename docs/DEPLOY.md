# Deploy to Railway (Hobby) with Supabase Postgres

Two Railway services from one image (`backend/Dockerfile`, built from the repo root): `api` and `scheduler`.
The database is Supabase Postgres; there is no Railway Postgres (see the short appendix). Everything is configured
in the Railway dashboard; the repo holds no Railway config files.

**Why not Config as Code or Infrastructure as Code.** Railway deprecated Config as Code (existing files work until
2026-12-01; from 2026-08-28 services that never used it cannot opt in), and our services are new. Railway's new
Infrastructure as Code (`.railway/railway.ts`, `railway config plan/apply`) documents no field for a Dockerfile
builder or a restart policy as of 2026-11-22, so we do not adopt it now. Revisit when it does.

## 1. First-deploy order

Do these in order; the first deploy must see a complete configuration.

1. Railway: New Project, **Empty Project**. Add two **empty services** (not from the repo yet): `api` and `scheduler`.
2. Per-service settings and `RAILWAY_DOCKERFILE_PATH` (list below).
3. `api`: Settings, Networking, **Generate Domain**; add the volume (section 3). The scheduler gets no domain and no volume.
4. Set **all variables** on both services (section 4), including `PUBLIC_BASE_URL` via the reference variables below.
5. Only now connect the GitHub repo to each service (Settings, Source) and deploy.

Why: the pre-deploy command (`alembic upgrade head`) loads the same prod `Settings` guards as the app, so every prod
variable (`DATABASE_URL`, `JWT_SECRET`, `TG_*`, `PUBLIC_BASE_URL`, ...) must already exist before the first deploy,
or the pre-deploy step fails and the release never starts.

### Dashboard settings

**Both services**

- Variable `RAILWAY_DOCKERFILE_PATH=backend/Dockerfile` (Railway's documented way to use a Dockerfile outside the repo root; the build context stays the repo root, which the Dockerfile expects).
- Root Directory: leave empty (the build context must be the repo root; `RAILWAY_DOCKERFILE_PATH=backend/Dockerfile` is relative to it).
- Source: this repo, branch `main` (connect it last, step 5).
- Replicas: **1**. The scheduler takes a Postgres advisory lock, so extra replicas would only idle. The API keeps in-process state (image-decode semaphores, rate limiters, the post-commit notification dispatcher), so a second replica would split it.

**api**

- Custom start command: none (the Dockerfile `CMD` already runs uvicorn on `$PORT` with the proxy headers).
- Pre-deploy command: `alembic upgrade head`.
- Healthcheck path: `/healthz`, timeout `60`.
- Restart policy: On Failure, max retries `10`.
- Volume mounted at `/data/files`. **Nothing in Railway enforces this any more.** Without the volume, uploads silently disappear on every redeploy. **Verify the volume exists and its mount path is exactly `/data/files` before the first deploy.** As a backstop the api refuses to start with `APP_ENV=prod` unless Railway's `RAILWAY_VOLUME_MOUNT_PATH` (set automatically when a volume is attached) equals `STORAGE_DIR`. A volume attached at the wrong path makes the api refuse to start, with an error naming both paths; no volume at all gives "no Railway volume attached". `STORAGE_DIR` must also exist and be writable (escape hatch: `STORAGE_ALLOW_EPHEMERAL=true`, which accepts losing uploads; leave it unset). A failed start shows as a crash loop with `StorageVolumeError` in the logs.
- The pre-deploy migration runs in a separate container without the volume, which is fine: it only touches the database.
- Networking: Generate Domain.

**scheduler**

- Custom start command: `python -m app.jobs.runner`.
- No healthcheck, no pre-deploy command.
- Restart policy: On Failure.
- No domain, no volume.

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

Supavisor in session mode refuses clients beyond the project's pool size (about 15 on small plans). Count connections from the code, worst case:

| Process | Connections | Source |
|---|---|---|
| `api` pooled engine | up to `DB_POOL_SIZE + DB_MAX_OVERFLOW` per instance | `app/db/session.py` |
| `api` `/healthz` | at most 1 transient per instance (NullPool, serialized by a semaphore and a 2 s cache) | `app/main.py` |
| `preDeploy` migration | 1 for a few seconds (NullPool) | `alembic upgrade head` |
| `scheduler` leader lock | 1 held for the process lifetime | `try_lead` in `app/jobs/runner.py` |
| `scheduler` jobs | up to `SCHEDULER_MAX_CONCURRENT_JOBS`, 1 each (NullPool) | semaphore in `Runner._run_job` |

The runner registers 6 jobs that all fire at startup; the semaphore makes them take turns, so the scheduler never holds more than `1 + SCHEDULER_MAX_CONCURRENT_JOBS` connections. Railway starts the new instance while the old one still runs, so during a redeploy:

```
api       = 2 * (DB_POOL_SIZE + DB_MAX_OVERFLOW)   # old and new instance
          + 2                                       # healthz, one per instance
          + 1                                       # preDeploy migration
scheduler = (1 + SCHEDULER_MAX_CONCURRENT_JOBS)     # leader lock + jobs
          + 1                                       # new instance's try_lead while the old one runs
peak      = api + scheduler
```

Because a service with a volume cannot have two deployments mounted at once, the old and new api do not actually overlap on redeploy (expect brief downtime instead); the numbers above are kept as a safe overestimate.

Defaults with `APP_ENV=prod` (nothing set): `DB_POOL_SIZE=3`, `DB_MAX_OVERFLOW=0`, `SCHEDULER_MAX_CONCURRENT_JOBS=2` (dev and test default to 10/10):

| Part | Formula | Connections |
|---|---|---|
| api pools (old + new) | 2 * (3 + 0) | 6 |
| api healthz | 2 | 2 |
| api migration | 1 | 1 |
| scheduler lock + jobs | 1 + 2 | 3 |
| scheduler overlap | 1 | 1 |
| **Peak** | | **13** |

This is a deliberately pessimistic sum (the migration runs before the new api starts, so the real peak is about 12), and it leaves ~2 for manual access (dashboard/psql/pg_dump).

**Check your pool size** in Supabase, Database, Settings, connection pooling (it depends on plan and compute size). If it is 15, the defaults leave ~2 for manual access (dashboard/psql/pg_dump); for more headroom set `SCHEDULER_MAX_CONCURRENT_JOBS=1` (peak 12). If it is larger, raise the numbers using the formula and keep the peak at or below the pool size minus about 2 for manual access, for example a pool size of 30 allows `DB_POOL_SIZE=6`, `DB_MAX_OVERFLOW=2`, `SCHEDULER_MAX_CONCURRENT_JOBS=3`: 2*8 + 3 + 4 + 1 = 24. A small pool is safe for this app (at most 100 users, one worker); requests only wait briefly for a free connection, and scheduler jobs wait their turn.

**If you set `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` or `SCHEDULER_MAX_CONCURRENT_JOBS` explicitly, you override these defaults and the 13 above no longer holds: recompute the peak with the formula before deploying.** Do not copy the dev values (10/10) into prod: 2 * 20 alone is 40.

`DB_POOL_SIZE` and `DB_MAX_OVERFLOW` apply to the **api only** (the scheduler, healthz and migrations use NullPool). `SCHEDULER_MAX_CONCURRENT_JOBS` applies to the scheduler only. Set them per service, not in shared variables.

### Appendix: Railway Postgres (optional)

If you do not want Supabase: add the Railway Postgres plugin and set `DATABASE_URL=${{Postgres.DATABASE_URL}}` on both services (enable Backups on that service). The same connection budget applies against its `max_connections`. This is not the supported prod path.

## 3. Volume and domain

- Volume on `api` only, mount path `/data/files` (the image sets `STORAGE_DIR=/data/files`; the api startup check enforces the mount in prod, see above).
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
| `DB_POOL_SIZE` | leave unset (prod default `3`) | unused | api only, see Connection budget |
| `DB_MAX_OVERFLOW` | leave unset (prod default `0`) | unused | api only |
| `SCHEDULER_MAX_CONCURRENT_JOBS` | unused | leave unset (default `2`) | scheduler only, see Connection budget |
| `STORAGE_DIR` | optional | optional | defaults to `/data/files` in the image; only api has the volume |
| `STORAGE_ALLOW_EPHEMERAL` | leave unset | unused | `true` skips the api's check that `RAILWAY_VOLUME_MOUNT_PATH` equals `STORAGE_DIR` (uploads then lost on redeploy) |
| `RAILWAY_DOCKERFILE_PATH` | `backend/Dockerfile` | `backend/Dockerfile` | build setting, see Dashboard settings |
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

Logs are single-line JSON in prod (INFO to stdout), so Railway colours levels correctly and `@level:"error"` now shows only real errors; successful scheduler job runs are not logged.

## 8. Proxy notes

Railway terminates TLS at its proxy. The image `CMD` runs uvicorn with `--proxy-headers --forwarded-allow-ips='*'` so `request.client` (the login rate-limit key) is the real client IP, not the proxy's. Trade-off: with `*` the app trusts `X-Forwarded-For` from any peer, but the container is only reachable through Railway's proxy, and the worst a spoofed header does is rotate the login rate-limit bucket (login still needs valid signed initData). Upload and write limits are per user, not per IP. The webhook route and SPA fallback use only paths, so they are unaffected.

## 9. Rollback

Railway, `api` (and `scheduler`), Deployments, pick the last good one, Redeploy/Rollback. Migrations are not reverted automatically: if a release added a migration, either keep it (additive) or run `alembic downgrade -1` from a one-off shell against the DB before rolling back. Roll the scheduler back with the api so both run the same schema expectations.

## 10. Backups

- Database: Supabase backups (check your plan; see section 2) plus `pg_dump` against the session pooler before risky migrations.
- Volume `/data/files`: see "Photos volume" in section 3; Supabase backups do not cover it.
