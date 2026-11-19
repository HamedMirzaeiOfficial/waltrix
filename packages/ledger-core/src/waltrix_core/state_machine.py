"""Explicit state machines.

Transactions and holds have *different* lifecycles; they are not forced into
one shared machine. Every status change in the engine goes through
``transition_*`` so an illegal move fails loudly instead of corrupting history.

Transaction lifecycle::

    CREATED ──► POSTED ──► REVERSED          (transfer / deposit / withdrawal)
       │  └───► FAILED                       (business rule rejected it)
       └──► PENDING ──► POSTED               (hold captured)
               └──────► FAILED               (hold released or expired)

``CREATED`` exists only inside the database transaction that creates the
record; the engine is synchronous, so callers observe a terminal state or
PENDING. A POSTED transaction becomes REVERSED only once it is *fully*
reversed; partial reversals (refunds) leave it POSTED with ``reversed_amount``.

Hold lifecycle::

    ACTIVE ──► CAPTURED | RELEASED | EXPIRED   (all terminal)
"""

from __future__ import annotations

from .enums import HoldStatus, TransactionStatus
from .errors import InvalidStateTransition

TS = TransactionStatus
TRANSACTION_TRANSITIONS: dict[TransactionStatus, frozenset[TransactionStatus]] = {
    TS.CREATED: frozenset({TS.PENDING, TS.POSTED, TS.FAILED}),
    TS.PENDING: frozenset({TS.POSTED, TS.FAILED}),
    TS.POSTED: frozenset({TS.REVERSED}),
    TS.FAILED: frozenset(),
    TS.REVERSED: frozenset(),
}

HS = HoldStatus
HOLD_TRANSITIONS: dict[HoldStatus, frozenset[HoldStatus]] = {
    HS.ACTIVE: frozenset({HS.CAPTURED, HS.RELEASED, HS.EXPIRED}),
    HS.CAPTURED: frozenset(),
    HS.RELEASED: frozenset(),
    HS.EXPIRED: frozenset(),
}


def check_transaction_transition(current: TransactionStatus, target: TransactionStatus) -> None:
    if target not in TRANSACTION_TRANSITIONS[TransactionStatus(current)]:
        raise InvalidStateTransition(
            f"transaction cannot move from {current} to {target}",
            current=str(current),
            target=str(target),
        )


def check_hold_transition(current: HoldStatus, target: HoldStatus) -> None:
    if target not in HOLD_TRANSITIONS[HoldStatus(current)]:
        raise InvalidStateTransition(
            f"hold cannot move from {current} to {target}",
            current=str(current),
            target=str(target),
        )
