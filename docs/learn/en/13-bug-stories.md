# Chapter 13 — Lessons from bugs

**English** · [فارسی](../13-bug-stories.md)

This chapter collects the bugs and mistakes that **really** happened while building this project, in the order they happened, with their cause and lesson. None of them is made up.

## 1. Lock order in hold capture

**What happened:** the first version of `_resolve_hold` locked in this order: hold → wallets → accounts → **transaction row**. But `reverse_transaction` locks the transaction row **first**. Two operations that lock shared resources in different orders are the classic recipe for a deadlock.

**How it was found:** by reading the code against the "global lock order" rule written at the top of `operations.py`, not by a test. The tests did not exercise this path, because a reversal is rejected on a hold that has not been captured yet.

**Lesson:** **write down** the lock-order rule (in a comment or an ADR). Then compare every new operation against it. Tests rarely find rare deadlocks.

## 2. A migration that pointed at live code

**What happened:** the trigger SQL lived in `db/ddl.py` and migration `0001` imported it.

**Why that is bad:** a migration must be a photograph of the past. If `ddl.py` ever changed, databases migrated earlier would have the old version and new databases the new one, under the same revision number.

**The fix:** the SQL was copied into the migration file itself and `ddl.py` was deleted.

## 3. A rollback that "expired" objects

**What happened:** the manual-entry test failed with the odd error `A transaction is already begun on this Session`.

**The cause:** an earlier operation had failed with `ValidationFailed` and its transaction had been rolled back. After a rollback, SQLAlchemy **expires** every object in the session (it no longer knows whether their values are correct). The next line of the test read `exp.id`; reading an expired attribute issues a `SELECT` and **automatically opens a new transaction** (autobegin). `run_operation` deliberately refuses to start inside an open transaction, so it raised.

**Lesson:** `expire_on_commit=False` prevents expiry after a commit, not after a rollback. And the error showed that the rule "`run_operation` owns its transaction" really is enforced. The bug was in the test, not in the engine.

## 4. Fixtures that could not be seen

**What happened:** the fixtures in `tests/conftest.py` were not visible to `apps/api/tests`, and `pytest_plugins` is no longer supported in a non-root conftest. Then the SDK's test folder collided with the root `tests` package and imports broke.

**The fix:** the fixtures moved to `tests/fixtures.py`, and a root `conftest.py` loads them with `pytest_plugins = ["tests.fixtures"]`; the SDK test folder has no `__init__.py`.

**Lesson:** test layout in a monorepo is a design decision. Settle it early.

## 5. A required header that OpenAPI called "optional"

**What happened:** `Idempotency-Key` was required in code (we raised an error without it), but because the parameter had `default=None`, OpenAPI showed it as **optional**. The test written for exactly this (`test_openapi_documents_idempotency`) went red.

**Why it matters:** anyone generating a client from OpenAPI, or reading the docs, would think the header was not needed.

**Lesson:** test the contract, not just the behaviour.

## 6. A heredoc that broke the `&&` chain

**What happened:** a command like this was written:

```bash
ruff check . && cat >> .gitignore <<'EOF'
...
EOF
git add -A && git commit ...
```

ruff failed, yet the commit happened! The heredoc ends the line, and `git add` is a **new** command that has nothing to do with ruff's result. The commit was corrected immediately (an amend on the local branch, before any push).

**Lesson:** use `set -e` in scripts and never assume `&&` carries across a new line. Better still: run the linter in CI and in a pre-commit hook.

**It happened again.** While this very chapter was being translated, it was written to disk with a shell heredoc whose terminator was also `EOF`. The `EOF` line inside the example above ended the heredoc early, and the rest of the chapter ran as shell commands, including `git add -A`. The `git commit ...` that followed failed (`...` is not a valid path), so nothing was committed; the index was reset and the file was written with an editor tool instead. Same mechanism, different symptom: **text that contains your delimiter is code, not data.** Use a delimiter that cannot appear in the content, or do not pass content through a shell at all.

## 7. A miscount in the test, not in the code

**What happened:** the SDK round-trip test expected 6 transactions and got 5. The code was the first suspect, but a manual count gave deposit, transfer, failed transfer, hold, reversal = **5**. A capture does not create a new transaction; it makes the hold transaction POSTED.

**Lesson:** when a test is red, first ask "is my expectation right?". And this bug taught something about the model: a capture is a change of status, not a new record.

## 8. A mock that never resolved

**What happened:** a Vitest test ran its body to completion but then hung for 10 seconds and failed with "Hook timed out". Step-by-step `console.log` showed that the test itself had finished and the hang came afterwards.

**The cause:** `create.mockImplementation(() => new Promise(...))` returns a **forever-pending** promise for every later call too. The fix was `mockImplementationOnce`. Then, to be sure, a test was added that checks 300 ms after success that `create` was called only once; in other words, we made sure this was not the symptom of a real double submission.

**Lesson:** when a mock behaves strangely, assume it might be hiding a real bug, and rule that out with an explicit assertion.

## 9. JSONB does not keep key order

**What happened:** the list of reconciliation checks in the UI came out in an odd order every time.

**The cause:** the run summary is stored in a `JSONB` column, and PostgreSQL sorts JSONB keys **by length and then alphabetically**, not in insertion order. `Object.entries` in the frontend showed that order.

**The fix:** the UI sorts by a fixed list (`CHECK_LABELS`).

**Lesson:** `JSON` keeps order and whitespace, `JSONB` does not. If order means something, store an array or sort when displaying.

## 10. A table rendered twice

**What happened:** the Playwright test `getByText("reconciliation.run")` failed with a strict-mode error: two elements were found.

**The cause:** for responsiveness, `DataTable` keeps both a `<table>` (desktop) and a card list (mobile) in the DOM and hides one with CSS. Every piece of text exists twice.

**The fix:** the tests were scoped to `page.getByRole("table")`; the mobile test to `getByRole("list", { name: "Wallets" })`.

**Lesson:** "hidden with CSS" means "still in the DOM". The difference matters for tests and for screen readers (which skip the hidden list because it is `display:none`).

## 11. Node without TypeScript

**What happened:** the TypeScript example would not run with `node --experimental-strip-types`: `ERR_NO_TYPESCRIPT`. The Linux distribution's Node had been built without that feature.

**The fix:** the example is compiled with `tsc` and the output is run; no new dependency (such as tsx) was added.

**Lesson:** "works on my machine" includes "with my installed Node". Run examples in the real environment.

## 12. Versions that were the "newest" but did not fit together

**What happened:** npm warned that recharts 2 and eslint 9 were deprecated. The newest were TypeScript 7 and Vite 8. But `typescript-eslint` only supported up to TypeScript 6.1.

**The decision:** the compatible set that talkio also uses (TypeScript 5.7, Vite 6) was kept; recharts went to 3.10 and eslint to 10.14, with versions released at least two weeks earlier.

**Lesson:** "newest" is not a goal; "compatible and stable" is. Read `peerDependencies` before upgrading.

## 13. A chart animation in a screenshot

**What happened:** the first screenshot of the Overview page showed a flat volume chart, as if there were no transactions.

**The cause:** Recharts animates for 1.5 seconds by default, and the screenshot was taken mid-animation. The data was correct.

**The fix:** a shorter animation (500 ms) and a longer wait before the screenshot.

**Lesson:** suspect the display before blaming the logic. And the brief said "real screenshots only": so a screenshot must show the real state, not an intermediate frame.

> Deeper versions of several of these stories, plus the bugs found while making the dashboard bilingual, are in [chapter 14](14-challenge-stories.md), told as "scene, root cause, fix, lesson, question".

## Final exercise

Re-introduce one of these bugs on purpose in an experimental branch (for example number 1 or 9) and see which test or tool catches it. If none does, write that test. The best sign of understanding a bug is a test that makes its return impossible.
