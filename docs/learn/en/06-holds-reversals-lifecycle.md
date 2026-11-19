# Chapter 6 — Holds, reversals and the status lifecycle

**English** · [فارسی](../06-holds-reversals-lifecycle.md)

Files for this chapter: `state_machine.py`, `services/operations.py` (`create_hold`, `_resolve_hold`, `expire_holds`, `reverse_transaction`), [transaction-lifecycle.md](../../financial-model/transaction-lifecycle.md), [ADR 0005](../../architecture/decisions/0005-holds-as-pending-entries.md)

## 1. What a hold is

When you pay by card at a hotel, the amount is "blocked" but not yet taken. Later the real amount (perhaps less) is **captured**, or the block is **released**, or it **expires** on its own.

## 2. A hold as a pending entry

```
create_hold 400:   Dr wallet:a 400 (pending)   |   Cr wallet:m 400 (pending)
```

This is a real, balanced entry with `phase = "pending"`. It affects the `pending_*` columns, not `posted_*`. So:

```
posted balance: 1000     available: 1000 − 400 = 600
```

A capture of 250:

1. The pending effect of the hold entry is **released** (`release_pending`: the pending columns go back).
2. A **new** posted entry for 250 is recorded.
3. The remainder (150) is free automatically, because the pending effect of the whole hold was removed.

A subtle point: the pending entry itself **never changes** (append-only). Whether it "still counts" is derived from the hold's status. Reconciliation checks that the pending columns of every account exactly equal the sum of the pending entries of ACTIVE holds (`pending_balance_mismatch`).

## 3. An explicit state machine

```python
TRANSACTION_TRANSITIONS = {
    CREATED:  {PENDING, POSTED, FAILED},
    PENDING:  {POSTED, FAILED},
    POSTED:   {REVERSED},
    FAILED:   set(),
    REVERSED: set(),
}
```

Every status change goes through `check_transaction_transition`. An illegal move (for example POSTED → PENDING) raises `invalid_state_transition` instead of silently corrupting data. `test_transaction_transitions_exhaustive` tries **all 25 pairs** (5×5).

The brief said "do not cram everything into one state machine". So a hold has its own machine (`ACTIVE → CAPTURED | RELEASED | EXPIRED`), and so does a wallet (`active ⇄ suspended → closed`).

### Mapping a hold to its transaction

| Event | Hold | Transaction of type hold |
| --- | --- | --- |
| Created | ACTIVE | PENDING |
| Capture | CAPTURED | POSTED (`posted_amount` = the captured amount) |
| Release | RELEASED | FAILED (`failure_code=hold_released`) |
| Expiry | EXPIRED | FAILED (`failure_code=hold_expired`) |

Reconciliation checks this mapping too (`hold_state_mismatch`).

## 4. Expiry with several workers

```python
select(Hold).where(Hold.status == ACTIVE, Hold.expires_at <= as_of)
    .limit(1).with_for_update(skip_locked=True)
```

`SKIP LOCKED` means "skip rows somebody else has locked". So several concurrent workers never process the same hold twice and never wait for each other. Each hold expires in its own transaction; if a worker dies, at most one half-done hold is rolled back and processed next time. Test: `test_parallel_expiry_workers_never_double_release` (6 workers, 30 holds, total exactly 30).

A capture after `expires_at` is rejected (`hold_expired`) even if no worker has reached that hold yet. The real time matters, not the processing time.

## 5. Reversal: do not erase history

```
original transfer:       Dr alice 3000 | Cr bob 3000
partial reversal 1000:   Dr bob   1000 | Cr alice 1000   (reverses_entry_id = the original entry)
```

- The original entry stays untouched (the trigger forbids changes).
- A new transaction of type `reversal` is created that points to the original.
- The original transaction keeps `reversed_amount`; it only moves to `REVERSED` once fully reversed. So a "partial refund" is simply a partial reversal.
- The original transaction row is locked `FOR UPDATE`, so two concurrent reversals cannot return more than the original amount. `test_reversal_race_cannot_double_refund`: 12 concurrent reversals of 100 on a transfer of 500 → exactly 5 succeed.

### When the recipient has already spent the money

If Bob sent the money elsewhere, the reversal fails with `insufficient_funds`. Waltrix deliberately does not let a reversal push a customer account negative. That is a business decision that a real system might make differently (for example with a "receivable from customer" account), but it must be explicit.

A reversal on a **suspended** wallet is allowed (`check_status=False`), because corrections must always be possible.

## Exercises

1. Create a hold, capture part of it, and look at both entries (pending and posted) on the transaction page. Write down the balances at each step.
2. Allow `FAILED → POSTED` in `TRANSACTION_TRANSITIONS`. Which test breaks? What dangerous scenario does the prohibition prevent?
3. Design a "second capture" (several partial captures from one hold). What has to change in the data model?
4. Why does `expire_holds` process one hold per transaction rather than all of them in one? List the pros and cons.
