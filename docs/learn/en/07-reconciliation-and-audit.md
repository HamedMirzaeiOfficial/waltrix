# Chapter 7 — Reconciliation and audit

**English** · [فارسی](../07-reconciliation-and-audit.md)

Files for this chapter: `services/reconciliation.py`, `services/audit.py`, `features/admin.tsx` (the Reconciliation page), [reconciliation.md](../../reconciliation.md)

## 1. "Trust, but verify"

Chapter 3 said the deferred trigger does not let an unbalanced entry commit. So why does reconciliation still look for unbalanced entries?

Because guarantees rest on **assumptions**: the trigger is enabled, nobody tampered with data as a superuser, migrations ran correctly, a backup was restored correctly. Reconciliation tests all those assumptions again, independently. If it ever finds something, one of the assumptions broke, and you found out **before the customer did**.

## 2. The idea: rebuild from the journal

The journal (entries and postings) is the source of truth. Everything else (the balance columns, transaction and hold statuses) is a "cache" or summary. Reconciliation recomputes the cache from the journal and compares:

```sql
WITH derived AS (
  SELECT p.account_id,
         sum(CASE WHEN p.direction='debit'  THEN p.amount ELSE 0 END) AS debits,
         sum(CASE WHEN p.direction='credit' THEN p.amount ELSE 0 END) AS credits
    FROM postings p JOIN journal_entries e ON e.id = p.entry_id
   WHERE p.org_id = :org AND e.phase = 'posted'
   GROUP BY p.account_id)
SELECT a.id, ... FROM accounts a LEFT JOIN derived d ON d.account_id = a.id
 WHERE a.posted_debits <> coalesce(d.debits, 0) OR ...
```

Note the `LEFT JOIN` and `coalesce`: an account with no postings must have a zero balance; if its cache is non-zero, that is still an error.

## 3. Twelve checks

| Check | The question it asks |
| --- | --- |
| `unbalanced_entry`, `short_entry`, `trial_balance` | Does the double-entry rule hold everywhere? |
| `posted_balance_mismatch`, `pending_balance_mismatch` | Does the balance cache match the journal? |
| `overdraft` | Is any protected account negative? |
| `posted_without_entry`, `failed_with_postings` | Do transaction statuses agree with the journal? |
| `reversal_total_mismatch` | Does `reversed_amount` equal the actual reversals? |
| `hold_state_mismatch` | Do a hold's status and its transaction's status agree? |
| `funding_vs_wallets` | Was money created from nothing? |
| `overdue_hold` (warning) | Has the expiry worker fallen behind? |

## 4. One snapshot for every check

```python
with session.begin():
    session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
    findings, summary = run_checks(session, actor.org_id)
```

If the twelve queries ran under READ COMMITTED, each query would see **its own** snapshot. A transfer could commit between query 3 and query 4 and the checks would disagree with each other: a "false alarm". Under REPEATABLE READ every query in the transaction sees the same picture as of the first one, even while money is moving. `READ ONLY` also guarantees that reconciliation cannot write anything by mistake.

The result is stored in a **separate** transaction (`reconciliation_runs`), because the first one was read-only.

## 5. Testing the detector

A detector that never finds anything may simply be broken. `test_10_reconciliation_detects_tampered_cache` tampers with the cache on purpose:

```python
session.execute(text("UPDATE accounts SET posted_credits = posted_credits + 5 WHERE id = :id"), ...)
run = reconciliation.run_reconciliation(session, owner)
assert {"posted_balance_mismatch", "funding_vs_wallets"} <= {f["check"] for f in run.findings}
```

Five cents of tampering lights up two independent checks. **Lesson:** for every alarm, have a test that triggers it.

## 6. When something is found

Never "fix" a balance with SQL; that breaks the next check and leaves no trace. Correct the money with an entry (a reversal, or a manual entry between internal accounts), so the correction itself is recorded.

## 7. The audit log: separate from money

`audit_events` answers "**who** did what": creating a wallet, changing a role, creating an API key, running reconciliation. The journal answers "how did **money** move". Keeping them separate means non-financial events (such as a role change) do not clutter the ledger, and the audit log can have a different retention policy.

```python
_FORBIDDEN_KEYS = {"password", "secret", "token", "api_key", "authorization", "key"}
```

`audit.record` strips sensitive keys from metadata, even if a programmer sends them by mistake. Every event has a `correlation_id`; with it you can go from a log line to the audit event and to the journal entry of the same request.

## Exercises

1. In `psql`, tamper with the `pending_debits` column of a wallet and run reconciliation from the dashboard. Which checks turn red? (Do this on the dev database, then put it back with a correcting step.)
2. Change the isolation level to READ COMMITTED and run reconciliation in a loop while the stress test runs. Do you see false alarms?
3. Design a thirteenth check: "no PENDING transaction may be older than 30 days". Write its SQL and a test that triggers it.
