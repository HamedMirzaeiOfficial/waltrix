# Chapter 5 — Idempotency: safe repetition

**English** · [فارسی](../05-idempotency.md)

Files for this chapter: `services/idempotency.py`, `services/runner.py`, `apps/api/src/waltrix_api/deps.py::idempotency_key`, `packages/*-sdk`, [ADR 0004](../../architecture/decisions/0004-idempotency-in-the-same-transaction.md)

## 1. The problem: "the response did not arrive"

A client sends a transfer request. The network drops and no response arrives. Did the server move the money? **The client does not know.**

- If it sends again, the money may move twice.
- If it does not, the transfer may never have happened and the customer keeps waiting.

No network protocol guarantees "exactly-once delivery". What we can guarantee is this: **executing a request with a given key has an effect at most once**, and the client can always learn the outcome by repeating it.

## 2. Waltrix's rules

| Rule | Implementation |
| --- | --- |
| A key is scoped to (organization, operation, key) | `UniqueConstraint("org_id", "operation", "key")` |
| A fingerprint of the parameters | `fingerprint()`: SHA-256 of sorted JSON |
| Same key + same parameters → the original outcome | replayed with the header `Idempotent-Replayed: true` |
| Same key + different parameters → conflict | `409 idempotency_key_reused` |
| A business failure is stored and replayed | `outcome="failed"` + the id of the FAILED transaction |
| A crash or unexpected error → the key stays free | because the whole transaction rolls back |
| Required by the API | `Header(alias="Idempotency-Key")` with no default |

## 3. The core idea: the idempotency record in the **same** transaction

The naive approach:

```
1. create an IN_PROGRESS record and commit
2. move the money and commit
3. mark the record DONE and commit
```

The process may die between any two steps: an IN_PROGRESS record is orphaned (how long do we wait?), or the money moved but the record was never marked DONE (a retry moves it again!). Three commits mean three points of failure.

Waltrix's approach:

```python
with session.begin():
    record, stored = idempotency.claim(...)   # INSERT ... ON CONFLICT DO NOTHING
    ... move the money ...
    idempotency.complete(record, ...)
# one COMMIT
```

The record exists **if and only if** the financial outcome was committed. An "in progress" state is never visible after a commit, so there is no need for timeouts or for recovering orphaned records.

## 4. Concurrent duplicate requests

Two requests with the same key arrive at the same time. Both run `INSERT ... ON CONFLICT DO NOTHING`. What happens?

To protect the unique index, PostgreSQL makes the second `INSERT` **wait** until the first transaction ends:

- If the first commits, the second `INSERT` does nothing, `RETURNING` is empty, and we read the committed record and replay it.
- If the first rolls back, the second `INSERT` succeeds and this request becomes the "first writer".

So without any manual lock, the unique index itself forms a queue. `test_same_idempotency_key_concurrently_executes_once`: 25 concurrent requests, exactly one execution, 24 replays, all with the same id.

## 5. Why store a business failure?

Suppose a transfer failed with `insufficient_funds`. The customer then topped up the account, and the client repeated the same request with the **same key**. Should it succeed now?

Waltrix (like Stripe) says **no**: the same earlier failure comes back. A key means "this is the same request", and that request definitely failed. If the user really wants a "new attempt", a new key is needed. This rule is tested: `test_6_business_failure_is_replayed_not_rerun`.

## 6. On the client side: the key is created once

In the Python SDK (`_endpoints.py`):

```python
def create_transfer(..., idempotency_key: str | None = None) -> Spec[Transaction]:
    return Spec("POST", "/transfers", body, idempotency_key=_key(idempotency_key))
```

If no key is given, `_key` creates a UUID **once**; every retry of that call sends the same key. It is better, though, to derive the key from your own domain (`f"{order_id}:capture"`), so it stays the same even after a process restart.

### Three kinds of outcome, not two

| Outcome | Python SDK | TypeScript SDK |
| --- | --- | --- |
| Definite success | the return value | the return value |
| Definite failure | `OperationFailedError` | `WaltrixApiError.isBusinessFailure` |
| **Unknown** | `UnknownOutcomeError(idempotency_key=...)` | `WaltrixUnknownOutcomeError` |

The "unknown" error is the most important design decision in the SDKs. Most libraries report a timeout as a failure, and the programmer assumes "the money did not move". Here the error explicitly says "maybe" and hands you the key for a safe repeat. Even a user cancellation (`AbortSignal`) after sending counts as "unknown" for a mutation.

### Which requests are retried

Only GETs and POSTs that carry a key, and only on timeouts, connection errors, 429, 502/503/504 and `409 concurrent_request`. A POST without a key (such as running reconciliation) is **never** retried automatically. Test: `test_post_without_idempotency_key_is_never_retried`.

## Exercises

1. Send a transfer with `curl`, then send the same one again and look at the `Idempotent-Replayed` header. Then change the amount. What is the response?
2. In `claim`, remove the `existing.fingerprint != fp` condition. Which test breaks? What attack or bug does this condition prevent?
3. Design it: if a replay had to return **the exact bytes of the first response** (not the current state), what would have to be stored, and at what cost?
4. Why must an idempotency key be scoped to the organization? Write a scenario where, without that, one tenant sees another tenant's outcome.
