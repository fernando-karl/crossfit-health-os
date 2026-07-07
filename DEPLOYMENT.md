# Deployment (production host)

This documents how CrossFit Health OS actually runs in production on the single
host. It supersedes the Coolify/Docker/Supabase description in the older docs and
in `CLAUDE.md` — that stack is **not** how this instance is deployed.

> The app is a backend-only FastAPI service that serves both the JSON API and the
> Jinja2 HTML UI. There is no separate frontend deploy.

## Topology

| Component | Where | Notes |
|-----------|-------|-------|
| App (FastAPI/uvicorn) | systemd unit `crossfit.service` | `127.0.0.1:8003`, 2 workers, behind a reverse proxy |
| Database | **host** PostgreSQL 16 on `127.0.0.1:5432`, DB `crossfit` | NOT the Docker `postgres` container (that one serves other apps) |
| Cache/queue | Redis on `127.0.0.1:6379` | Celery workers are not wired up yet |
| Code + venv | `/opt/crossfit-health-os` | owned by the `crossfit` service user |

The app authenticates to Postgres and Redis over **TCP with a password**
(`DATABASE_URL`, `REDIS_URL`), so the OS user it runs as is independent of DB auth.

## Service user & systemd

The service runs as a dedicated, unprivileged system user **`crossfit`** (not root):

```ini
# /etc/systemd/system/crossfit.service
[Service]
User=crossfit
Group=crossfit
WorkingDirectory=/opt/crossfit-health-os/backend
EnvironmentFile=/opt/crossfit-health-os/backend/.env
ExecStart=/opt/crossfit-health-os/backend/venv/bin/uvicorn app.main:app \
    --host 127.0.0.1 --port 8003 --workers 2 \
    --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=always
# hardening (does not restrict writes under /opt)
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
```

- The whole tree `/opt/crossfit-health-os` is owned `crossfit:crossfit`.
- `backend/.env` is mode `640` (not world-readable — it holds secrets).
- Git management as root needs `git config --global --add safe.directory /opt/crossfit-health-os`
  because the tree is owned by `crossfit`.

Common operations:

```bash
systemctl status crossfit
systemctl restart crossfit
journalctl -u crossfit -n 50 --no-pager
curl -s http://127.0.0.1:8003/health     # {"status":"healthy",...}
```

## Database / migrations

Migrations are **Alembic** (`backend/alembic/versions`), not Supabase. Run from
`backend/` with `DATABASE_URL` exported:

```bash
cd /opt/crossfit-health-os/backend
export DATABASE_URL=$(grep -E '^DATABASE_URL=' .env | cut -d= -f2-)
./venv/bin/alembic current
./venv/bin/alembic upgrade head
```

**Table-ownership gotcha:** the earliest tables (e.g. `users`) were created owned
by the `postgres` superuser, while later migrations created theirs as `crossfit`.
That mismatch makes `ALTER TABLE` migrations fail with
`must be owner of table users`. Fix once, as a superuser, before upgrading:

```bash
sudo -u postgres psql -d crossfit -f backend/scripts/transfer_table_ownership.sql
```

The script is idempotent and transfers all public tables/sequences/views to
`crossfit`.

## Updating to a new release

```bash
cd /opt/crossfit-health-os
# 1. backup DB + env
mkdir -p /opt/backups/crossfit-$(date +%F-%H%M%S) && cd "$_"
pg_dump "$DATABASE_URL" -Fc -f crossfit-db.dump
cp /opt/crossfit-health-os/backend/.env .

# 2. pull
cd /opt/crossfit-health-os && git pull

# 3. deps + migrations (run as / readable by crossfit)
cd backend
./venv/bin/pip install -r requirements.txt   # reinstalls -e ./cfai too
./venv/bin/alembic upgrade head

# 4. restart + verify
systemctl restart crossfit && curl -s http://127.0.0.1:8003/health
```

Gotchas when the **venv or code directory is moved** (e.g. swap-style deploys):

- The `cfai` package is an editable install (`-e ./cfai`); a moved tree leaves a
  stale `__editable__.cfai-*.pth` pointer — re-run `pip install -e ./cfai` at the
  final path.
- venv entry-point scripts (`uvicorn`, `alembic`) have absolute-path shebangs;
  after a move, rewrite them or rebuild the venv. `bin/python3` is an absolute
  symlink to the system interpreter and survives a move.

## Dependency notes

- **`bcrypt` is pinned `==4.3.0`.** `passlib 1.7.4` reads `bcrypt.__about__`, which
  `bcrypt>=5` removed; with bcrypt unpinned a fresh install pulls 5.x and every
  password hash/verify raises `ValueError` → login/registration 500.
- Static assets are cache-busted by mtime: templates link `…?v={{ asset_version() }}`,
  where `asset_version()` is the max mtime of files under `app/static`. Editing a
  static file is enough to bust browser caches on next load — no restart needed.

## Optional configuration (features dormant until set)

All have safe empty defaults, so the app boots without them.

| Env var(s) | Enables |
|------------|---------|
| `STRIPE_SECRET_KEY`, `STRIPE_PUBLIC_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID` | Billing endpoints |
| `INTERNAL_CRON_SECRET` | `POST /api/v1/internal/cron/weekly-reviews` (wire to an external scheduler) |
| `SMTP_HOST`, `SMTP_FROM`, … | Password-reset emails via `/api/v1/auth/forgot-password` (logs link if unset) |
| `GOOGLE_CALENDAR_CLIENT_ID`, `GOOGLE_CALENDAR_CLIENT_SECRET` | Google Calendar connect + sync (`/dashboard/integrations`) |

### Google Calendar OAuth

Set credentials in **`backend/.env`** (what systemd loads). Keys may also live in the
repo-root `.env`; the app backfills them into settings when `backend/.env` omits them.

1. [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services →
   Credentials → **OAuth 2.0 Client ID** (Web application).
2. Enable the **Google Calendar API** for the project.
3. **Authorized redirect URI** (must match `FRONTEND_URL` exactly):

   ```
   https://<your-domain>/auth/callback
   ```

   Example for this host: `https://crossfit.leicbit.com/auth/callback`

   The legacy API path `/api/v1/integrations/calendar/oauth/callback` still works
   if you register both URIs in Google Cloud Console.
4. Add to `backend/.env`:

   ```env
   GOOGLE_CALENDAR_CLIENT_ID=….apps.googleusercontent.com
   GOOGLE_CALENDAR_CLIENT_SECRET=….
   ```

5. `systemctl restart crossfit`

If credentials are missing or still placeholders (`your-client-id`), the connect
button returns **503** with `google_calendar_not_configured` instead of sending the
user to Google with an empty `client_id`.

**OAuth state store:** with **2 uvicorn workers** (`crossfit.service`), set a working
`REDIS_URL` in `backend/.env`. Without Redis, OAuth `state` nonces live in process
memory and callbacks can fail with `Invalid or expired state` when the redirect
hits the other worker.

Never commit `client_secret.json` or OAuth secrets — use `GOOGLE_CALENDAR_*` in
`backend/.env` only. If a JSON client file was ever added to the repo, rotate the
secret in Google Cloud Console.


Copy the unit files from `infra/systemd/` and enable the timer:

```bash
sudo cp infra/systemd/crossfit-weekly-reviews.{service,timer} /etc/systemd/system/
# Ensure INTERNAL_CRON_SECRET is set in backend/.env
sudo systemctl daemon-reload
sudo systemctl enable --now crossfit-weekly-reviews.timer
systemctl list-timers crossfit-weekly-reviews.timer
```

Manual trigger (for testing):

```bash
curl -X POST -H "X-Internal-Cron-Secret: $INTERNAL_CRON_SECRET" \
  http://127.0.0.1:8003/api/v1/internal/cron/weekly-reviews
```

### Password reset email (SMTP)

When `SMTP_HOST` and `SMTP_FROM` are set in `backend/.env`, forgot-password sends
a real email. Otherwise the reset URL is written to the app log (dev-friendly).

Example (typical STARTTLS on port 587):

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=noreply@example.com
SMTP_PASSWORD=your-app-password
SMTP_FROM="CrossFit Health OS <noreply@example.com>"
SMTP_USE_TLS=true
SMTP_USE_SSL=false
```

Quote values that contain spaces in `.env` (e.g. `APP_NAME="CrossFit Health OS"`).
| `APP_DOMAIN`, `APP_SCHEME`, `SUPPORT_EMAIL`, `DPO_EMAIL` | Absolute URLs / legal pages |

## Rollback

Keep the previous code dir and DB dump from the update step. To roll back:

```bash
systemctl stop crossfit
git -C /opt/crossfit-health-os checkout <previous-sha>   # or restore the saved dir
# additive migrations (new columns/tables) are backward-compatible with older code,
# so a DB rollback is usually unnecessary; restore from the pg_dump only if needed.
systemctl start crossfit
```
