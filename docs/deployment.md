# Deployment and operations

## Shape

One container image (`Dockerfile`): the FastAPI app serving the API and the built dashboard from the same
origin, plus the same image run as a maintenance worker. PostgreSQL is the only stateful dependency.

```bash
docker compose up --build          # db + migrate + api (127.0.0.1:8080) + worker
docker compose run --rm api waltrix seed-demo   # optional synthetic data
```

> The Dockerfile and Compose file are provided and built in CI, but were **not executed in the development
> environment of this repository** (no Docker available there). The non-Docker path below is what was
> exercised end to end.

## Without Docker

```bash
scripts/dev-db.sh                                   # private PostgreSQL on 127.0.0.1:4822
python -m venv .venv && .venv/bin/pip install -e packages/ledger-core -e "apps/api[dev]" -e packages/python-sdk
npm ci && npm run build -w @waltrix/sdk && npm run build -w @waltrix/web
export WALTRIX_DATABASE_URL=postgresql://waltrix@127.0.0.1:4822/waltrix
.venv/bin/waltrix migrate
WALTRIX_WEB_DIST=apps/web/dist .venv/bin/waltrix serve --port 4820
```

Behind a reverse proxy that serves the app under a path prefix (`/some/prefix/`), build the web app with
`VITE_BASE=/some/prefix/` and set `WALTRIX_SESSION_COOKIE_PATH=/some/prefix/api` and
`WALTRIX_COOKIE_SECURE=true`.

## Production checklist

* `WALTRIX_ENVIRONMENT=production` (forces `Secure` cookies), HTTPS only, `WALTRIX_TRUSTED_PROXY_COUNT`
  set to the real number of proxies.
* Separate DB roles for migrations (owner) and runtime (DML only). TLS to the database.
* Run `waltrix migrate` as a one-off job before starting new API versions (migrations are forward-only in
  production; `downgrade` exists for development).
* Schedule `waltrix expire-holds` (every minute), `waltrix purge-idempotency` (hourly) and
  `waltrix reconcile` (hourly or nightly; exits non-zero on findings → alert).
* Scrape `/metrics`; probe `/healthz` (liveness) and `/readyz` (DB reachable + schema applied).

## Observability

| Signal | Where |
| --- | --- |
| JSON access logs with correlation id, route template, status, duration | stdout |
| `waltrix_http_requests_total`, `waltrix_http_request_duration_seconds` | `/metrics` |
| `waltrix_financial_operations_total{operation,outcome}` (succeeded, failed, replayed, error) | `/metrics` |
| `waltrix_financial_operation_duration_seconds{operation}` (time inside the DB transaction) | `/metrics` |
| `waltrix_financial_operation_failures_total{operation,kind}` | `/metrics` |
| `waltrix_reconciliation_last_errors` | `/metrics` (set by API-triggered runs) |
| Who did what | `audit_events` table / `GET /audit-events` |

Background jobs are plain idempotent commands; their visibility is their exit code, log lines, audit
events (hold expiry, reconciliation) and the `overdue_hold` reconciliation warning if expiry lags.
Metrics are per process (Prometheus aggregates across replicas).

## Backup and restore

* **Backups:** continuous WAL archiving + periodic base backups (e.g. pgBackRest, or a managed
  database's point-in-time recovery). Logical `pg_dump` is fine for small installations and tests.
* **RPO:** equals your WAL shipping lag (seconds with streaming/archiving, zero only with synchronous
  replication). **RTO:** time to restore the base backup and replay WAL.
* **Restore procedure:** restore to a new instance → `waltrix migrate` (no-op if current) → run
  `waltrix reconcile` and require it to pass → switch traffic. Transactions committed after the recovery
  point are lost; clients that still hold their idempotency keys can safely re-submit them.
* **Test restores** regularly; a backup that was never restored is a hope, not a backup.
