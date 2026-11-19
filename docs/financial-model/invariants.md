# Invariants and where each one is enforced

**English** · [فارسی](../fa/financial-model/invariants.md)

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

## Why four layers and not one

Each layer covers a different way of failing:

| Layer | Catches | Does not catch |
| --- | --- | --- |
| Engine | user mistakes, with a precise, translatable error code | a bug in the engine itself |
| Database | a bug in the engine, or code that bypasses it | data changed by a superuser, a disabled trigger, a bad restore |
| Reconciliation | everything that reached disk, whatever the cause | problems in data it does not re-derive (e.g. audit metadata) |
| Tests | regressions before they ship | anything nobody wrote a test for |

A rule enforced in only one layer is a rule that one bug can break.

## Checking an invariant by hand

Reconciliation runs these continuously, but during an incident it helps to ask the database directly. Run
them against a read replica or inside `BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY`.

**1. Every posted entry balances per currency**

```sql
SELECT p.entry_id, p.currency,
       sum(p.amount) FILTER (WHERE p.direction = 'debit')  AS debits,
       sum(p.amount) FILTER (WHERE p.direction = 'credit') AS credits
  FROM postings p
 WHERE p.org_id = :org
 GROUP BY p.entry_id, p.currency
HAVING sum(p.amount) FILTER (WHERE p.direction = 'debit')
    <> sum(p.amount) FILTER (WHERE p.direction = 'credit');
-- expected: no rows
```

**2. Money is conserved** (funding asset = wallet liabilities, per currency)

```sql
SELECT a.currency,
       sum(CASE WHEN a.code = 'system:simulated_funding' THEN a.posted_debits - a.posted_credits END) AS funding,
       sum(CASE WHEN w.id IS NOT NULL THEN a.posted_credits - a.posted_debits END)                    AS wallets
  FROM accounts a LEFT JOIN wallets w ON w.account_id = a.id
 WHERE a.org_id = :org
 GROUP BY a.currency;
-- expected: funding = wallets on every row (manual entries between internal accounts excluded)
```

**10. The cached balance of one account equals its postings**

```sql
SELECT a.posted_debits, a.posted_credits,
       coalesce(sum(p.amount) FILTER (WHERE p.direction = 'debit'), 0)  AS journal_debits,
       coalesce(sum(p.amount) FILTER (WHERE p.direction = 'credit'), 0) AS journal_credits
  FROM accounts a
  LEFT JOIN postings p        ON p.account_id = a.id
  LEFT JOIN journal_entries e ON e.id = p.entry_id AND e.phase = 'posted'
 WHERE a.id = :account AND (p.id IS NULL OR e.id IS NOT NULL)
 GROUP BY a.posted_debits, a.posted_credits;
```

All three queries were run against the development database. The reconciliation SQL in
`services/reconciliation.py` is the authoritative version of each check; these are simplified for reading.

## Adding a new invariant

When a feature introduces a new rule (for example "a fee entry always credits a revenue account"):

1. **Engine:** check it where the entry is built and raise a `BusinessRuleViolation` with a stable code.
2. **Database:** add a CHECK, a foreign key or a deferred trigger in a **new** migration. Never edit an
   existing migration (see chapter 14, story 6, of the learning guide).
3. **Reconciliation:** add a check to `CHECKS` in `services/reconciliation.py` and a label to
   `CHECK_LABELS` in `apps/web/src/features/admin.tsx` (plus its Persian entry in `locales/fa.json`).
4. **Test:** add a numbered test that violates the rule through each layer and asserts it is caught,
   including one that tampers with the data and expects reconciliation to fail.
5. Add a row to the table above.

## What these guarantees do not cover

* A PostgreSQL superuser can disable triggers or edit rows. Run the API with a role that owns no tables
  (see [security](../security.md)); reconciliation exists to detect what slipped through anyway.
* Immutability is enforced for `journal_entries`, `postings` and `audit_events`. `transactions` and
  `holds` are mutable *status* records by design; their consistency with the journal is reconciled.
* Invariant 2 holds only while deposits and withdrawals are the only external flows. A fee or FX feature
  needs its own conservation rule (e.g. "funding = wallets + revenue").
