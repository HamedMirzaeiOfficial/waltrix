# ADR 0004: Idempotency records commit with the financial result

**English** · [فارسی](../../fa/architecture/decisions/0004-idempotency-in-the-same-transaction.md)

**Status:** accepted

**Context.** Networks lose responses. A client that did not get an answer cannot tell "not done" from
"done, but the reply was lost", so it must be able to retry safely. That requires the server to recognise
a retry and return the original outcome, and the record that makes this possible must never disagree with
whether money actually moved.

**Decision.** The idempotency record is inserted (`ON CONFLICT DO NOTHING`) at the start of the operation's
database transaction and completed at the end of it. Therefore it exists if and only if the outcome was
committed. A concurrent request with the same key blocks on the unique index until the first commits or
rolls back, then replays or proceeds. The key is scoped to `(organization, operation, key)` and stored with
a SHA-256 fingerprint of the parameters; the same key with different parameters is a `409`. Deterministic
business failures are stored and replayed; crashes and unexpected errors roll everything back and leave
the key free.

**Rejected.** A separate "IN_PROGRESS" record committed before the work. It needs timeouts, recovery of
orphaned records, and a second state machine; it also opens a window where the record says "done" but the
money write failed (or vice versa). An external store (Redis) has the same two-writes problem.

**Trade-off.** A duplicate in-flight request holds a database connection while it waits (bounded by
`lock_timeout`). Replays return the *current* state of the original resource, not a byte-identical copy of
the first response.

**Consequences.** Clients can treat any timeout as "unknown" and retry with the same key; the SDKs and the
dashboard do exactly that. Records are kept for 24 hours (`waltrix purge-idempotency`), so a retry must
happen within that window.
