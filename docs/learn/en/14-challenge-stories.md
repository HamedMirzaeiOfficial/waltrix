# Chapter 14 — Challenge stories: from symptom to lesson

**English** · [فارسی](../14-challenge-stories.md)

## Goal of this chapter

Chapter 13 went through the bugs briefly. This chapter is slower and is written for **telling**: in an interview, in a talk, or to a new teammate. Every story has the same structure:

1. **Scene:** the symptom a user, an operator or a test sees.
2. **Root cause:** why it really happened.
3. **The fix in the code:** with file and function names, so you can open them next to the text.
4. **Lesson:** something that carries over to other projects.
5. **Question:** to make sure you understood.

Every story carries one of two labels:

- **Real:** it actually happened while building this project.
- **Reconstructed from the design:** a bug the code deliberately prevents. The scene is a narrative, but the root cause and the fix are exactly what you see in the comments and tests of the named file. Say the same thing honestly in an interview: "the design prevented this", not "this happened to us in production".

A suggestion: before reading the "root cause" of each story, spend a few minutes guessing.

---

## 1. A transfer that did not happen twice after "connection lost"

*Reconstructed from the design*

**Scene.** An operator moves $500 from wallet A to B. The request reaches the server and the money moves, but just before the response arrives, the Wi-Fi drops. The browser only sees a network error. The operator clicks "Confirm" again. Has $1000 now left the wallet?

**Root cause.** From the client's point of view, "no response" is different from "not done", but they look the same. If the system treated the resend as a fresh request, the money would move twice. Storing the key somewhere separate (Redis, say, or a separate database transaction) is not enough either: if the key is recorded and the operation rolls back, a retry is refused although no money moved; if the operation commits and the key does not, a retry runs it again.

**The fix in the code.**

- `packages/ledger-core/src/waltrix_core/services/runner.py::run_operation`: the idempotency key is claimed **inside the same** PostgreSQL transaction that moves the money. So the key is committed if and only if the outcome is committed.
- `services/idempotency.py::claim`: `INSERT ... ON CONFLICT DO NOTHING` on a unique index. A second request with the same key **waits** on that row until the first finishes, then returns the stored outcome (a replay).
- A fingerprint of the parameters is stored too: the same key with a different amount gets `idempotency_key_reused` (409), not a replay.
- In the UI the key is created when you enter the "review" screen and stays fixed for every retry of that draft (`apps/web/src/features/transfer/machine.ts`).

Test: `tests/concurrency/test_concurrency.py::test_same_idempotency_key_concurrently_executes_once` sends several concurrent requests with one key and checks that only one executes.

**Lesson.** Idempotency is not a "response cache"; it is part of the operation's **atomicity**. Wherever the key and the effect are stored in two different places, there is a window in which one is recorded without the other.

**Question.** Why is a business failure (insufficient funds, for example) also stored as an outcome and replayed? If it were not stored, what scenario would be dangerous?

---

## 2. "Result unknown": a screen that never lies

*Reconstructed from the design, plus a real bug in a test*

**Scene.** The server is under load and a transfer takes 15 seconds. The client timeout is 15 seconds. What should the UI say? "Succeeded"? "Failed"? Either could be a lie.

**Root cause.** Most UIs have two states: success and error. With money there is a third: **we do not know**. Show it as "error" and the user tries again (with a new key!) and the money moves twice. Show "success" when it did not happen and the user makes a promise to a customer.

**The fix in the code.**

- `packages/typescript-sdk/src/client.ts::send`: only safe requests are retried (GET, or POST with a key). If no definitive answer arrives after all attempts, the SDK throws a separate `WaltrixUnknownOutcomeError`, not a generic error.
- `apps/web/src/features/transfer/machine.ts`: the transfer page's state machine has an `unknown` state. `success` is reachable **only** from a server response, never optimistically.
- In the `unknown` state the page automatically "verifies" with backoff. Verifying means resending the **same** request with the **same** key; the server replays the original outcome.

**The real bug alongside it.** While writing the test for this behaviour, a Vitest test ran to completion and then hung for 10 seconds. The cause: `mockImplementation(() => new Promise(...))` returns a forever-pending promise for **every** later call too. The fix was `mockImplementationOnce`, and more importantly, an assertion was added that 300 ms after success `create` has been called only once. In other words, we proved that the hang was not the symptom of a real double submission.

**Lesson.** "I don't know" is a first-class state. Model it, name it and design a UI for it.

**Question.** `machine.ts` does not let you go back to editing from the `unknown` state, but it does from `review` and `rejected`, and there it throws the key away. Why? (Hint: what does the server do with the same key and different parameters, and if the first attempt actually succeeded, what would editing and sending with a new key do?)

---

## 3. Capture and reversal at the same time: a deadlock no test caught

*Real*

**Scene.** One operator is capturing a hold, and at the same moment another operator reverses that hold's transaction. Both requests hang for 5 seconds and one comes back with "resource is busy". PostgreSQL's log says `deadlock detected`.

**Root cause.** The first version of `_resolve_hold` took locks in this order: hold → wallets → accounts → **transaction row**. But `reverse_transaction` locks the transaction row **first**. Two operations that lock shared resources in different orders are the classic recipe for a deadlock: each holds what the other wants.

Why did the tests not catch it? Because a reversal is only allowed on a POSTED transaction, and a hold that has not been captured yet is not POSTED. So the two paths did not naturally overlap in the tests.

**How it was found.** By **reading the code** against the rule written at the top of the file, not by a test.

**The fix in the code.** `packages/ledger-core/src/waltrix_core/services/operations.py`:

```text
idempotency key  ->  transaction / hold row  ->  wallets (by id)  ->  accounts (by id)
```

This global order is in the docstring at the top of the file, and `_resolve_hold` now locks the transaction row before the wallets. `lock_accounts` in `services/ledger.py` also locks accounts **in id order**, so two transfers A→B and B→A both take min(A,B) first and one simply waits for the other.

Test: `test_opposite_transfers_do_not_deadlock` sends 40 opposite transfers at once.

**Lesson.** **Write down** the lock-order rule (in a comment or an ADR) and compare every new operation against it. Tests rarely find rare deadlocks, but an eye that knows the rule does.

**Question.** Why are wallets locked `FOR SHARE` and accounts `FOR UPDATE`? If wallets were `FOR UPDATE` too, what would get slower?

---

## 4. A balance that was still stale after the lock

*Reconstructed from the design*

**Scene.** In a stress test, two concurrent $80 withdrawals from a wallet holding $100 both succeed and the account goes negative. Yet the code takes a `FOR UPDATE` lock before withdrawing!

**Root cause.** SQLAlchemy has an "identity map": if an `Account` object was already loaded into the session, `SELECT ... FOR UPDATE` takes the lock in the database, but by default the ORM keeps the object's **previous values**. So the code holds the right lock but reads a balance it loaded before the lock.

**The fix in the code.** Every lock uses `execution_options(populate_existing=True)` (`lock_accounts` in `services/ledger.py`, `_lock_wallets` and `_lock_hold` in `services/operations.py`). The docstring of `lock_accounts` says exactly this: read the balances **after** the lock was granted, not stale values from the identity map.

Test: `test_concurrent_debits_cannot_overspend`.

**Lesson.** "I hold the lock" and "I have fresh data" are two separate claims. Any caching layer between you and the database (an ORM, an application cache) can break the second.

**Question.** `populate_existing` appears nine times in the code. Which lock would work correctly without it, and why is it still better to have it?

---

## 5. Two workers, one expired hold

*Reconstructed from the design*

**Scene.** To be safe, two instances of the hold-expiry worker are running. Suddenly a wallet's balance has been "released" twice and is higher than the real money.

**Root cause.** If both workers read "active, overdue holds" and both process the same hold, the release is applied twice. With a plain `FOR UPDATE` the second worker waits and, after the first commits, sees the same row (now EXPIRED); that is correct, but the workers queue behind each other.

**The fix in the code.** `services/operations.py::expire_holds`:

- `FOR UPDATE SKIP LOCKED`: each worker takes a row nobody else has locked; two workers never pick the same hold and never wait for each other.
- Each hold expires in **its own transaction**: if a worker dies mid-way, at most that one hold stays ACTIVE and is picked up next time.
- `check_hold_transition` in `state_machine.py` also forbids EXPIRED → EXPIRED.

Tests: `test_parallel_expiry_workers_never_double_release` and `test_capture_and_release_race_has_one_winner`.

**Lesson.** Design background work for **several concurrent instances** from the start. `SKIP LOCKED` builds a simple, correct work queue on PostgreSQL.

**Question.** Why does `expire_holds` take only `LIMIT 1` per round, rather than, say, 100 rows in one transaction?

---

## 6. A migration that pointed at live code

*Real*

**Scene.** There was no symptom yet; the risk was spotted in code review. The trigger SQL lived in `db/ddl.py` and migration `0001` imported it.

**Root cause.** A migration must be **a photograph of the past**. If someone ever changed `ddl.py`, databases migrated earlier would have the old trigger and new databases the new one, **under the same revision number**. Two production databases on one version, behaving differently.

**The fix in the code.** The SQL was copied into `migrations/versions/0001_initial_schema.py` itself and `ddl.py` was deleted. The triggers `postings_entry_balanced` and `journal_entries_have_postings` are now defined only there.

**Lesson.** Migration code should depend only on things that never change. Even one "shared constant" is enough to rewrite history silently.

**Question.** If you want to change a trigger's rule, what is the right way to do it?

---

## 7. The deferred trigger: a safety net that must never tear

*Reconstructed from the design*

**Scene.** Imagine someone later adds a new operation (a fee, say) and by mistake writes only the debit line. Their unit tests are green, because they only check one account's balance.

**Root cause.** The posting engine (`rules.py::validate_entry`) checks balance, but the engine is code too, and code has bugs. If the code were the only guard, one bug could put an unbalanced entry into the ledger, and an unbalanced ledger means money was created from nothing or lost.

**The fix in the code.**

- Migration `0001`: `CONSTRAINT TRIGGER ... DEFERRABLE INITIALLY DEFERRED`. The check runs **at COMMIT** (not after every INSERT, because while the lines are being written the entry is naturally still unbalanced) and fails with `ERRCODE = 'check_violation'`.
- `runner.py`: error code `23514` (and `23503`, `23505`) is turned into `LedgerInvariantViolation` and logged at ERROR level: "a database constraint caught something the engine did not. This is a bug."
- Reconciliation independently checks `unbalanced_entry` too (chapter 7).

**Lesson.** For rules whose violation is a disaster, put **two independent layers** in place: one in code for a good message, one in the database for the guarantee. The second layer should never fire in practice; if it does, that is an alert.

**Question.** Why can the balance trigger not be defined `INITIALLY IMMEDIATE`?

---

## 8. JSONB scrambled the order

*Real*

**Scene.** On the reconciliation page, the list of checks appeared in a strange order every time: "Overdraft" before "Every entry balances", with no understandable logic.

**Root cause.** Each run's summary is stored in a `JSONB` column. PostgreSQL stores JSONB keys sorted **by length and then alphabetically**, not in insertion order. `Object.entries` in the frontend showed that order. Python had sent the right order; the database changed it.

**The fix in the code.** `apps/web/src/features/admin.tsx`: the fixed list `CHECK_LABELS` determines the display order and shows only the checks present in the summary. The same list now also holds the labels for translation.

**Lesson.** `JSON` keeps the text and the order, `JSONB` does not. If order means something, store an array or sort explicitly in the display layer.

**Question.** If a new check is added to reconciliation and someone forgets to add it to `CHECK_LABELS`, what does the UI show? (Look at the `RunReport` code.)

---

## 9. An organization that could be chosen but would not open

*Real, found while making the dashboard bilingual*

**Scene.** A user signs in, sees "Choose an organization" and clicks their organization. The page flickers and shows **the same page** again. A second click gets them in. The Playwright tests were green, because they always created a **new** organization rather than choosing an existing one.

**Root cause.** `SessionProvider` in `apps/web/src/lib/session.tsx` computed the current membership like this:

```ts
const orgId = getOrganizationId(); // a module variable in api.ts
const membership = me?.memberships.find((m) => m.organization.id === orgId) ?? null;
```

`selectOrganization` changed that variable and then `navigate("/")` was called. But changing a module variable **does not notify React**. The provider did not re-render, `RequireOrg` still saw the old `membership = null` and sent the user back to `/organizations`. When the `me` query came back the provider did re-render, but by then it was too late.

**How it was found.** While taking screenshots of the Persian version, the script got stuck on the organizations page. The i18n changes were suspected first, but the same scenario reproduced in **both languages**, and then on **the code from before the change** (in a separate git worktree). So the bug was old.

**The fix in the code.** The organization id is now kept in that provider's **state** as well as in `api.ts` (which the SDK reads on every request); `selectOrganization` and `signOut` update both. Regression test: `apps/web/e2e/session.spec.ts`.

**Lesson.** Any value that affects **rendering** must live in state or in a subscribable store. A module variable is fine for "something read on the next request", not for "something the page makes decisions on". And end-to-end tests must cover the **returning user**'s path, not only a brand-new one.

**Question.** `i18n.ts` also keeps the language in a module variable. Why does the same bug not happen there? (Hint: `LangProvider` and `key={lang}`.)

---

## 10. "$10.00-": the minus sign that moved

*Real, found while making the dashboard bilingual*

**Scene.** In the Persian version, the amount column of a wallet statement showed a $10 withdrawal as `$۱۰٫۰۰-`. A deposit was `$۲۵٫۰۰+`. For a finance operator, a sign in the wrong place means a wrong reading.

**Root cause.** The Unicode bidirectional algorithm (bidi). The `Money` component built the string `"−" + "$10.00"`. In a right-to-left paragraph, the minus sign is a "neutral" character at the start of the text and takes the paragraph's direction, so it is displayed **on the right**, which to the eye is after the number.

The same algorithm caused two more problems: ids such as `wallet:645addcc…` stuck to the left, and long English names such as "Northwind Demo (synthetic data)" were cut from the **beginning**: "…mo (synthetic data)".

**The fix in the code.**

- `apps/web/src/lib/format.ts::formatMoney`: in Persian, the amount is wrapped in the Unicode characters LRI and PDI (`⁦ … ⁩`), meaning "treat this as one separate left-to-right unit".
- `Money` in `components/ui/data.tsx` renders with `dir="ltr"` so that + and − stay inside the same unit.
- `index.css`: `.font-mono` gets `unicode-bidi: isolate` in RTL; user-entered names get `dir="auto"` so the content decides the direction.

All of these were found and confirmed with **real screenshots**, not with unit tests. A unit test only checks which characters a string has, not how it is laid out on screen.

**Lesson.** RTL is not just "add `dir="rtl"`". Numbers, ids, codes and Latin names inside Persian text are LTR islands and must be isolated explicitly. For a financial UI, look at the screen **with your own eyes** after any direction change.

**Question.** Why was isolating in `formatMoney` not enough, so that `Money` also needed `dir="ltr"`?

---

## 11. A language switch that could have lost an unknown transfer

*Real, a design decision made while making the dashboard bilingual*

**Scene.** This bug never reached a user. An operator makes a transfer and the result is "unknown" (story 2). The page shows the idempotency key and verifies automatically every few seconds. Now the operator switches the language. The page is rebuilt and returns to an empty form. The key, and the only safe way to learn the outcome, are gone. The operator makes the transfer again with a new key.

**Root cause.** The simplest way to re-translate every string after a language change is to remount the React tree (`key={lang}` in `LangProvider`). The React Query cache sits above it and survives, but components' **local state**, including the transfer state machine, is rebuilt from scratch.

**The fix in the code.**

- `apps/web/src/lib/lang.tsx::useLanguageLock(active)`: every operation that is in flight or has an unknown outcome takes a lock. While any lock is held, a language switch is refused and a toast says "Finish the current operation first".
- `TransferPage` takes the lock with `isUnresolved(state)`; `useIdempotentAction` (for funding, holds, reversals) with the `pending` or `unknown` status.
- Test: `apps/web/src/lib/lang.test.tsx` checks that a switch under the lock is refused.

**Lesson.** Measure every "harmless" UI feature (language, theme, tabs) against **the worst moment**: the middle of a money operation. The right question is not "what does this button do" but "if it is pressed right now, what is lost?".

**Question.** Why is no lock needed in the `review` state?

---

## 12. A rollback that "expired" objects

*Real*

**Scene.** The manual-entry test failed with an error unrelated to the test itself: `A transaction is already begun on this Session`.

**Root cause.** An earlier operation in the same test had failed with `ValidationFailed` and its transaction was rolled back. After a rollback, SQLAlchemy **expires** every object in the session, because it no longer knows whether their values are correct. The next line of the test read `exp.id`. Reading an expired attribute issues a `SELECT` and **automatically opens a new transaction** (autobegin). Then `run_operation`, which deliberately refuses to start inside an open transaction, raised.

**The fix in the code.** The bug was in the test: the id was saved in a variable before the operation. The check in `runner.py` stayed:

```python
if session.in_transaction():
    raise RuntimeError("run_operation must start its own transaction; commit first")
```

**Lesson.** `expire_on_commit=False` prevents expiry after a **commit**, not after a **rollback**. And this failure showed that the rule "every financial operation owns its transaction" really is enforced; if it were not, the next operation would have run silently inside the test's unintended transaction.

**Question.** Why does refusing to let `run_operation` start inside an open transaction matter for the correctness of money?

---

## Common patterns

| Pattern | Stories |
| --- | --- |
| "I don't know" is a state, not an error | 1, 2, 11 |
| Two independent layers for critical rules (code + database + reconciliation) | 7, 8 |
| Make order and concurrency explicit, not implicit | 3, 4, 5 |
| What was "stored" is not what you "see" (caches, the identity map, JSONB, module variables) | 4, 8, 9, 12 |
| Tests hit the happy path; bugs live in the returning, concurrent or badly-timed path | 3, 9, 11 |
| For UI, nothing replaces your eyes and real screenshots | 9, 10 |

## How to tell these stories

A 60-second template that works in interviews:

1. **The symptom** in one sentence: "Users clicked their organization and landed on the same page again."
2. **Why it was hard:** "The tests were green, because they always created a new organization."
3. **The root cause** in one technical sentence: "A value that rendering depended on lived in a module variable, and React was never told it changed."
4. **The fix and the proof:** "I moved it into state and wrote an end-to-end test for the returning user."
5. **The general lesson:** "Now I look at anything that affects rendering from that angle."

For "reconstructed from the design" stories the template differs slightly: "We knew this risk, we designed it so that it cannot happen, and this test proves it." That is just as valuable.

## Exercises

1. Re-introduce story 3: in an experimental branch, move the transaction lock in `_resolve_hold` after `lock_accounts`. Write a test that runs a capture and a reversal at the same time. Does it catch the deadlock? If not, why not?
2. Re-introduce story 9 (remove the `useState` from `session.tsx`) and watch `e2e/session.spec.ts` go red.
3. For story 10, remove `dir="ltr"` from `Money` and look at the statement page in Persian.
4. Tell one of these stories to someone with the 60-second template. If you say "I mean…" halfway through, you cannot yet state the root cause in one sentence.
