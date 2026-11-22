# Deploy to Railway

Two services from one image (`backend/Dockerfile`, built from the repo root), plus Postgres.
Config lives in `railway/api.json` and `railway/scheduler.json`.

## 1. Project and services

1. Railway: New Project, Deploy from GitHub repo, pick this repo. Delete any auto-created service you do not want.
2. Create two services from the same repo: `api` and `scheduler`.
3. For each, Settings, "Config-as-code path" (a.k.a. Railway Config File): `/railway/api.json` for `api`, `/railway/scheduler.json` for `scheduler`.
4. **Exactly 1 replica each** (the config pins `numReplicas: 1`; do not scale up). The scheduler takes a Postgres advisory lock, so extra replicas would only idle. The API keeps in-process state (image-decode semaphores, rate limiters, the post-commit notification dispatcher), so a second replica would split that state.
5. `api` runs `alembic upgrade head` as `preDeployCommand` before each release and is health-checked on `/healthz`. `scheduler` has neither.

## 2. Database

- **Option A (recommended): Railway Postgres plugin.** Add it to the project. On both services set `DATABASE_URL=${{Postgres.DATABASE_URL}}`. The `postgresql://` scheme is normalized to `postgresql+asyncpg://` by the app and by alembic.
- **Option B: Supabase.** Use the **session pooler** (`aws-0-<region>.pooler.supabase.com`, port **5432**, user `postgres.<ref>`) because the direct host is IPv6-only and Railway's outbound IPv6 is opt-in. **Never port 6543** (transaction pooler): asyncpg prepared statements and the scheduler's session advisory lock break there. URL-encode special characters in the password.

## 3. Volume and domain

- Volume on `api` only, mount path `/data/files` (the image sets `STORAGE_DIR=/data/files`). Without it uploads vanish on every deploy.
- Generate a public domain for `api` only (Settings, Networking). The scheduler has no public domain. The first deploy needs the domain before `PUBLIC_BASE_URL` can be set, so deploy once, then set the variable (redeploy).

## 4. Secrets and variables

Generate secrets: `openssl rand -hex 32` (one for `JWT_SECRET`, another for `TG_WEBHOOK_SECRET`).

Both services refuse to start with `APP_ENV=prod` unless: real `TG_BOT_TOKEN`, `JWT_SECRET` non-default and at least 32 chars, `TG_WEBHOOK_SECRET` at least 32 chars, `TG_BOT_USERNAME`, `TG_APP_SHORT_NAME`, `PUBLIC_BASE_URL` starting with `https://`. Put the shared ones in Railway shared variables (or reference them: `${{shared.NAME}}`).

| Variable | api | scheduler | Notes |
|---|---|---|---|
| `APP_ENV` | `prod` | `prod` | shared |
| `DATABASE_URL` | yes | yes | `${{Postgres.DATABASE_URL}}`, shared |
| `TG_BOT_TOKEN` | yes | yes | prod bot token, shared |
| `TG_BOT_USERNAME` | yes | yes | without `@`, shared |
| `TG_APP_SHORT_NAME` | yes | yes | BotFather Main App short name, shared |
| `TG_WEBHOOK_SECRET` | yes | yes | shared |
| `JWT_SECRET` | yes | yes | shared |
| `PUBLIC_BASE_URL` | yes | yes | `https://<api domain>`, no trailing slash, shared |
| `STORAGE_DIR` | optional | optional | defaults to `/data/files` in the image; only api has the volume |
| `DB_POOL_SIZE` | optional | optional | default 10 |
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

- Railway Postgres: enable Backups on the database service (Settings, Backups) and test a restore into a new service; also `pg_dump "$DATABASE_PUBLIC_URL" > backup.sql` before risky migrations.
- Supabase: daily backups on paid plans; otherwise `pg_dump` against the session pooler on a schedule.
- Volume `/data/files`: Railway volume backups (Settings on the volume) if available on your plan; avatars and uploads live only there.
