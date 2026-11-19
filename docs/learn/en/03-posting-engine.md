# Chapter 3 — The posting engine and database constraints

**English** · [فارسی](../03-posting-engine.md)

Files for this chapter: `services/ledger.py`, `db/models.py`, `migrations/versions/0001_initial_schema.py`, `tests/integration/test_ledger_invariants.py`

## 1. Defence in layers

Every financial rule in Waltrix has four layers:

1. The **engine** checks first, so it can return a precise error (`insufficient_funds`).
2. The **database** enforces the same rule with a constraint or trigger, so a bug cannot commit wrong data.
3. **Reconciliation** later recomputes everything, so silent drift is found.
4. **Tests** on real PostgreSQL prove that the layers above actually work.

**Lesson:** a check in code is for a good user experience; a database constraint is for correctness. You need both.

## 2. `post_entry`: the only place money moves

```python
def post_entry(session, actor, *, locked, phase, kind, description, lines, ...):
    validate_entry(lines)                       # the pure rules of chapter 2
    for line in lines:
        account = locked.get(line.account_id)   # the account must already be locked
        if account is None: raise LedgerInvariantViolation(...)
        ...
    for line in lines: _apply(locked[line.account_id], line, phase)
    for account in touched: _check_overdraft(account)
    session.add(JournalEntry(...)); session.add(Posting(...)) ...
```

Three points:

- `locked` is a dict of accounts **the caller has already locked**. The engine refuses to write to an account that is not locked. Forgetting a lock is therefore an obvious programming error, not a hidden race condition.
- All changes are applied first and overdraft is checked afterwards, so an entry that touches one account twice is still checked correctly.
- `LedgerInvariantViolation` is not a "user" error; it means a bug. The API turns it into a generic 500 and the details go only to the log.

## 3. Constraints in `models.py`

### Preventing overdraft in the database itself

```python
CheckConstraint(
    "allow_negative "
    "OR (normal_balance = 'credit' AND posted_credits - posted_debits - pending_debits >= 0) "
    "OR (normal_balance = 'debit'  AND posted_debits - posted_credits - pending_credits >= 0)",
    name="no_overdraft",
)
```

The test `test_7_database_check_blocks_overdraft_even_if_engine_is_bypassed` manipulates a balance directly with SQL and shows that PostgreSQL refuses it.

### Composite foreign keys: tenant and currency in the schema

```python
ForeignKeyConstraint(
    ["account_id", "org_id", "currency"],
    ["accounts.id", "accounts.org_id", "accounts.currency"],
)
```

An ordinary FK (`account_id → accounts.id`) only says "this account exists". The composite FK says "this account exists **and** belongs to this organization **and** has this currency". For that, `accounts` has a `UniqueConstraint("id", "org_id", "currency")` (an FK must point at a unique key). The result: even raw SQL cannot write a posting of organization A onto an account of organization B (`test_8_schema_rejects_cross_tenant_posting`), or a EUR line onto a USD account (`test_9_schema_rejects_posting_in_wrong_currency`).

## 4. Immutability with triggers

In migration `0001`:

```sql
CREATE TRIGGER postings_append_only
  BEFORE UPDATE OR DELETE ON postings
  FOR EACH ROW EXECUTE FUNCTION waltrix_reject_mutation();
```

`UPDATE postings SET amount = amount + 1` fails with "postings is append-only". Corrections are only possible with a reversing entry (chapter 6). The same applies to `journal_entries` and `audit_events`.

An honest limitation: a database superuser can disable the trigger. That is why [security.md](../../security.md) recommends running the API with a role that does not own the tables.

## 5. Deferred triggers: an unbalanced entry never commits

The problem: an entry has two postings, inserted by two separate `INSERT`s. After the first `INSERT` the entry is **temporarily** unbalanced. So you cannot check after each INSERT.

The solution: a **deferred constraint trigger**:

```sql
CREATE CONSTRAINT TRIGGER postings_entry_balanced
  AFTER INSERT ON postings
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION waltrix_check_entry_from_posting();
```

`INITIALLY DEFERRED` means the trigger runs at `COMMIT`, when all postings are in. If any entry is unbalanced in some currency, or has fewer than two postings, the whole transaction aborts. `test_1_database_rejects_unbalanced_entry_at_commit` tries exactly this with raw SQL.

**Lesson:** some rules are not defined on "one row" but on "a set of rows at the end of a transaction". A deferred constraint is the tool for that.

## 6. A migration is frozen

The triggers first lived in a separate Python file that the migration imported. The flaw: if that file ever changed, the old migration would "change" too, and databases migrated earlier would differ from new ones. So the SQL was copied into the migration file itself. A migration must be a photograph of the past, not a pointer to present code.

## Exercises

1. In `psql`, run `UPDATE journal_entries SET description='x'` and look at the error. Then try `ALTER TABLE ... DISABLE TRIGGER` (on a test database!). Why must the runtime role not be allowed to do this?
2. Temporarily make the deferred trigger `INITIALLY IMMEDIATE` and run the tests. What breaks, and why?
3. Design a new constraint: "a CLOSED account must not receive new postings". Write it as a trigger and add a test for it.
