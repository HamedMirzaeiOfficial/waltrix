# Waltrix learning guide

**English** · [فارسی](../README.md)

> **Wallet + Matrix**: a sense of structure, transactions and financial technology.

This guide is written for **study**, not as a quick reference. Its goal is to teach the engineering of financial software in depth by reading the real code of this project: double-entry accounting, database transactions, locking and concurrency, idempotency, API and SDK design, and the UX of operations where a "mistake" means lost money.

> The precise technical reference is in [`docs/`](../../README.md) in English and in [`docs/fa/`](../../fa/README.md) in Persian: [architecture](../../architecture/overview.md), [double-entry model](../../financial-model/double-entry.md), [invariants](../../financial-model/invariants.md), [concurrency](../../concurrency.md), [API](../../api/rest.md), [security](../../security.md). The terms of both languages are side by side in the [glossary](../../glossary.md).

## Prerequisites

- Python and basic SQL (`SELECT`, `JOIN`, transactions)
- TypeScript and basic React (components, hooks, state)
- Familiarity with HTTP and Git

You do not need to know accounting, SQLAlchemy, FastAPI, Hypothesis or Playwright; the chapters explain them.

## Chapters

| # | Chapter | Main topic |
| --- | --- | --- |
| 1 | [The architecture map](01-architecture.md) | monorepo, layers, why a separate "financial core" |
| 2 | [Money and double-entry accounting](02-money-and-double-entry.md) | minor units, account types, debit/credit, why float is forbidden |
| 3 | [The posting engine and database constraints](03-posting-engine.md) | `post_entry`, CHECK, composite FKs, deferred triggers |
| 4 | [Transactions, locks and concurrency](04-transactions-and-locks.md) | READ COMMITTED, `FOR UPDATE`, lock order, deadlocks |
| 5 | [Idempotency: safe repetition](05-idempotency.md) | keys, fingerprints, storing the key with the outcome, "unknown outcome" |
| 6 | [Holds, reversals and the status lifecycle](06-holds-reversals-lifecycle.md) | pending entries, partial capture, reversal, state machines |
| 7 | [Reconciliation and audit](07-reconciliation-and-audit.md) | rebuilding from the journal, snapshots, the audit log |
| 8 | [Security and multi-tenancy](08-security-and-tenancy.md) | tenants, roles and permissions, API keys, CSRF, enumeration |
| 9 | [API and SDK design](09-api-and-sdks.md) | structured errors, cursor pagination, safe retries, ParamSpec |
| 10 | [The dashboard and the UX of moving money](10-dashboard-and-money-ux.md) | the transfer state machine, preventing double submission, design tokens |
| 11 | [Testing](11-testing.md) | tests on real PostgreSQL, property-based, stress, Playwright |
| 12 | [Operations and deployment](12-operations.md) | structured logs, metrics, health/ready, backups and RPO |
| 13 | [Lessons from bugs](13-bug-stories.md) | real bugs and mistakes from building this project, briefly |
| 14 | [Challenge stories](14-challenge-stories.md) | 12 in-depth stories from symptom to lesson, ready to tell in an interview |
| 15 | [Making the dashboard bilingual](15-i18n.md) | `t()`, RTL, Persian digits, the Solar Hijri calendar, locking the language during a money operation |

## Suggested reading path

1. Read chapter 1 and run the project with the Quick start in the [README](../../../README.md). Sign in as the demo user, make a transfer and look at its journal entry page.
2. Read chapters 2 and 3 together, with `packages/ledger-core/src/waltrix_core/rules.py` and `services/ledger.py` open beside them.
3. Chapters 4 and 5 are the heart of the project. After reading them, run `tests/concurrency/test_concurrency.py`.
4. Read chapters 6 to 9 in order.
5. Read chapter 10 (frontend) and 11 (testing), and break a test on purpose.
6. Read chapters 13 and 14 last; the bug stories mean more once you have seen the code. Read chapter 15 whenever the frontend interests you.

Every chapter ends with a few **exercises**. Actually do them; that is where most of the learning happens.

## How to read the code

- **Start from the invariants, not the details.** First look at the table in [invariants.md](../../financial-model/invariants.md): where each rule is checked in the engine, in the database, in reconciliation, and by which test.
- **Follow one request.** Follow "transfer money" from the Confirm button in `apps/web/src/features/transfer/TransferPage.tsx` to `routers/money.py::create_transfer`, `services/operations.py::transfer` and `services/runner.py::run_operation`.
- **Tests are executable documentation.** When you are not sure exactly what a function guarantees, read its test.

## Short glossary

The complete list, with the English and Persian term and the label you see in the dashboard, is in the [shared glossary](../../glossary.md).

| Term | Meaning in this project |
| --- | --- |
| Ledger | the set of accounts of one organization |
| Journal entry | one financial event with several debit and credit lines; immutable |
| Posting | one debit or credit on one account |
| Debit / Credit | the two sides of an entry (left / right of the book) |
| Minor unit | cents for USD; every amount is an integer of these |
| Hold | money set aside but not moved yet |
| Reversal | an opposite entry that corrects; the original is never deleted |
| Idempotency | a request executed several times has an effect only once |
| Reconciliation | rebuilding balances from the journal and comparing them with stored values |
| Tenant | an organization with fully isolated data |
