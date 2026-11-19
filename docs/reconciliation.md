# Reconciliation

Reconciliation re-derives everything it can from the immutable journal and compares it with the mutable
records (materialized balances, transaction and hold statuses). It runs in **one REPEATABLE READ, READ
ONLY** transaction, so all checks see the same snapshot while money keeps moving.

Run it from the dashboard (Reconciliation → Run now), the API (`POST /api/v1/reconciliation/runs`,
permission `reconciliation:run`), or the CLI for every organization (`waltrix reconcile`, non-zero exit
code on errors, which suits cron and alerting).

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

Each run is stored (`reconciliation_runs`) with a summary (per-check counts, trial balance, row counts,
duration) and up to 50 findings per check, and an audit event is written. The Prometheus gauge
`waltrix_reconciliation_last_errors` exposes the latest error count for alerting.

## Handling findings

1. Treat any error as an incident. Do not "fix" balances with SQL; that breaks the next reconciliation.
2. Find the cause through the finding details (ids), the audit log and correlation ids in logs.
3. Correct money with reversals or manual entries between internal accounts, so the correction itself is
   recorded. Fix cache drift (`posted_balance_mismatch` with a correct journal) with a reviewed migration
   that recomputes the columns from postings, then re-run reconciliation.

`tests/integration/test_ledger_invariants.py::test_10_reconciliation_detects_tampered_cache` tampers with a
cached balance and asserts the run fails with the expected checks.
