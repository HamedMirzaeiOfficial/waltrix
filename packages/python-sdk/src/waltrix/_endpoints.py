"""Endpoint definitions shared by the sync and async clients.

Each function validates arguments and returns a ``Spec`` describing one HTTP
request. Money-moving specs carry an idempotency key that is generated *once*
here, so every retry of that call reuses the same key.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar
from urllib.parse import quote

from .types import (
    Balance,
    Hold,
    JournalEntry,
    Page,
    ReconciliationRun,
    Transaction,
    TransactionDetail,
    Wallet,
)

T = TypeVar("T")
MAX_SAFE_INTEGER = 2**53 - 1


@dataclass(frozen=True)
class Spec(Generic[T]):
    method: str
    path: str
    json: dict[str, Any] | None = None
    params: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None

    @property
    def retry_safe(self) -> bool:
        """GETs are safe; POSTs only when protected by an idempotency key."""
        return self.method == "GET" or self.idempotency_key is not None


def _seg(value: str) -> str:
    value = str(value)
    if not value or "/" in value:
        raise ValueError("invalid identifier")
    return quote(value, safe="")


def _amount(value: int, name: str = "amount") -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int number of minor units (never a float)")
    if not 0 < value <= MAX_SAFE_INTEGER:
        raise ValueError(f"{name} must be between 1 and 2**53-1")
    return value


def _key(key: str | None) -> str:
    return key or str(uuid.uuid4())


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


# --- wallets --------------------------------------------------------------------


def create_wallet(
    name: str,
    owner_reference: str,
    currency: str,
    *,
    metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> Spec[Wallet]:
    body = _clean(
        {"name": name, "owner_reference": owner_reference, "currency": currency, "metadata": metadata}
    )
    return Spec("POST", "/wallets", body, idempotency_key=_key(idempotency_key))


def get_wallet(wallet_id: str) -> Spec[Wallet]:
    return Spec("GET", f"/wallets/{_seg(wallet_id)}")


def list_wallets(
    *,
    limit: int = 25,
    cursor: str | None = None,
    status: str | None = None,
    currency: str | None = None,
    search: str | None = None,
) -> Spec[Page[Wallet]]:
    return Spec(
        "GET",
        "/wallets",
        params=_clean(
            {"limit": limit, "cursor": cursor, "status": status, "currency": currency, "search": search}
        ),
    )


def get_balance(wallet_id: str) -> Spec[Balance]:
    return Spec("GET", f"/wallets/{_seg(wallet_id)}/balance")


def _funding(
    kind: str,
    wallet_id: str,
    amount: int,
    currency: str,
    description: str | None,
    reference: str | None,
    idempotency_key: str | None,
) -> Spec[Transaction]:
    body = _clean(
        {"amount": _amount(amount), "currency": currency, "description": description, "reference": reference}
    )
    return Spec("POST", f"/wallets/{_seg(wallet_id)}/{kind}", body, idempotency_key=_key(idempotency_key))


def credit_wallet(
    wallet_id: str,
    amount: int,
    currency: str,
    *,
    description: str | None = None,
    reference: str | None = None,
    idempotency_key: str | None = None,
) -> Spec[Transaction]:
    """Fund a wallet from the server's SIMULATED funding source."""
    return _funding("credit", wallet_id, amount, currency, description, reference, idempotency_key)


def debit_wallet(
    wallet_id: str,
    amount: int,
    currency: str,
    *,
    description: str | None = None,
    reference: str | None = None,
    idempotency_key: str | None = None,
) -> Spec[Transaction]:
    return _funding("debit", wallet_id, amount, currency, description, reference, idempotency_key)


def suspend_wallet(wallet_id: str, *, reason: str | None = None) -> Spec[Wallet]:
    return Spec("POST", f"/wallets/{_seg(wallet_id)}/suspend", _clean({"reason": reason}))


def activate_wallet(wallet_id: str) -> Spec[Wallet]:
    return Spec("POST", f"/wallets/{_seg(wallet_id)}/activate", {})


def wallet_statement(
    wallet_id: str, *, start: str | None = None, end: str | None = None
) -> Spec[dict[str, Any]]:
    return Spec("GET", f"/wallets/{_seg(wallet_id)}/statement", params=_clean({"start": start, "end": end}))


# --- transfers & transactions -----------------------------------------------------------


def create_transfer(
    source_wallet_id: str,
    destination_wallet_id: str,
    amount: int,
    currency: str,
    *,
    description: str | None = None,
    reference: str | None = None,
    metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> Spec[Transaction]:
    body = _clean(
        {
            "source_wallet_id": source_wallet_id,
            "destination_wallet_id": destination_wallet_id,
            "amount": _amount(amount),
            "currency": currency,
            "description": description,
            "reference": reference,
            "metadata": metadata,
        }
    )
    return Spec("POST", "/transfers", body, idempotency_key=_key(idempotency_key))


def get_transaction(transaction_id: str) -> Spec[TransactionDetail]:
    return Spec("GET", f"/transactions/{_seg(transaction_id)}")


def list_transactions(
    *,
    limit: int = 25,
    cursor: str | None = None,
    status: str | None = None,
    type: str | None = None,
    wallet_id: str | None = None,
    currency: str | None = None,
    search: str | None = None,
    sort: str = "-created_at",
) -> Spec[Page[Transaction]]:
    params = {
        "limit": limit,
        "cursor": cursor,
        "status": status,
        "type": type,
        "wallet_id": wallet_id,
        "currency": currency,
        "search": search,
        "sort": sort,
    }
    return Spec("GET", "/transactions", params=_clean(params))


# --- holds -----------------------------------------------------------------------------------


def create_hold(
    wallet_id: str,
    destination_wallet_id: str,
    amount: int,
    currency: str,
    *,
    expires_in_seconds: int | None = None,
    description: str | None = None,
    idempotency_key: str | None = None,
) -> Spec[Hold]:
    body = _clean(
        {
            "wallet_id": wallet_id,
            "destination_wallet_id": destination_wallet_id,
            "amount": _amount(amount),
            "currency": currency,
            "expires_in_seconds": expires_in_seconds,
            "description": description,
        }
    )
    return Spec("POST", "/holds", body, idempotency_key=_key(idempotency_key))


def get_hold(hold_id: str) -> Spec[Hold]:
    return Spec("GET", f"/holds/{_seg(hold_id)}")


def list_holds(
    *, limit: int = 25, cursor: str | None = None, status: str | None = None, wallet_id: str | None = None
) -> Spec[Page[Hold]]:
    return Spec(
        "GET",
        "/holds",
        params=_clean({"limit": limit, "cursor": cursor, "status": status, "wallet_id": wallet_id}),
    )


def capture_hold(
    hold_id: str, *, amount: int | None = None, idempotency_key: str | None = None
) -> Spec[Hold]:
    body = _clean({"amount": _amount(amount) if amount is not None else None})
    return Spec("POST", f"/holds/{_seg(hold_id)}/capture", body, idempotency_key=_key(idempotency_key))


def release_hold(hold_id: str, *, idempotency_key: str | None = None) -> Spec[Hold]:
    return Spec("POST", f"/holds/{_seg(hold_id)}/release", {}, idempotency_key=_key(idempotency_key))


# --- reversals, journal, reconciliation, audit ------------------------------------------------


def create_reversal(
    transaction_id: str,
    *,
    amount: int | None = None,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> Spec[Transaction]:
    body = _clean(
        {
            "transaction_id": transaction_id,
            "amount": _amount(amount) if amount is not None else None,
            "reason": reason,
        }
    )
    return Spec("POST", "/reversals", body, idempotency_key=_key(idempotency_key))


def list_journal_entries(
    *,
    limit: int = 25,
    cursor: str | None = None,
    kind: str | None = None,
    phase: str | None = None,
    account_id: str | None = None,
) -> Spec[Page[JournalEntry]]:
    params = {"limit": limit, "cursor": cursor, "kind": kind, "phase": phase, "account_id": account_id}
    return Spec("GET", "/journal-entries", params=_clean(params))


def get_journal_entry(entry_id: str) -> Spec[JournalEntry]:
    return Spec("GET", f"/journal-entries/{_seg(entry_id)}")


def run_reconciliation() -> Spec[ReconciliationRun]:
    return Spec("POST", "/reconciliation/runs", {})


def list_reconciliation_runs(*, limit: int = 20, cursor: str | None = None) -> Spec[Page[ReconciliationRun]]:
    return Spec("GET", "/reconciliation/runs", params=_clean({"limit": limit, "cursor": cursor}))


def list_audit_events(
    *, limit: int = 50, cursor: str | None = None, action: str | None = None, target_id: str | None = None
) -> Spec[Page[dict[str, Any]]]:
    params = {"limit": limit, "cursor": cursor, "action": action, "target_id": target_id}
    return Spec("GET", "/audit-events", params=_clean(params))
