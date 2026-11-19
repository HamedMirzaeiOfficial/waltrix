# ADR 0002: Integer minor units everywhere

**Status:** accepted

**Decision.** Amounts are integers in the currency's minor unit (`1250` = 12.50 USD) in Python (`int`),
PostgreSQL (`BIGINT`) and JSON. Amounts are capped at 2^53-1 so JavaScript `number` is exact. The UI parses
the decimal *string* a user typed into minor units (`parseMoney`) and formats from integers; it never does
float arithmetic on money. Currency is explicit on every account, posting and request, and supported
currencies (with ISO 4217 exponents) are an allow-list.

**Rejected.** `NUMERIC`/`Decimal`: correct but invites "just a little rounding" in application code, and
JSON has no decimal type, so clients would parse floats anyway. Strings on the wire: safe but clumsy for
every client; the 2^53 cap removes the need.
