# REST API v1

**English** · [فارسی](../fa/api/rest.md)

Base path `/api/v1`. Interactive docs at `/api/docs`, machine-readable schema at `/api/v1/openapi.json`.

## Conventions

* **Auth.** Servers: `Authorization: Bearer wtx_key_...` (key bound to one org and role). Dashboard:
  httpOnly session cookie + `X-Waltrix-Organization: <org id>` + `X-Requested-With: waltrix-web` on writes.
* **Money.** `{"amount": 1250, "currency": "USD"}`. `amount` is a positive JSON integer in minor units,
  ≤ 2^53−1. `10.5`, `"10"` and `true` are rejected (422).
* **Idempotency.** Required on every money-moving route: `Idempotency-Key: <1-255 printable chars>`.
  Replays carry `Idempotent-Replayed: true`.
* **Correlation.** Send `X-Correlation-ID` (`[A-Za-z0-9._-]{1,64}`) or receive a generated one; it is in
  every response, log line, audit event, transaction and journal entry.
* **Pagination.** Cursor based: `?limit=1..100&cursor=...` →
  `{"data": [...], "next_cursor": "...", "has_more": true}`. Stable while rows are being inserted.
* **Language.** Responses and messages are English. Clients localise by the stable error `code`, not the
  `message` text; the dashboard does exactly this for Persian.
* **Errors.**

```json
{"error": {"code": "insufficient_funds", "message": "insufficient available balance",
           "details": {"transaction_id": "0b9e..."}, "correlation_id": "4f2c..."}}
```

| Status | Codes |
| --- | --- |
| 400 | `organization_required` |
| 401 | `authentication_failed` |
| 403 | `permission_denied`, `csrf_failed`, `user_session_required` |
| 404 | `not_found` (also for other tenants' resources) |
| 409 | `idempotency_key_reused`, `concurrent_request`, `invalid_state_transition`, `conflict` |
| 422 | `validation_failed`; business: `insufficient_funds`, `wallet_not_active`, `currency_mismatch`, `same_wallet`, `hold_not_active`, `hold_expired`, `capture_exceeds_hold`, `not_reversible`, `reversal_exceeds_remaining` |
| 429 | `rate_limited` (+ `Retry-After`) |
| 500 | `internal_error` (no internals leaked) |

## Endpoints

| Method & path | Permission | Notes |
| --- | --- | --- |
| `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` | - | dashboard sessions |
| `GET/POST /organizations` | user session | list memberships / create (caller becomes owner) |
| `GET/PATCH /organizations/current` | read / `org:manage` | |
| `GET/POST /organizations/current/members`, `PATCH/DELETE .../{id}` | `members:read` / `members:manage` | cannot grant above own role; last owner protected |
| `GET/POST /api-keys`, `POST /api-keys/{id}/revoke`, `POST /api-keys/{id}/rotate` | `api_keys:manage` (user only) | secret returned once |
| `GET/POST /wallets`, `GET /wallets/{id}`, `GET /wallets/{id}/balance` | `wallets:read` / `wallets:manage` | filters: `status`, `currency`, `search` |
| `POST /wallets/{id}/suspend` · `/activate` · `/close` | `wallets:manage` | |
| `POST /wallets/{id}/credit` · `/debit` | `money:fund` | **simulated** funding source, Idempotency-Key |
| `GET /wallets/{id}/statement` | `ledger:read` | running balance from postings, `start`/`end` |
| `POST /transfers`, `GET /transfers/{id}` | `money:move` | Idempotency-Key |
| `GET /transactions`, `GET /transactions/{id}` | `ledger:read` | filters: `status`, `type`, `wallet_id`, `currency`, `created_after/before`, `search`, `sort` |
| `GET/POST /holds`, `GET /holds/{id}`, `POST /holds/{id}/capture` · `/release` | `money:move` | Idempotency-Key |
| `POST /reversals` | `money:reverse` | full or partial (`amount`) |
| `GET /accounts`, `POST /accounts`, `GET /accounts/{id}`, `GET /accounts/{id}/statement` | `ledger:read` / `accounts:manage` | internal accounts only via POST |
| `GET /journal-entries`, `GET /journal-entries/{id}` | `ledger:read` | filters: `kind`, `phase`, `account_id` |
| `POST /journal-entries` | `ledger:manual_entry` | balanced, internal non-wallet accounts only |
| `POST/GET /reconciliation/runs`, `GET /reconciliation/runs/{id}` | `reconciliation:run` / `:read` | |
| `GET /audit-events` | `audit:read` | filters: `action` prefix, `target_id`, `actor_id` |
| `GET /overview` | `ledger:read` | dashboard metrics from real rows |
| `GET /currencies` | - | supported codes and exponents |
| `GET /healthz`, `GET /readyz`, `GET /metrics` | - | liveness, readiness (DB + migration), Prometheus |

There are no generic CRUD endpoints for financial data: balances change only through the operations above.

## Examples

```bash
KEY=wtx_key_...   # from `waltrix seed-demo` or the dashboard
curl -s -X POST http://127.0.0.1:4820/api/v1/transfers \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -H "Idempotency-Key: order-81-payment" \
  -d '{"source_wallet_id":"<uuid>","destination_wallet_id":"<uuid>","amount":1250,"currency":"USD"}'
```

```json
{"id": "9cd10db6-...", "type": "transfer", "status": "posted", "amount": 1250, "posted_amount": 1250,
 "reversed_amount": 0, "currency": "USD", "source_wallet_id": "...", "destination_wallet_id": "...",
 "correlation_id": "4f2c...", "created_at": "2026-11-19T15:01:12.117Z", "posted_at": "2026-11-19T15:01:12.117Z", ...}
```

Sending the same request again returns the same body with `Idempotent-Replayed: true`. Changing the
amount with the same key returns `409 idempotency_key_reused`.
