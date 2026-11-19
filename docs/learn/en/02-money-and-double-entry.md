# Chapter 2 — Money and double-entry accounting

**English** · [فارسی](../02-money-and-double-entry.md)

Files for this chapter: `waltrix_core/money.py`, `rules.py`, `enums.py`, `services/ledger.py`, [double-entry.md](../../financial-model/double-entry.md)

## 1. Why float is forbidden for money

```python
>>> 0.1 + 0.2
0.30000000000000004
```

A `float` stores numbers in base 2, and `0.1` has no exact base-2 representation. A ledger performs millions of additions and these tiny errors accumulate. More importantly, two systems computing "the same" number may get two different answers.

**Waltrix's answer:** every amount is an **integer in minor units**: `1250` means 12.50 USD. `int` in Python, `BIGINT` in PostgreSQL, an integer in JSON.

```python
def validate_amount(amount: object, *, field: str = "amount") -> int:
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise ValidationFailed(...)
```

Why is `bool` checked separately? Because in Python `True` is an `int` (`isinstance(True, int) == True`). Without that line, `amount=True` would mean one cent!

### The 2^53 − 1 ceiling

JavaScript only has `number` (a 64-bit float), which holds integers exactly only up to `Number.MAX_SAFE_INTEGER = 2^53 − 1`. So Waltrix caps amounts at that value (`MAX_AMOUNT`). The result: the dashboard and the TypeScript SDK are exact without `BigInt` and without strings. Balances are `BIGINT` (up to 2^63), so there is room to sum.

### User input: a string, not a float

The user types `12.5`. Doing `Number("12.5") * 100` reaches `1249.9999` for some numbers. `packages/typescript-sdk/src/money.ts::parseMoney` works on the **string**: it splits the integer and fractional parts, pads the fraction to the currency exponent and joins them: `"12" + "50" → 1250`. If the user types more decimals than the currency allows (`12.345` dollars) the input is rejected, **not rounded**.

**Lesson:** rounding is a business decision, not an implementation detail. If you do not know how to round, reject.

## 2. The currency is always explicit

Every account has exactly one currency. Every posting has a currency. Every request has a currency. The allowed currencies are listed in `CURRENCY_EXPONENTS` (JPY exponent 0, USD exponent 2). "Any three letters will do" means that one day someone enters `USDT` or `usd `.

## 3. Double-entry accounting on one page

Every financial event changes at least **two** accounts, and total debits equal total credits. Money is never created from nothing and never disappears; it only moves.

| Account type | Normal side | Example in Waltrix |
| --- | --- | --- |
| Asset | debit | `system:simulated_funding`: money that came in from outside |
| Liability | credit | **every wallet**: what we owe the customer |
| Equity / revenue | credit | manual internal accounts |
| Expense | debit | manual internal accounts |

Why is a wallet a "liability"? Because from our point of view (the custodian), a customer balance is something we **owe** them. When a customer deposits, our assets go up (debit funding) and our liability to them goes up too (credit wallet).

```
deposit $100:    Dr simulated_funding 10000   |   Cr wallet:alice 10000
transfer $30:    Dr wallet:alice       3000   |   Cr wallet:bob    3000
```

### An invariant that follows from this model

Because money only enters through deposits and only leaves through withdrawals, for every currency it must always hold that:

```
debit balance of the funding account  ==  total liability to all wallets
```

Reconciliation checks exactly this (`funding_vs_wallets`). So "no money was created from nothing" is not a slogan; it is an SQL query.

## 4. The rules of a valid entry (`rules.validate_entry`)

1. At least two postings.
2. Every amount is a positive integer below the cap.
3. **Per currency**, debits = credits. So `Dr 100 USD / Cr 100 EUR` is rejected, even though "100 = 100"! That is the "hidden currency conversion" the brief forbids.
4. One account cannot be both debited and credited in the same entry (this is usually a sign of a bug).

## 5. How balances are stored

Instead of one `balance` column that can go up and down, every account has four **non-negative** totals:

```
posted_debits, posted_credits, pending_debits, pending_credits
```

and the balance is **derived** from them (`rules.signed_balance`, `available_balance`):

```
posted balance (credit-normal account) = posted_credits − posted_debits
available                              = posted_credits − posted_debits − pending_debits
```

The benefit: each column only grows (except when a hold is released), and it can be compared directly with the sum of the postings. Note that money **on its way in** (pending_credits) does not count as available.

## Exercises

1. In Python, try `sum([0.1] * 10) == 1.0`. Then with `Decimal` and with integers. Explain the results.
2. Compare `parseMoney("0.07", "USD")` with `Math.round(Number("0.07") * 100)` and with `Number("0.07") * 100`. Which inputs break the last approach?
3. Write the entry "charge a $2 fee from a wallet to a revenue account" as a Dr/Cr table. Does the funding_vs_wallets invariant still hold? (Hint: no! What must happen next?)
4. Why does `available_balance` subtract `pending_credits`, not `pending_debits`, for debit-normal accounts?
