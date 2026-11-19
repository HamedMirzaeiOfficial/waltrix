# Chapter 4 — Transactions, locks and concurrency

**English** · [فارسی](../04-transactions-and-locks.md)

Files for this chapter: `services/runner.py`, `services/ledger.py::lock_accounts`, `services/operations.py`, `tests/concurrency/test_concurrency.py`, [ADR 0003](../../architecture/decisions/0003-locking-strategy.md)

This is the most important chapter of the project. The hardest bugs in financial systems come from concurrency: two requests at the same moment.

## 1. The classic problem: double spend

A wallet holds $100. Two $100 withdrawals arrive at the same time:

```
request A: reads the balance → 100      request B: reads the balance → 100
A: 100 >= 100 ✓ → subtracts             B: 100 >= 100 ✓ → subtracts
result: $200 spent out of $100
```

This is the **check-then-act** pattern: there is a gap between "checking" and "acting".

## 2. The solution: lock the row, then check

```python
def lock_accounts(session, org_id, account_ids):
    ids = sorted(set(account_ids))
    rows = session.execute(
        select(Account)
        .where(Account.org_id == org_id, Account.id.in_(ids))
        .order_by(Account.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalars().all()
```

- `FOR UPDATE` locks the row until the end of the transaction. Request B **waits** on this same `SELECT` until A commits or rolls back.
- When B gets the lock, under READ COMMITTED it reads the **newly committed** value ($0) and gets `insufficient_funds`.
- `populate_existing=True` matters: SQLAlchemy has an identity map, and if this object was already in the session, without this option it may hand you the **old** in-memory value, even after the lock was granted!

`test_concurrent_debits_cannot_overspend`: a $1000 wallet, 40 withdrawals of $100 **exactly at the same time** (with `threading.Barrier`). The result is always 10 successes, 30 failures, balance zero.

## 3. Deadlocks and lock order

A transfer A→B locks A, then B. At the same time a transfer B→A locks B, then A. Each waits for the other: a **deadlock**. PostgreSQL kills one, but we have handed a random error to a user.

The solution: `sorted(set(account_ids))`. Both transactions lock `min(A, B)` first; one waits and no cycle forms. `test_opposite_transfers_do_not_deadlock` runs forty transfers in both directions at once.

### A global order across different operations

Sorting accounts is not enough; different operations lock **other** rows too (wallets, holds, the original transaction of a reversal). So there is a global order (at the top of `operations.py`):

```
idempotency key  →  transaction / hold row  →  wallets (by id)  →  accounts (by id)
```

While this project was being written, `_resolve_hold` locked the transaction row **after** the accounts, while a reversal locks it **before** them: a potential deadlock. It was fixed so that the order is the same. (Chapter 13, and story 3 in chapter 14.)

## 4. FOR SHARE for wallets

Wallets are locked with `with_for_update(read=True)`, which is `FOR SHARE`:

- Two concurrent transfers on one wallet **do not block** each other on the wallet row (a shared lock is compatible with a shared lock). They wait on the account row instead.
- But `set_wallet_status` (suspend) takes `FOR UPDATE` and waits until in-flight transfers finish. So a wallet cannot be suspended "halfway through" a transfer.

## 5. Why not SERIALIZABLE?

SERIALIZABLE isolation gives the same safety without explicit locks, but instead of "waiting" it **rejects** conflicting transactions with `serialization_failure`. On a busy wallet that means a flood of errors that every client must retry correctly. With explicit locks, the normal behaviour under load is "wait", not "fail". The price is discipline about lock order.

## 6. The transaction boundary: `run_operation`

```python
with session.begin():
    session.execute(text("SET LOCAL lock_timeout = '5000ms'"))
    record, stored = idempotency.claim(...)          # chapter 5
    try:
        with session.begin_nested():                 # SAVEPOINT
            rtype, rid = execute(session)
    except BusinessRuleViolation as err:
        failed = on_failure(session, err)            # record a FAILED transaction
    idempotency.complete(record, ...)
# COMMIT: the deferred triggers run here
```

- **One COMMIT** makes partial writes impossible. If the process dies mid-way, PostgreSQL rolls everything back when the connection drops. `test_3_failure_mid_operation_commits_nothing` raises an exception after the postings were flushed and shows that nothing was recorded.
- **SAVEPOINT**: if a business rule is violated (such as insufficient funds), only the changes inside the savepoint are undone, and we can still record a "FAILED transaction" in the same transaction.
- **`lock_timeout`**: if a lock takes more than 5 seconds, instead of waiting forever we get error `55P03`, which becomes `409 concurrent_request` (retryable).

## 7. The hot account

Every deposit locks the `system:simulated_funding` account, so deposits in one currency run one after another. That is acceptable for a learning project and is recorded in the ADR. Real-world solutions: split the account into several shards, or buffer the postings.

## Exercises

1. In `lock_accounts`, remove `sorted` (`ids = list(set(account_ids))`) and run `test_opposite_transfers_do_not_deadlock` a few times. What is the error, and why does it happen only "sometimes"?
2. Remove `populate_existing=True`. Does any test break? If not, write one that exposes the bug (hint: load the account object into the same session before locking).
3. Change `lock_timeout` to `'1ms'` and run the stress test. How are the `ConcurrentRequest` errors counted, and do the invariants still hold?
4. With two `psql` windows, create a deadlock by hand (`BEGIN; SELECT ... FOR UPDATE` in different orders) and read PostgreSQL's message.
