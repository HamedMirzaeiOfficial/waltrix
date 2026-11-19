# Chapter 8 — Security and multi-tenancy

**English** · [فارسی](../08-security-and-tenancy.md)

Files for this chapter: `apps/api/src/waltrix_api/deps.py`, `services/identity.py`, `permissions.py`, `services/queries.py`, `apps/api/tests/test_api.py`, [security.md](../../security.md)

## 1. The golden rule: do not trust the identity the client claims

The dashboard client sends the header `X-Waltrix-Organization: <id>`. If the server simply accepted it, any user could write another organization's id. In `deps.py::current_actor`:

```python
actor = identity.actor_for_user(db, creds.user, org_id, correlation_id(request))
```

`actor_for_user` looks up the user's membership **in the database** and reads the role from there too. The header is only a "selection", not a "claim of permission". For an API key, the organization header is ignored entirely, because the key is bound to one organization (`test_api_key_is_bound_to_its_org`).

## 2. Data isolation at three levels

1. **Queries:** every function in `queries.py` and `operations.py` filters on `org_id == actor.org_id`.
2. **Schema:** the composite `(id, org_id)` foreign keys (chapter 3).
3. **Responses:** another organization's resource gets the same "not found" response as a random UUID.

The third matters: if you return `403` for other people's resources and `404` for missing ones, an attacker can learn which ids exist by trying them (**enumeration**). `test_cross_tenant_access_is_404` compares both the status code and the message of the two cases. Ids are random UUIDs too, not sequential numbers.

## 3. Roles and permissions

```python
class Permission(StrEnum):
    MONEY_MOVE = "money:move"
    AUDIT_READ = "audit:read"
    ...
ROLE_PERMISSIONS = {Role.OWNER: frozenset(Permission), Role.VIEWER: frozenset(_READ), ...}
```

Nowhere does the code write `if role == "admin"`; it always writes `actor.require(Permission.MONEY_MOVE)`. Roles are just bundles of permissions and can change without touching the code.

The permission check lives **inside the core**, not only in the API. So a host application calling `operations.transfer` directly still cannot move money with a viewer `Actor` (`test_8_permissions_enforced_in_engine`).

### Preventing privilege escalation

- Nobody can grant a role higher than their own (`ROLE_RANK`).
- The last owner cannot be removed or demoted; and to keep that check correct under concurrency, all memberships of the organization are locked (`_lock_membership`). Without the lock, two owners could demote each other at the same time and leave the organization ownerless.
- An API key can only have the finance_operator, auditor or viewer role, and the key and member management endpoints require a user session. So a leaked key cannot create new keys.

## 4. Passwords, sessions and API keys

| | Stored as | Why |
| --- | --- | --- |
| Password | scrypt with a random salt | deliberately slow; passwords have little entropy |
| Session token | SHA-256 | the token has 256 bits of entropy; a slow hash adds nothing |
| API key | SHA-256 + a public prefix | the prefix is for display in the UI and logs; the secret is shown only once |

**Login timing:** if a missing email were answered instantly while an existing one ran scrypt (slow), an attacker could tell from the **response time** which emails are registered. For a missing email `login` still runs scrypt against a dummy hash, and the error message is identical in both cases (`test_login_failure_is_generic`).

## 5. CSRF with a SameSite cookie and a custom header

The dashboard authenticates with an httpOnly cookie (JavaScript cannot read the token, so XSS cannot steal it). The danger of cookies is CSRF: another site builds a form that POSTs to our API and the browser attaches the cookie automatically. Two defences:

1. `SameSite=Strict`: the browser does not send the cookie on cross-site requests.
2. Writing with a cookie requires the header `X-Requested-With: waltrix-web`. A browser does not let another site send a custom header without a CORS preflight, and our CORS only accepts explicitly listed origins (none by default).

## 6. Small things that matter

- `extra="forbid"` in Pydantic: a `balance` field in a create-wallet request is rejected (`test_unknown_fields_rejected`).
- `StrictInt` for amounts: `"100"`, `true` and `10.5` all get 422.
- A separate rate limit for login (per IP and per email).
- `X-Forwarded-For` is trusted only up to `TRUSTED_PROXY_COUNT`; otherwise anyone could write a fake IP and escape the rate limit.
- Logs do not record bodies or headers; the route is logged as a pattern (`/wallets/{wallet_id}`), not the real id.

## 7. What we do not claim

There is no MFA, SSO, password recovery or email verification, and the project has not had an independent security audit. Writing down honestly "what is not there" is part of security documentation.

## Exercises

1. With an API key from organization A, use `curl` to try to read a wallet of organization B and to transfer to it. Send the `X-Waltrix-Organization` header too. Explain the result.
2. Temporarily remove the `X-Requested-With` check in `deps.py`. Which test breaks? Write a simple HTML page that demonstrates the CSRF attack (then put the check back).
3. Measure the response time of `/auth/login` 20 times for an existing and a missing email. Is there a meaningful difference? Then remove `_DUMMY_HASH` and measure again.
