# ADR 0004: Idempotency records commit with the financial result

**Status:** accepted

**Decision.** The idempotency record is inserted (`ON CONFLICT DO NOTHING`) at the start of the operation's
database transaction and completed at the end of it. Therefore it exists if and only if the outcome was
committed. A concurrent request with the same key blocks on the unique index until the first commits or
rolls back, then replays or proceeds. Deterministic business failures are stored and replayed; crashes and
unexpected errors roll everything back and leave the key free.

**Rejected.** A separate "IN_PROGRESS" record committed before the work. It needs timeouts, recovery of
orphaned records, and a second state machine; it also opens a window where the record says "done" but the
money write failed (or vice versa).

**Trade-off.** A duplicate in-flight request holds a database connection while it waits (bounded by
`lock_timeout`). Replays return the *current* state of the original resource, not a byte-identical copy of
the first response.
