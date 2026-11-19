# Invariants and where each one is enforced

Defense in depth: the engine checks first (to give a precise error), the database enforces the same rule
(so a bug cannot commit bad data), reconciliation re-derives it later (so silent drift is detected), and a
test proves it against real PostgreSQL.

| # | Invariant | Engine | Database | Reconciliation | Test |
| --- | --- | --- | --- | --- | --- |
| 1 | Every entry balances per currency, ≥ 2 postings | `rules.validate_entry` | deferred constraint triggers at COMMIT | `unbalanced_entry`, `short_entry`, `trial_balance` | `test_1_*`, property tests |
| 2 | Internal transfers conserve money | two-line entries only | (follows from 1) | `funding_vs_wallets` | `test_2_*`, stress test |
| 3 | No partial commits | one tx per operation + savepoint | atomic transaction | `posted_without_entry`, `failed_with_postings` | `test_3_failure_mid_operation_commits_nothing` |
| 4 | Posted history is immutable | no update code paths | `BEFORE UPDATE OR DELETE` triggers raise | - | `test_4_journal_is_append_only` |
| 5 | Reversals preserve history | new mirrored entry, `reverses_entry_id` | FK to original | `reversal_total_mismatch` | `test_5_*` |
| 6 | A request applies at most once per key | `idempotency.claim` | unique (org, operation, key) | - | `test_6_*`, concurrency test |
| 7 | Protected accounts never overdraw (incl. holds) | check after locks | `ck_accounts_no_overdraft` | `overdraft` | `test_7_*`, concurrent debits |
| 8 | No cross-tenant access | every query filters `org_id`, 404 for others | composite FKs `(id, org_id)` | - | `test_8_*`, API tenancy tests |
| 9 | Currencies never mix | currency checks | composite FK `(account, org, currency)` | per-currency checks | `test_9_*` |
| 10 | Cached balances equal the journal | same tx as postings, row locks | non-negative CHECKs | `posted_balance_mismatch`, `pending_balance_mismatch` | `test_10_*` |
| 11 | Hold and transaction states agree | `_resolve_hold` | `capture_has_entry` CHECK | `hold_state_mismatch` | hold tests, race tests |
| 12 | Amounts are positive integers ≤ 2^53−1 | `validate_amount`, Pydantic `StrictInt` | `amount > 0` CHECK, BIGINT | - | unit + API validation tests |

## What these guarantees do not cover

* A PostgreSQL superuser can disable triggers or edit rows. Run the API with a role that owns no tables
  (see [security](../security.md)); reconciliation exists to detect what slipped through anyway.
* Immutability is enforced for `journal_entries`, `postings` and `audit_events`. `transactions` and
  `holds` are mutable *status* records by design; their consistency with the journal is reconciled.
