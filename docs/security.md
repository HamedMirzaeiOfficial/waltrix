# Security model

Waltrix is an educational, open-source project. It has **not** been independently audited and makes no
claim of regulatory compliance (PCI DSS, SOC 2, banking licenses). The controls below are what the code
actually does.

## Tenancy

* Every tenant-owned row carries `org_id`, and every service query filters by the actor's `org_id`.
* The actor's org and role come from the server: an API key row, or the user's membership for the org
  named in `X-Waltrix-Organization` (verified on every request). Client-supplied ownership is never trusted.
* Resources of another tenant return `404 not_found`, identical to a random UUID (no existence oracle).
  IDs are random UUIDv4, not sequential.
* Composite foreign keys `(id, org_id)` make cross-tenant references impossible at the schema level, e.g.
  a posting cannot reference another org's account even through raw SQL.

## Authentication

| Credential | Storage | Lifetime | Notes |
| --- | --- | --- | --- |
| Password | scrypt (n=2^14, r=8, p=1, 16-byte salt) | - | min 10 chars; unknown emails still run scrypt against a dummy hash (timing) and get the same error |
| Session | SHA-256 of a 256-bit token | 12 h, revocable | httpOnly, `SameSite=Strict`, `Secure` in production, path-scoped |
| API key | SHA-256 of a 256-bit secret + public prefix | optional expiry | shown once; `last_used_at` tracked |

**CSRF.** Cookie-authenticated writes also require `X-Requested-With: waltrix-web`. Browsers cannot send a
custom header cross-site without a CORS preflight, and CORS only allows the explicit `WALTRIX_CORS_ORIGINS`
list (never `*` with credentials; empty by default = same-origin only).

## Authorization

Role → permission bundles in `permissions.py`; code checks permissions, never role names.

| Permission | Owner | Admin | Finance operator | Auditor | Viewer |
| --- | :-: | :-: | :-: | :-: | :-: |
| read wallets / ledger | ✓ | ✓ | ✓ | ✓ | ✓ |
| manage wallets, move money, fund, reverse | ✓ | ✓ | ✓ | | |
| reconciliation read | ✓ | ✓ | ✓ | ✓ | |
| reconciliation run, audit log | ✓ | ✓ | | ✓ | |
| manual entries, internal accounts | ✓ | ✓ | | | |
| members, API keys | ✓ | ✓ | | | |
| organization settings | ✓ | | | | |

API keys can only hold finance operator, auditor or viewer roles, and key/member management endpoints
require a user session, so a leaked key cannot mint more keys. Members cannot grant a role above their
own, and the last owner cannot be removed or demoted (memberships are locked during the check).

## API key rotation guidance

1. Create the replacement (`POST /api-keys/{id}/rotate` with `grace_hours` > 0 for zero downtime).
2. Deploy the new secret to your secret manager and services.
3. Watch `last_used_at` of the old key; it stops working when the grace period ends (or immediately with 0).
4. Rotate immediately when a person with access leaves or a key appears in logs or a repository.

## Input and abuse protection

* Pydantic models with `extra="forbid"`, `StrictInt` amounts, length limits; server-side validation is
  authoritative (the UI validates for ergonomics only).
* Rate limits: per credential (default 600/min) and per IP + per email for login/registration (10/min).
  In-process: with several API replicas, each enforces its own window. `X-Forwarded-For` is honored only
  for `WALTRIX_TRUSTED_PROXY_COUNT` trusted hops.
* Security headers on every response: `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
  `Cache-Control: no-store`.

## Secrets and logging

* No secrets in the repository; configuration via `WALTRIX_*` env vars (`.env` is gitignored).
* Logs are JSON lines with method, route template, status, duration and correlation id: no bodies,
  headers, tokens or passwords. Audit metadata is scrubbed of keys like `password`, `secret`, `token`.
* Unexpected errors return a generic 500; details stay in logs under the correlation id.

## Database hardening (recommended for any real deployment)

* Run migrations with an owner role; run the API with a role that has only `SELECT, INSERT, UPDATE` on the
  needed tables and does **not** own them (so it cannot `TRUNCATE` or disable triggers).
* TLS to PostgreSQL, encrypted backups, restricted network access.

## Known gaps

No MFA, no SSO, no password reset flow, no email verification, no per-key IP allow-lists, no field-level
encryption, in-memory rate limiting. See the README roadmap.
