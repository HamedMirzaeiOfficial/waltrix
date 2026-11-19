"""Pure double-entry rules, independent of the database.

The engine validates every journal entry with ``validate_entry`` before it
touches the database. PostgreSQL then re-checks the same invariant with a
deferred constraint trigger at COMMIT time (see migration 0001) so a bug in
this module cannot commit an unbalanced entry either.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from uuid import UUID

from .enums import Direction, NormalBalance
from .errors import LedgerInvariantViolation
from .money import MAX_AMOUNT, normalize_currency


@dataclass(frozen=True, slots=True)
class Line:
    """One posting before it is persisted."""

    account_id: UUID
    direction: Direction
    amount: int
    currency: str


def validate_entry(lines: Sequence[Line]) -> None:
    """Raise ``LedgerInvariantViolation`` unless ``lines`` form a valid balanced entry.

    Rules:
      * at least two lines;
      * every amount is a positive integer within limits;
      * for **each currency separately**, total debits == total credits
        (no cross-currency netting, so no silent FX);
      * no account is both debited and credited in the same entry
        (that would be a no-op line pair hiding intent).
    """
    if len(lines) < 2:
        raise LedgerInvariantViolation("a journal entry needs at least two postings")
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    sides: dict[UUID, set[Direction]] = defaultdict(set)
    for line in lines:
        if isinstance(line.amount, bool) or not isinstance(line.amount, int):
            raise LedgerInvariantViolation("posting amounts must be integers")
        if line.amount <= 0 or line.amount > MAX_AMOUNT:
            raise LedgerInvariantViolation("posting amounts must be positive and within limits")
        currency = normalize_currency(line.currency)
        idx = 0 if line.direction is Direction.DEBIT else 1
        totals[currency][idx] += line.amount
        sides[line.account_id].add(line.direction)
    for currency, (debits, credits) in totals.items():
        if debits != credits:
            raise LedgerInvariantViolation(
                f"entry does not balance in {currency}: debits {debits} != credits {credits}",
                currency=currency,
            )
    for account_id, dirs in sides.items():
        if len(dirs) > 1:
            raise LedgerInvariantViolation(
                "an account cannot be debited and credited in the same entry",
                account_id=str(account_id),
            )


def reversed_lines(lines: Iterable[Line]) -> list[Line]:
    """Mirror image of an entry: every debit becomes a credit and vice versa."""
    flip = {Direction.DEBIT: Direction.CREDIT, Direction.CREDIT: Direction.DEBIT}
    return [Line(ln.account_id, flip[ln.direction], ln.amount, ln.currency) for ln in lines]


def signed_balance(normal: NormalBalance, debits: int, credits: int) -> int:
    """Balance in the account's natural sign (positive = normal side)."""
    return debits - credits if normal is NormalBalance.DEBIT else credits - debits


def available_balance(
    normal: NormalBalance,
    posted_debits: int,
    posted_credits: int,
    pending_debits: int,
    pending_credits: int,
) -> int:
    """Spendable balance: posted balance minus outgoing holds.

    Incoming pending amounts are deliberately *not* counted: money on its way
    in is not money you can spend yet.
    """
    if normal is NormalBalance.CREDIT:
        return posted_credits - posted_debits - pending_debits
    return posted_debits - posted_credits - pending_credits
