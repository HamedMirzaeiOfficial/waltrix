"""Enumerations shared by the domain, the database and the API.

They are ``StrEnum`` so the stored database value equals the wire value.
"""

from __future__ import annotations

from enum import StrEnum


class AccountType(StrEnum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"


class NormalBalance(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


NORMAL_BALANCE: dict[AccountType, NormalBalance] = {
    AccountType.ASSET: NormalBalance.DEBIT,
    AccountType.EXPENSE: NormalBalance.DEBIT,
    AccountType.LIABILITY: NormalBalance.CREDIT,
    AccountType.EQUITY: NormalBalance.CREDIT,
    AccountType.REVENUE: NormalBalance.CREDIT,
}


class Direction(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


class AccountStatus(StrEnum):
    ACTIVE = "active"
    FROZEN = "frozen"
    CLOSED = "closed"


class WalletStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class EntryPhase(StrEnum):
    """PENDING entries move pending balances (holds); POSTED entries move posted balances."""

    PENDING = "pending"
    POSTED = "posted"


class EntryKind(StrEnum):
    TRANSFER = "transfer"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    HOLD = "hold"
    CAPTURE = "capture"
    REVERSAL = "reversal"
    MANUAL = "manual"


class TransactionType(StrEnum):
    TRANSFER = "transfer"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    HOLD = "hold"
    REVERSAL = "reversal"


class TransactionStatus(StrEnum):
    CREATED = "created"
    PENDING = "pending"
    POSTED = "posted"
    FAILED = "failed"
    REVERSED = "reversed"


class HoldStatus(StrEnum):
    ACTIVE = "active"
    CAPTURED = "captured"
    RELEASED = "released"
    EXPIRED = "expired"


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    FINANCE_OPERATOR = "finance_operator"
    AUDITOR = "auditor"
    VIEWER = "viewer"


class ActorType(StrEnum):
    USER = "user"
    API_KEY = "api_key"
    SYSTEM = "system"


class ReconciliationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
