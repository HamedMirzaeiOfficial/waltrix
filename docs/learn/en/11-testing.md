# Chapter 11 — Testing

**English** · [فارسی](../11-testing.md)

Files for this chapter: `tests/fixtures.py`, `tests/unit/`, `tests/integration/`, `tests/concurrency/`, `apps/api/tests/`, `packages/python-sdk/tests/`, `apps/web/src/**/*.test.tsx`, `apps/web/e2e/`

## 1. This project's test pyramid

| Layer | Tool | Count (last run) | What it proves |
| --- | --- | --- | --- |
| Pure domain | pytest + Hypothesis | part of 156 | entry, money, state machine and permission rules |
| Integration | pytest + real PostgreSQL | part of 156 | 10 financial invariants, triggers and constraints |
| Concurrency | threads + Barrier | part of 156 | no double spend, no deadlock, no double execution |
| Stateful property | Hypothesis `RuleBasedStateMachine` | 1 (12 examples × 20 steps) | the ledger behaves like a simple model |
| HTTP | FastAPI TestClient | 31 | authentication, tenancy, validation, pagination |
| SDK | httpx MockTransport + a real server | 18 | retries, keys, error mapping |
| Frontend | Vitest + Testing Library | 24 + 30 (SDK) | the transfer state machine, the transfer page, i18n and the language lock |
| E2E | Playwright | 7 | critical user journeys, desktop and mobile, Persian, a returning user |

## 2. Why real PostgreSQL and not SQLite

`FOR UPDATE` locks, `SKIP LOCKED`, deferred triggers, CHECK with expressions, `ON CONFLICT`, `REPEATABLE READ`: none of them exist in SQLite in the same form. Testing invariants on a database without these features only proves that the test is green. `scripts/dev-db.sh` starts a private PostgreSQL cluster in `.local/pgdata`, without Docker and without sudo.

Once per session, `tests/fixtures.py` downgrades and upgrades the migrations (so the migrations are tested too) and runs `TRUNCATE` before every test. Why TRUNCATE rather than rolling back each test? Because the concurrency tests use several connections and must see each other's committed data. (TRUNCATE does not fire row triggers, so it does not conflict with append-only tables.)

## 3. Test invariants, not functions

Test names carry the number of the invariant: `test_1_...` to `test_10_...`. Each test answers a question, not "does this function work". A few interesting ones:

- `test_3_failure_mid_operation_commits_nothing` uses `monkeypatch` to raise an exception after the postings were flushed (simulating a crash), then proves that the number of postings did not change **and** that the idempotency key is still free.
- `test_4_journal_is_append_only` tries five UPDATE/DELETE statements with `parametrize`.
- `test_1_database_rejects_unbalanced_entry_at_commit` bypasses the engine and builds an unbalanced entry directly with the ORM.

## 4. Concurrency tests

```python
def run_concurrently(factory, n, fn):
    barrier = threading.Barrier(n)
    def worker(i):
        s = factory()
        barrier.wait(timeout=30)   # everyone starts at exactly the same moment
        return fn(s, i)
```

Without the `Barrier`, the first thread has probably finished before the tenth is even created, and no race happens: the test goes green but proves nothing. Each thread has its own session (connection). Exceptions are collected and asserted at the end.

The stress test: 16 threads × 30 random operations on 6 overlapping wallets, and every transfer is **immediately repeated with the same key** (simulating a retry after a timeout) and must be a replay. At the end: money is conserved, no balance is negative, reconciliation is green. This is a correctness test, not a benchmark; no performance figure is claimed.

## 5. Property-based tests

```python
@given(st.lists(st.integers(1, 10**12), min_size=1, max_size=8), st.integers(1, 8))
def test_property_split_credits_balance(self, debits, n_credit): ...
```

Instead of a few hand-made examples, Hypothesis generates hundreds of random inputs (and edge cases). Stronger still is the **stateful test** (`test_property_ledger.py`): Hypothesis builds random sequences of deposits, withdrawals, transfers, holds, captures, releases and reversals. After **every step**, the real balance of each wallet is compared with a simple Python model (a dict). If it fails, Hypothesis **shrinks** the sequence and shows the shortest failing one.

**Lesson:** the model must be simple enough to be obviously correct. The model's whole logic is a few lines of additions and subtractions.

## 6. Testing the SDK without a network

`httpx.MockTransport` lets you replace the server with a Python function: "time out twice, then return 201". The test checks that all three attempts sent the **same** `Idempotency-Key`. The round-trip test hands FastAPI's own `TestClient` to the SDK as its `http_client`: a real SDK, a real API, a real database, no port.

## 7. Playwright

Before the tests, `playwright.config.ts` migrates a separate database (`waltrix_e2e`) and starts the API, serving the dashboard build, on port 4823. Seven journeys: funding and a transfer with review through to seeing the balanced entry; a definite overspend failure (bypassing the UI); reconciliation and audit; the API key secret shown once; mobile navigation on a Pixel 7; a complete transfer in Persian with Persian digits (`i18n.spec.ts`); and signing in again and choosing an existing organization (`session.spec.ts`, chapter 14, story 9).

## 8. Real results

The results of the last run are in the README (156 Python, 30 SDK, 24 dashboard, 7 Playwright). The rule: no number is written down unless it was run.

## Exercises

1. In `test_concurrent_debits_cannot_overspend`, remove `barrier.wait` and run the test 20 times. Is it always green? Does that mean the code is correct?
2. Plant a deliberate bug in `operations.transfer`: read the balance **before** taking the lock. Which tests catch it? Which do not?
3. Raise `max_examples` of the stateful test to 200 and run it. Add a new rule (for example "suspend and reactivate a wallet") to the machine.
4. Write a Playwright test for "Result unknown" (hint: `page.route` to drop the response after the request has reached the server).
