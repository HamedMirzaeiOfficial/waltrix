"""Money primitives.

All monetary amounts in Waltrix are integers in the currency's *minor unit*
(cents for USD, yen for JPY). Floats never appear anywhere in the money path:
not in the database (BIGINT), not in the engine (``int``), and not on the wire
(JSON integers).

Amounts are capped at ``MAX_AMOUNT`` (2**53 - 1) so that they survive a round
trip through JavaScript ``number`` without precision loss. Account balances are
stored in BIGINT columns, which leaves ~1000x headroom above that cap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from .errors import ValidationFailed

MAX_AMOUNT = 2**53 - 1

# ISO 4217 minor-unit exponents for the currencies this build supports.
# Supporting a new currency is a deliberate change, not free text.
CURRENCY_EXPONENTS: dict[str, int] = {
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "CHF": 2,
    "CAD": 2,
    "AUD": 2,
    "AED": 2,
    "IRR": 2,
    "JPY": 0,
    "KRW": 0,
}

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def normalize_currency(code: str) -> str:
    """Validate a currency code against the supported list and return it upper-cased."""
    if not isinstance(code, str):
        raise ValidationFailed("currency must be a string", field="currency")
    upper = code.strip().upper()
    if not _CURRENCY_RE.match(upper):
        raise ValidationFailed("currency must be a 3-letter ISO 4217 code", field="currency")
    if upper not in CURRENCY_EXPONENTS:
        raise ValidationFailed(f"currency {upper} is not supported", field="currency")
    return upper


def validate_amount(amount: object, *, field: str = "amount") -> int:
    """Return ``amount`` if it is a strictly positive integer within ``MAX_AMOUNT``.

    ``bool`` is rejected explicitly because ``True`` is an ``int`` in Python.
    """
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise ValidationFailed(f"{field} must be an integer number of minor units", field=field)
    if amount <= 0:
        raise ValidationFailed(f"{field} must be greater than zero", field=field)
    if amount > MAX_AMOUNT:
        raise ValidationFailed(f"{field} exceeds the maximum supported amount", field=field)
    return amount


@dataclass(frozen=True, slots=True)
class Money:
    """An immutable (amount, currency) pair. Arithmetic refuses to mix currencies."""

    amount: int
    currency: str

    def __post_init__(self) -> None:
        if isinstance(self.amount, bool) or not isinstance(self.amount, int):
            raise TypeError("Money.amount must be int (minor units)")
        object.__setattr__(self, "currency", normalize_currency(self.currency))

    def _check(self, other: Money) -> None:
        if not isinstance(other, Money):
            raise TypeError("can only combine Money with Money")
        if other.currency != self.currency:
            raise ValueError(f"currency mismatch: {self.currency} vs {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount - other.amount, self.currency)

    def format(self) -> str:
        """Human-readable string, e.g. ``"12.50 USD"``. Display only."""
        exp = CURRENCY_EXPONENTS[self.currency]
        value = Decimal(self.amount).scaleb(-exp)
        return f"{value:,.{exp}f} {self.currency}"
