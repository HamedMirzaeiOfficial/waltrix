# Reconciliation

**English** · [فارسی](fa/reconciliation.md)

Reconciliation re-derives everything it can from the immutable journal and compares it with the mutable
records (materialized balances, transaction and hold statuses). It runs in **one REPEATABLE READ, READ
ONLY** transaction, so all checks see the same snapshot while money keeps moving.

Run it from the dashboard (Reconciliation → Run now), the API (`POST /api/v1/reconciliation/runs`,
permission `reconciliation:run`), or the CLI for every organization (`waltrix reconcile`, non-zero exit
code on errors, which suits cron and alerting).

## The checks

| Check | Severity | Detects |
| --- | --- | --- |
| `unbalanced_entry` | error | an entry whose debits ≠ credits in some currency |
| `short_entry` | error | an entry with fewer than two postings |
| `trial_balance` | error | org-wide posted debits ≠ credits per currency |
| `posted_balance_mismatch` | error | account posted totals ≠ sum of posted postings |
| `pending_balance_mismatch` | error | account pending totals ≠ pending entries of active holds |
| `overdraft` | error | a protected account with negative available balance |
| `posted_without_entry` | error | a POSTED/REVERSED transaction with no posted entry |
| `failed_with_postings` | error | a FAILED transfer/deposit/withdrawal that has entries |
| `reversal_total_mismatch` | error | `reversed_amount` ≠ sum of its posted reversals |
| `hold_state_mismatch` | error | hold status and transaction status disagree |
| `funding_vs_wallets` | error | simulated funding asset ≠ total wallet liabilities |
| `overdue_hold` | warning | an active hold past `expires_at` (expiry worker lagging) |

An error fails the run; a warning is reported but does not.

## How a check is written

Every check is one SQL query in `CHECKS` (`packages/ledger-core/src/waltrix_core/services/reconciliation.py`)
that returns **the rows that violate the rule**. No rows means the check passed. For example:

```sql
-- unbalanced_entry: one row per (entry, currency) whose lines do not cancel out
SELECT p.entry_id::text AS id, p.currency,
       sum(CASE WHEN p.direction='debit'  THEN p.amount ELSE 0 END) AS debits,
       sum(CASE WHEN p.direction='credit' THEN p.amount ELSE 0 END) AS credits
  FROM postings p WHERE p.org_id = :org
 GROUP BY p.entry_id, p.currency
HAVING sum(CASE WHEN p.direction='debit' THEN p.amount ELSE -p.amount END) <> 0
```

This shape keeps checks independent of each other and of the engine: each one is a fresh question asked
of the journal, not a reuse of the code being verified. Up to 50 violating rows per check are stored as
findings (`MAX_FINDINGS_PER_CHECK`); the count in the summary is always the full number.

## Why one snapshot

With READ COMMITTED, each of the twelve queries would see its own moment in time. A transfer committing
between two queries would make, for example, `posted_balance_mismatch` and `funding_vs_wallets` disagree
with each other: a false alarm during normal traffic. `REPEATABLE READ` fixes one snapshot for the whole
run, and `READ ONLY` guarantees reconciliation itself cannot write. The result is then stored in a
separate, short write transaction.

## What a run stores

Each run is stored in `reconciliation_runs` with:

* `status` (`passed` or `failed`) and `duration_ms`;
* a `summary`: per-check counts, error and warning totals, the trial balance per currency, and row counts
  (entries, postings, accounts, transactions);
* up to 50 `findings` per check, each with the check name, severity and the violating row as JSON.

An audit event (`reconciliation.run`) is written, and the Prometheus gauge
`waltrix_reconciliation_last_errors` exposes the latest error count for alerting.

The summary lives in a `JSONB` column, which does not keep key order; the dashboard displays the checks in
a fixed order (`CHECK_LABELS`) for that reason.

## Scheduling and alerting

| Where | How | Alert on |
| --- | --- | --- |
| Cron or the compose `worker` | `waltrix reconcile` hourly or nightly | non-zero exit code |
| Prometheus | scrape `/metrics` | `waltrix_reconciliation_last_errors > 0` |
| After a restore or failover | `waltrix reconcile` before reopening traffic | any error |

`overdue_hold` warnings usually mean `waltrix expire-holds` is not running often enough, not that money is
wrong.

## Handling findings

1. Treat any error as an incident. Do not "fix" balances with SQL; that breaks the next reconciliation.
2. Find the cause through the finding details (ids), the audit log and correlation ids in logs.
3. Correct money with reversals or manual entries between internal accounts, so the correction itself is
   recorded. Fix cache drift (`posted_balance_mismatch` with a correct journal) with a reviewed migration
   that recomputes the columns from postings, then re-run reconciliation.

### A worked example

A run fails with `posted_balance_mismatch` and `funding_vs_wallets` for one wallet account:

1. The finding shows the account id, its cached totals and the totals derived from postings. The journal
   side is consistent with `unbalanced_entry` and `trial_balance` (both passed), so the journal is fine
   and the **cache** drifted.
2. The audit log and database logs around the time of the drift show a manual SQL `UPDATE` on `accounts`.
3. The correction is a migration that recomputes `posted_debits` and `posted_credits` of that account from
   its postings, reviewed by a second person. Money itself does not move, so no journal entry is needed.
4. A new run passes; the incident note links both runs.

If instead `unbalanced_entry` had failed, the journal itself would be wrong. That should be impossible
while the deferred triggers are enabled, so the first question is who disabled them.

`tests/integration/test_ledger_invariants.py::test_10_reconciliation_detects_tampered_cache` tampers with a
cached balance and asserts the run fails with the expected checks.
