"""Response shapes (TypedDicts mirror the OpenAPI schema). Amounts are ``int`` minor units."""

from __future__ import annotations

from typing import Any, Generic, Literal, TypedDict, TypeVar

T = TypeVar("T")

TransactionStatus = Literal["created", "pending", "posted", "failed", "reversed"]
HoldStatus = Literal["active", "captured", "released", "expired"]
WalletStatus = Literal["active", "suspended", "closed"]


class Balance(TypedDict):
    currency: str
    posted: int
    pending_outgoing: int
    pending_incoming: int
    available: int


class Wallet(TypedDict):
    id: str
    name: str
    owner_reference: str
    currency: str
    status: WalletStatus
    account_id: str
    balance: Balance
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


class Transaction(TypedDict):
    id: str
    type: str
    status: TransactionStatus
    amount: int
    posted_amount: int | None
    reversed_amount: int
    currency: str
    source_wallet_id: str | None
    destination_wallet_id: str | None
    original_transaction_id: str | None
    description: str | None
    reference: str | None
    failure_code: str | None
    failure_message: str | None
    metadata: dict[str, Any]
    created_at: str
    posted_at: str | None


class Posting(TypedDict):
    line_no: int
    account_id: str
    account_code: str | None
    wallet_id: str | None
    direction: Literal["debit", "credit"]
    amount: int
    currency: str


class JournalEntry(TypedDict):
    id: str
    entry_number: int
    phase: Literal["pending", "posted"]
    kind: str
    description: str
    transaction_id: str | None
    reverses_entry_id: str | None
    created_at: str
    postings: list[Posting]


class TransactionDetail(Transaction):
    journal_entries: list[JournalEntry]
    reversals: list[Transaction]
    hold_id: str | None


class Hold(TypedDict):
    id: str
    wallet_id: str
    destination_wallet_id: str
    amount: int
    captured_amount: int | None
    currency: str
    status: HoldStatus
    transaction_id: str
    expires_at: str
    created_at: str


class ReconciliationRun(TypedDict):
    id: str
    status: Literal["passed", "failed"]
    summary: dict[str, Any]
    findings: list[dict[str, Any]]
    duration_ms: int
    created_at: str


class Page(TypedDict, Generic[T]):
    data: list[T]
    next_cursor: str | None
    has_more: bool
