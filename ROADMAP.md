# Product Roadmap (post-stabilization)

## Platform decisions

- **Celery:** Not implemented. Production uses HTTP cron (`POST /api/v1/internal/cron/weekly-reviews`) via systemd timer — simpler ops, sufficient for weekly jobs.
- **Frontend:** SSR Jinja2 + `chos.js` (no Next.js migration planned short-term).
- **Mobile HealthKit:** Backend API + companion SwiftUI app in `ios/` (Xcode build required on device).

## Near-term backlog

| Item | Status | Notes |
|------|--------|-------|
| Stripe billing | Placeholder | Set `STRIPE_*` env vars + webhook handler |
| PWA offline cache | Partial | `manifest.json` + minimal SW registered |
| Wearables (Whoop/Oura) | Not started | New integration modules |
| Redis template cache | Not started | Cache workout templates |
| Email SMTP | Infra ready | Wire `SMTP_*` in prod; forgot-password sends mail when configured |
| iOS HealthKit app | Source in repo | Build via Xcode; see `ios/README.md` |

## Completed in this release cycle

- Auth: JWT local forgot/reset password, SQLAlchemy user creation
- Adaptive engine: force_rest, template difficulty mapping, shared readiness
- HealthKit: sleep_quality + readiness persistence
- SSR: biomarkers upload, PRs, calendar integrations page, notifications read
- Infra: real `/health`, systemd weekly-review timer, Alembic-aligned docker-compose
- iOS: SwiftUI HealthKit companion (`ios/`) + `docs/healthkit_integration.md`
