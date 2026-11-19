# Concurrency, idempotency and failure recovery

**English** · [فارسی](fa/concurrency.md)

## The transaction boundary

Every financial mutation is one call to `runner.run_operation`, which owns one PostgreSQL transaction:

```
BEGIN (READ COMMITTED)
  SET LOCAL lock_timeout = '5s'
  claim idempotency key              -- INSERT ... ON CONFLICT DO NOTHING
  SAVEPOINT
    lock rows in global order, validate, insert entry + postings, update balances
  on BusinessRuleViolation: ROLLBACK TO SAVEPOINT, insert FAILED transaction
  complete idempotency record
COMMIT                                -- deferred triggers re-check every entry balances
```

Partial commits are impossible: there is a single COMMIT. A process crash at any point before it leaves
nothing behind (PostgreSQL rolls back the open transaction when the connection drops).

## Lock order (deadlock freedom)

```
idempotency key  →  transaction / hold row  →  wallets FOR SHARE (by id)  →  accounts FOR UPDATE (by id)
```

* Accounts are sorted by id before `SELECT ... FOR UPDATE`, so A→B and B→A both lock `min(A, B)` first;
  one simply waits. `test_opposite_transfers_do_not_deadlock` runs 40 such transfers at once.
* Wallets use `FOR SHARE`: concurrent transfers do not block each other on the wallet row, but a status
  change (`FOR UPDATE`) waits for in-flight movements, so a wallet cannot be suspended mid-transfer.
* Balances are read after the lock is granted (`populate_existing=True`), so the overdraft check always
  sees the latest committed value.

## Scenario table

| Scenario | What happens | Proven by |
| --- | --- | --- |
| 40 concurrent 100.00 debits on a 1 000.00 wallet | exactly 10 succeed, 30 fail `insufficient_funds`, balance 0 | `test_concurrent_debits_cannot_overspend` |
| Holds and transfers racing for the same funds | `floor(1000/150) = 6` succeed, available never negative | `test_concurrent_holds_and_transfers_respect_available` |
| 25 requests with the same Idempotency-Key | 1 executes, 24 replay the same transaction | `test_same_idempotency_key_concurrently_executes_once` |
| Capture vs. release of the same hold | exactly one wins per hold | `test_capture_and_release_race_has_one_winner` |
| 6 expiry workers in parallel | each hold expires once | `test_parallel_expiry_workers_never_double_release` |
| 12 concurrent partial refunds of 100 on a 500 transfer | exactly 5 succeed | `test_reversal_race_cannot_double_refund` |
| Process "dies" after postings were flushed | nothing committed; retry with the same key succeeds once | `test_3_failure_mid_operation_commits_nothing` |
| 16 threads × 30 random ops on 6 overlapping wallets, each transfer retried | money conserved, no negatives, reconciliation passes | `test_stress_random_operations_preserve_invariants` |

Example output of the last test from a local run (numbers vary with randomness and timing):
`stress: {'succeeded': 455, 'failed': 11} external={'in': 16093, 'out': 13486} entries={'entries': 439, ...}`.
This is a correctness test, not a benchmark; no throughput claims are made.

## Idempotency rules

* Scope: `(organization, operation, key)`. The same key on `transfer.create` and `wallet.credit` are
  independent.
* Fingerprint: SHA-256 of the canonical JSON of the operation name and its validated parameters.
  Same key + same fingerprint → replay. Same key + different fingerprint → `409 idempotency_key_reused`.
* Concurrency: the second INSERT on the unique index waits for the first transaction. If that commits,
  ours does nothing and we replay; if it rolls back, ours proceeds as the first writer.
* Outcomes stored: success (resource reference) and deterministic business failures (error code and the
  FAILED transaction id). Not stored: validation errors, auth errors, crashes; those leave the key free.
* Replays return the current representation of the original resource with `Idempotent-Replayed: true`.
* Retention: 24 hours (`waltrix purge-idempotency`). An expired key may be reused.
* The API **requires** `Idempotency-Key` on every money-moving route.

Waltrix does not claim exactly-once *delivery*: networks can always lose responses. It guarantees that a
retried request with the same key is *applied at most once* and that the client can always learn the
outcome by retrying.

## Client retry behavior (both SDKs)

* Retry only GETs and POSTs with an idempotency key (money-moving methods always have one; it is created
  once per call and reused across attempts).
* Retry on timeouts, connection errors, 429, 502/503/504 and `409 concurrent_request`, with exponential
  backoff and full jitter, honoring `Retry-After`.
* If a mutation never gets a definitive answer, raise `UnknownOutcomeError` / `WaltrixUnknownOutcomeError`
  carrying the key. The dashboard shows "Result unknown" and verifies by re-sending with the same key;
  it never displays success before the server confirms. While the outcome is unknown, the dashboard also
  refuses to switch language, because that would discard the key.

## Recovery and its limits

* **API crash:** in-flight transactions roll back; clients retry with their keys.
* **Worker crash:** at most one hold is mid-expiry; it stays ACTIVE and is processed on the next run.
* **Database failover:** committed transactions survive according to your replication setting. With
  asynchronous replication, the last few committed transactions can be lost on failover (RPO > 0);
  clients that retry with their keys will re-apply them. Use synchronous replication if RPO must be 0.
* **Restore from backup:** see [deployment](deployment.md#backup-and-restore). After a restore, run
  reconciliation before reopening traffic.
