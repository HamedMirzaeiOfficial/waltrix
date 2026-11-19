# ADR 0003: READ COMMITTED + deterministic row locks (not SERIALIZABLE)

**Status:** accepted

**Context.** Concurrent debits of one wallet must never overspend; concurrent transfers A->B and B->A must
not deadlock.

**Decision.** Run at READ COMMITTED. Inside each operation lock rows explicitly, always in one global order:
idempotency key -> transaction/hold row -> wallets (`FOR SHARE`, by id) -> accounts (`FOR UPDATE`, by id).
Check balances *after* the locks are granted (`populate_existing`). Back this with database constraints
(`no_overdraft` CHECK, composite FKs, deferred balance triggers) so a missed lock is caught as an error,
not committed as bad data. `lock_timeout` turns pathological waits into a retryable `409 concurrent_request`.

**Alternatives.** SERIALIZABLE gives the same safety with less explicit code, but every hot wallet becomes a
stream of serialization failures that all clients must retry, and correctness depends on every caller
retrying properly. Optimistic version columns have the same retry problem. Explicit locks make waiting,
not failing, the normal behavior under contention.

**Consequences.** Operations on the same account are serialized (throughput per hot account is bounded
by transaction latency). The simulated funding account is a hot row for deposits; a production system
would shard it per currency/partition. Measured behavior is covered by `tests/concurrency`.
