# Chapter 12 — Operations and deployment

**English** · [فارسی](../12-operations.md)

Files for this chapter: `apps/api/src/waltrix_api/{observability,ratelimit,cli}.py`, `routers/operations.py` (health), `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml`, [deployment.md](../../deployment.md)

## 1. The correlation id: the thread through everything

`RequestContextMiddleware` creates a `correlation_id` for every request (or takes the client's `X-Correlation-ID` if it is valid) and puts it in a `ContextVar`. The same id appears in:

- every JSON log line
- the response header
- the body of every error
- the audit event
- the transaction row and the journal entry

So from a customer complaint ("I saw this error: 4f2c...") you go straight to the log, the audit event and the financial entry of that request. The incoming id is restricted by the regex `^[A-Za-z0-9._-]{1,64}$`; otherwise a client could inject arbitrary text (even HTML) into the logs (`test_correlation_id_propagates`).

## 2. A pure ASGI middleware

The middleware is not written with `BaseHTTPMiddleware` but as pure ASGI (`__call__(scope, receive, send)`). The reasons: it is simpler, it has no problems with streaming, and it keeps the `ContextVar` correctly scoped to the request. Wrapping `send` captures the response status and adds the security headers.

## 3. Metrics

```python
OPERATIONS = Counter("waltrix_financial_operations_total", "...", ["operation", "outcome"])
OPERATION_LATENCY = Histogram("waltrix_financial_operation_duration_seconds", "...", ["operation"])
```

An architectural point: the core (`waltrix_core`) does not depend on prometheus. `runner.py` has an `OBSERVERS` list and the API registers a function in it. If an observer fails, it is only logged:

```python
except Exception:  # observers must never break money movement
```

**Lesson:** observability must never be able to break the main operation.

The `route` label is the path pattern (`/api/v1/wallets/{wallet_id}`), not the real path. If the real id were a label, every wallet would create a new time series and Prometheus would blow up (a cardinality explosion).

## 4. Liveness versus readiness

| Probe | Question | What it checks |
| --- | --- | --- |
| `/healthz` | Is the process alive? | nothing; it just answers |
| `/readyz` | Can it take traffic? | the database answers **and** migrations are applied |

If liveness also checked the database, a short database outage would make Kubernetes restart every pod and make things worse. Readiness only takes the pod out of the load balancer.

## 5. Background work without Celery

| Command | Job | Why it is safe to run several at once |
| --- | --- | --- |
| `waltrix expire-holds` | expire holds | `SKIP LOCKED`, one transaction per hold |
| `waltrix purge-idempotency` | delete expired keys | a conditional DELETE |
| `waltrix reconcile` | reconcile every organization | read-only; a non-zero exit code means a problem |

All three are idempotent; a cron job or a simple loop (`worker` in compose) is enough. A message queue is needed when you have long, distributed or event-driven work.

## 6. Running behind a proxy with a path prefix

On the shared server, the preview opens at an address like `/shared/ide/proxy/4820/` and the proxy **strips** the prefix. Three things must know the prefix:

1. Vite assets: `VITE_BASE=/shared/ide/proxy/4820/` at build time.
2. React Router: `basename={import.meta.env.BASE_URL}`.
3. The cookie: `WALTRIX_SESSION_COOKIE_PATH=/shared/ide/proxy/4820/api`, because the browser sees the **public** path.

And the API can serve the dashboard build itself (`WALTRIX_WEB_DIST`) so that everything is one origin: no CORS, a simple cookie.

## 7. Docker and CI

The `Dockerfile` is multi-stage: a Node stage builds the dashboard, and the Python stage copies only the result. It runs as a non-root user with a `HEALTHCHECK` on `/readyz`. Honestly: Docker was not available in this project's development environment, and these files are only built in CI.

CI has four jobs: Python on PostgreSQL 16 and 17 (a matrix), Node (lint, typecheck, i18n check, tests, build), Playwright, and the Docker image build.

## 8. Backups, RPO and RTO

- **RPO** (how much data we can lose): with WAL archiving, as much as the WAL shipping delay; zero only with synchronous replication.
- **RTO** (how long it takes to come back): the time to restore and replay WAL.
- After a restore, and **before** opening traffic, `waltrix reconcile` must be green.
- A nice detail: clients that kept their idempotency keys can safely resend any requests lost after the recovery point.

## Exercises

1. Run the API, make a few transfers and look at `curl localhost:4820/metrics | grep financial`. Make a failing transfer and find the counter change.
2. Write a new observer that logs a warning for operations slower than 500 ms. Register it in `create_app`.
3. Back up the dev database with `pg_dump`, restore it into a new database, and run `waltrix reconcile` against it.
4. Build the dashboard with the right `VITE_BASE` and open it from the shared server's preview address. If sign-in does not work, use DevTools to see which path the cookie was set with.
