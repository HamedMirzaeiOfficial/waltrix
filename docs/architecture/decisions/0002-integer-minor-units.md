# ADR 0002: Integer minor units everywhere

**English** · [فارسی](../../fa/architecture/decisions/0002-integer-minor-units.md)

**Status:** accepted

**Context.** Money crosses four runtimes: Python, PostgreSQL, JSON on the wire, and JavaScript in the
dashboard and the TypeScript SDK. Binary floating point cannot represent most decimal fractions
(`0.1 + 0.2 ≠ 0.3`), and the errors accumulate over millions of postings. Worse, two systems computing
"the same" amount with floats can disagree, which a ledger cannot tolerate.

**Decision.** Amounts are integers in the currency's minor unit (`1250` = 12.50 USD) in Python (`int`),
PostgreSQL (`BIGINT`) and JSON. Amounts are capped at 2^53-1 so JavaScript `number` is exact. The UI parses
the decimal *string* a user typed into minor units (`parseMoney`) and formats from integers; it never does
float arithmetic on money. Currency is explicit on every account, posting and request, and supported
currencies (with ISO 4217 exponents) are an allow-list. Input with more decimals than the currency allows
is rejected, never rounded.

**Rejected.** `NUMERIC`/`Decimal`: correct but invites "just a little rounding" in application code, and
JSON has no decimal type, so clients would parse floats anyway. Strings on the wire: safe but clumsy for
every client; the 2^53 cap removes the need.

**Consequences.** Every client must know each currency's exponent to display amounts (the SDKs ship the
table). A single amount cannot exceed about 90 trillion USD, which is far beyond any realistic transfer;
balances are `BIGINT` and can grow further. Display formatting (including Persian digits) is a pure
presentation step on top of integers, so localisation can never change an amount.
