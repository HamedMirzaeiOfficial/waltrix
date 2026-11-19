"""Financial operations. Every one runs through ``runner.run_operation``.

Global lock order (prevents deadlocks between different operation types)::

    idempotency key  ->  transaction / hold row  ->  wallets (by id)  ->  accounts (by id)

Wallet rows are locked ``FOR SHARE``: concurrent transfers do not block each
other on the wallet row, but a status change (``FOR UPDATE``) waits for them,
so a wallet cannot be suspended halfway through a transfer.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Account, Hold, JournalEntry, Transaction, Wallet
from ..enums import (
    Direction,
    EntryKind,
    EntryPhase,
    HoldStatus,
    TransactionStatus,
    TransactionType,
    WalletStatus,
)
from ..errors import (
    BusinessRuleViolation,
    CaptureExceedsHold,
    CurrencyMismatch,
    HoldExpired,
    HoldNotActive,
    LedgerInvariantViolation,
    NotFound,
    NotReversible,
    ReversalExceedsRemaining,
    SameWallet,
    ValidationFailed,
    WalletNotActive,
)
from ..money import normalize_currency, validate_amount
from ..permissions import Permission
from ..rules import Line, reversed_lines, validate_entry
from ..state_machine import check_hold_transition, check_transaction_transition
from . import audit
from .context import Actor
from .ledger import (
    ensure_funding_account,
    entry_lines,
    lock_accounts,
    now,
    post_entry,
    release_pending,
)
from .runner import OperationResult, run_operation

DEFAULT_HOLD_TTL = timedelta(days=7)
MAX_HOLD_TTL = timedelta(days=30)
REVERSIBLE_TYPES = {
    TransactionType.TRANSFER,
    TransactionType.DEPOSIT,
    TransactionType.WITHDRAWAL,
    TransactionType.HOLD,
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _clean_text(value: str | None, field: str, limit: int = 500) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if len(value) > limit:
        raise ValidationFailed(f"{field} must be at most {limit} characters", field=field)
    return value or None


def _lock_wallets(session: Session, org_id: UUID, ids: Sequence[UUID]) -> dict[UUID, Wallet]:
    unique = sorted(set(ids))
    rows = (
        session.execute(
            select(Wallet)
            .where(Wallet.org_id == org_id, Wallet.id.in_(unique))
            .order_by(Wallet.id)
            .with_for_update(read=True, of=Wallet)
            .execution_options(populate_existing=True)
        )
        .unique()
        .scalars()
        .all()
    )
    found = {w.id: w for w in rows}
    if len(found) != len(unique):
        raise NotFound("wallet not found")
    return found


def _require_active(*wallets: Wallet) -> None:
    for w in wallets:
        if w.status != WalletStatus.ACTIVE:
            raise WalletNotActive(f"wallet is {w.status}", wallet_id=str(w.id))


def _require_currency(currency: str, *wallets: Wallet) -> None:
    for w in wallets:
        if w.currency != currency:
            raise CurrencyMismatch(
                f"wallet currency is {w.currency}, request currency is {currency}",
                wallet_id=str(w.id),
            )


def _new_transaction(actor: Actor, **fields: Any) -> Transaction:
    return Transaction(
        org_id=actor.org_id,
        status=TransactionStatus.CREATED,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        correlation_id=actor.correlation_id,
        **fields,
    )


def _set_status(tx: Transaction, target: TransactionStatus) -> None:
    check_transaction_transition(TransactionStatus(tx.status), target)
    tx.status = target
    tx.updated_at = now()
    if target is TransactionStatus.POSTED:
        tx.posted_at = tx.updated_at


def _record_failed_transaction(
    session: Session, actor: Actor, err: BusinessRuleViolation, idempotency_key: str | None, **fields: Any
) -> tuple[str, UUID]:
    tx = _new_transaction(actor, idempotency_key=idempotency_key, **fields)
    _set_status(tx, TransactionStatus.FAILED)
    tx.failure_code = err.code
    tx.failure_message = err.message[:500]
    session.add(tx)
    session.flush()
    audit.record(
        session,
        actor,
        f"{fields['type']}.failed",
        target_type="transaction",
        target_id=tx.id,
        metadata={
            "failure_code": err.code,
            "amount": fields.get("amount"),
            "currency": fields.get("currency"),
        },
    )
    return "transaction", tx.id


# ---------------------------------------------------------------------------
# simple two-party movements
# ---------------------------------------------------------------------------


def _move(
    session: Session,
    actor: Actor,
    *,
    tx_type: TransactionType,
    operation: str,
    amount: int,
    currency: str,
    source_wallet_id: UUID | None,
    destination_wallet_id: UUID | None,
    description: str | None,
    reference: str | None,
    metadata: dict[str, Any] | None,
    idempotency_key: str | None,
) -> OperationResult:
    amount = validate_amount(amount)
    currency = normalize_currency(currency)
    description = _clean_text(description, "description")
    reference = _clean_text(reference, "reference", 120)
    metadata = metadata or {}
    payload = {
        "amount": amount,
        "currency": currency,
        "source_wallet_id": str(source_wallet_id) if source_wallet_id else None,
        "destination_wallet_id": str(destination_wallet_id) if destination_wallet_id else None,
        "description": description,
        "reference": reference,
        "metadata": metadata,
    }
    tx_fields = dict(
        type=tx_type,
        amount=amount,
        currency=currency,
        source_wallet_id=source_wallet_id,
        destination_wallet_id=destination_wallet_id,
        description=description,
        reference=reference,
        metadata_=metadata,
    )

    def execute(s: Session) -> tuple[str, UUID]:
        wallet_ids = [w for w in (source_wallet_id, destination_wallet_id) if w is not None]
        wallets = _lock_wallets(s, actor.org_id, wallet_ids)
        if source_wallet_id is not None and source_wallet_id == destination_wallet_id:
            raise SameWallet("source and destination wallets must differ")
        involved = list(wallets.values())
        _require_active(*involved)
        _require_currency(currency, *involved)

        # Build the two sides. Wallets are credit-normal liabilities: crediting
        # a wallet increases what we owe its owner.
        if tx_type is TransactionType.TRANSFER:
            debit_acc = wallets[source_wallet_id].account_id  # type: ignore[index]
            credit_acc = wallets[destination_wallet_id].account_id  # type: ignore[index]
            kind = EntryKind.TRANSFER
        elif tx_type is TransactionType.DEPOSIT:
            debit_acc = ensure_funding_account(s, actor.org_id, currency).id
            credit_acc = wallets[destination_wallet_id].account_id  # type: ignore[index]
            kind = EntryKind.DEPOSIT
        elif tx_type is TransactionType.WITHDRAWAL:
            debit_acc = wallets[source_wallet_id].account_id  # type: ignore[index]
            credit_acc = ensure_funding_account(s, actor.org_id, currency).id
            kind = EntryKind.WITHDRAWAL
        else:  # pragma: no cover - guarded by callers
            raise ValueError(tx_type)

        locked = lock_accounts(s, actor.org_id, [debit_acc, credit_acc])
        tx = _new_transaction(actor, idempotency_key=idempotency_key, **tx_fields)
        s.add(tx)
        s.flush()
        post_entry(
            s,
            actor,
            locked=locked,
            phase=EntryPhase.POSTED,
            kind=kind,
            description=description or f"{tx_type} {amount} {currency}",
            lines=[
                Line(debit_acc, Direction.DEBIT, amount, currency),
                Line(credit_acc, Direction.CREDIT, amount, currency),
            ],
            transaction_id=tx.id,
        )
        _set_status(tx, TransactionStatus.POSTED)
        tx.posted_amount = amount
        audit.record(
            s,
            actor,
            f"{tx_type}.posted",
            target_type="transaction",
            target_id=tx.id,
            metadata={"amount": amount, "currency": currency},
        )
        return "transaction", tx.id

    def on_failure(s: Session, err: BusinessRuleViolation) -> tuple[str, UUID]:
        return _record_failed_transaction(s, actor, err, idempotency_key, **tx_fields)

    return run_operation(
        session,
        actor,
        operation=operation,
        payload=payload,
        idempotency_key=idempotency_key,
        execute=execute,
        on_failure=on_failure,
    )


def transfer(
    session: Session,
    actor: Actor,
    *,
    source_wallet_id: UUID,
    destination_wallet_id: UUID,
    amount: int,
    currency: str,
    description: str | None = None,
    reference: str | None = None,
    metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> OperationResult:
    actor.require(Permission.MONEY_MOVE)
    return _move(
        session,
        actor,
        tx_type=TransactionType.TRANSFER,
        operation="transfer.create",
        amount=amount,
        currency=currency,
        source_wallet_id=source_wallet_id,
        destination_wallet_id=destination_wallet_id,
        description=description,
        reference=reference,
        metadata=metadata,
        idempotency_key=idempotency_key,
    )


def deposit(
    session: Session,
    actor: Actor,
    *,
    wallet_id: UUID,
    amount: int,
    currency: str,
    description: str | None = None,
    reference: str | None = None,
    metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> OperationResult:
    """Credit a wallet from the *simulated* funding source (demo only, no real bank)."""
    actor.require(Permission.MONEY_FUND)
    return _move(
        session,
        actor,
        tx_type=TransactionType.DEPOSIT,
        operation="wallet.credit",
        amount=amount,
        currency=currency,
        source_wallet_id=None,
        destination_wallet_id=wallet_id,
        description=description,
        reference=reference,
        metadata=metadata,
        idempotency_key=idempotency_key,
    )


def withdraw(
    session: Session,
    actor: Actor,
    *,
    wallet_id: UUID,
    amount: int,
    currency: str,
    description: str | None = None,
    reference: str | None = None,
    metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> OperationResult:
    """Debit a wallet back to the simulated funding source."""
    actor.require(Permission.MONEY_FUND)
    return _move(
        session,
        actor,
        tx_type=TransactionType.WITHDRAWAL,
        operation="wallet.debit",
        amount=amount,
        currency=currency,
        source_wallet_id=wallet_id,
        destination_wallet_id=None,
        description=description,
        reference=reference,
        metadata=metadata,
        idempotency_key=idempotency_key,
    )


# ---------------------------------------------------------------------------
# holds
# ---------------------------------------------------------------------------


def create_hold(
    session: Session,
    actor: Actor,
    *,
    wallet_id: UUID,
    destination_wallet_id: UUID,
    amount: int,
    currency: str,
    expires_in_seconds: int | None = None,
    description: str | None = None,
    idempotency_key: str | None = None,
) -> OperationResult:
    """Reserve funds: a PENDING entry moves pending balances only."""
    actor.require(Permission.MONEY_MOVE)
    amount = validate_amount(amount)
    currency = normalize_currency(currency)
    description = _clean_text(description, "description")
    ttl = DEFAULT_HOLD_TTL if expires_in_seconds is None else timedelta(seconds=expires_in_seconds)
    if ttl <= timedelta(0) or ttl > MAX_HOLD_TTL:
        raise ValidationFailed("expires_in_seconds must be between 1 and 30 days", field="expires_in_seconds")
    payload = {
        "wallet_id": str(wallet_id),
        "destination_wallet_id": str(destination_wallet_id),
        "amount": amount,
        "currency": currency,
        "expires_in_seconds": int(ttl.total_seconds()),
        "description": description,
    }
    tx_fields = dict(
        type=TransactionType.HOLD,
        amount=amount,
        currency=currency,
        source_wallet_id=wallet_id,
        destination_wallet_id=destination_wallet_id,
        description=description,
    )

    def execute(s: Session) -> tuple[str, UUID]:
        wallets = _lock_wallets(s, actor.org_id, [wallet_id, destination_wallet_id])
        if wallet_id == destination_wallet_id:
            raise SameWallet("source and destination wallets must differ")
        src, dst = wallets[wallet_id], wallets[destination_wallet_id]
        _require_active(src, dst)
        _require_currency(currency, src, dst)
        locked = lock_accounts(s, actor.org_id, [src.account_id, dst.account_id])
        tx = _new_transaction(actor, idempotency_key=idempotency_key, **tx_fields)
        s.add(tx)
        s.flush()
        entry = post_entry(
            s,
            actor,
            locked=locked,
            phase=EntryPhase.PENDING,
            kind=EntryKind.HOLD,
            description=description or f"hold {amount} {currency}",
            lines=[
                Line(src.account_id, Direction.DEBIT, amount, currency),
                Line(dst.account_id, Direction.CREDIT, amount, currency),
            ],
            transaction_id=tx.id,
        )
        _set_status(tx, TransactionStatus.PENDING)
        hold = Hold(
            org_id=actor.org_id,
            wallet_id=wallet_id,
            destination_wallet_id=destination_wallet_id,
            amount=amount,
            currency=currency,
            status=HoldStatus.ACTIVE,
            transaction_id=tx.id,
            pending_entry_id=entry.id,
            description=description,
            expires_at=now() + ttl,
        )
        s.add(hold)
        s.flush()
        audit.record(
            s,
            actor,
            "hold.created",
            target_type="hold",
            target_id=hold.id,
            metadata={"amount": amount, "currency": currency},
        )
        return "hold", hold.id

    def on_failure(s: Session, err: BusinessRuleViolation) -> tuple[str, UUID]:
        return _record_failed_transaction(s, actor, err, idempotency_key, **tx_fields)

    return run_operation(
        session,
        actor,
        operation="hold.create",
        payload=payload,
        idempotency_key=idempotency_key,
        execute=execute,
        on_failure=on_failure,
    )


def _lock_hold(session: Session, org_id: UUID, hold_id: UUID) -> Hold:
    hold = session.execute(
        select(Hold)
        .where(Hold.id == hold_id, Hold.org_id == org_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if hold is None:
        raise NotFound("hold not found")
    return hold


def _resolve_hold(
    s: Session, actor: Actor, hold: Hold, target: HoldStatus, capture_amount: int | None = None
) -> None:
    check_hold_transition(HoldStatus(hold.status), target)
    tx = s.execute(
        select(Transaction)
        .where(Transaction.id == hold.transaction_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    pending_entry = s.get_one(JournalEntry, hold.pending_entry_id)
    wallets = _lock_wallets(s, actor.org_id, [hold.wallet_id, hold.destination_wallet_id])
    src, dst = wallets[hold.wallet_id], wallets[hold.destination_wallet_id]
    if target is HoldStatus.CAPTURED:
        _require_active(src, dst)
    locked = lock_accounts(s, actor.org_id, [src.account_id, dst.account_id])
    release_pending(locked, pending_entry)
    if target is HoldStatus.CAPTURED:
        assert capture_amount is not None
        entry = post_entry(
            s,
            actor,
            locked=locked,
            phase=EntryPhase.POSTED,
            kind=EntryKind.CAPTURE,
            description=f"capture of hold {hold.id}",
            lines=[
                Line(src.account_id, Direction.DEBIT, capture_amount, hold.currency),
                Line(dst.account_id, Direction.CREDIT, capture_amount, hold.currency),
            ],
            transaction_id=tx.id,
        )
        hold.capture_entry_id = entry.id
        hold.captured_amount = capture_amount
        _set_status(tx, TransactionStatus.POSTED)
        tx.posted_amount = capture_amount
    else:
        s.flush()  # persist the pending release
        _set_status(tx, TransactionStatus.FAILED)
        tx.failure_code = "hold_released" if target is HoldStatus.RELEASED else "hold_expired"
        tx.failure_message = "the hold was released" if target is HoldStatus.RELEASED else "the hold expired"
    hold.status = target
    hold.resolved_at = now()
    s.flush()
    audit.record(
        s,
        actor,
        f"hold.{target}",
        target_type="hold",
        target_id=hold.id,
        metadata={"amount": hold.amount, "captured_amount": capture_amount, "currency": hold.currency},
    )


def capture_hold(
    session: Session,
    actor: Actor,
    *,
    hold_id: UUID,
    amount: int | None = None,
    idempotency_key: str | None = None,
) -> OperationResult:
    """Post a held amount (fully or partially). The remainder is released."""
    actor.require(Permission.MONEY_MOVE)
    if amount is not None:
        amount = validate_amount(amount)
    payload = {"hold_id": str(hold_id), "amount": amount}

    def execute(s: Session) -> tuple[str, UUID]:
        hold = _lock_hold(s, actor.org_id, hold_id)
        if hold.status != HoldStatus.ACTIVE:
            raise HoldNotActive(f"hold is {hold.status}")
        if hold.expires_at <= now():
            raise HoldExpired("hold has expired and can no longer be captured")
        capture = hold.amount if amount is None else amount
        if capture > hold.amount:
            raise CaptureExceedsHold("capture amount exceeds the held amount")
        _resolve_hold(s, actor, hold, HoldStatus.CAPTURED, capture)
        return "hold", hold.id

    return run_operation(
        session,
        actor,
        operation="hold.capture",
        payload=payload,
        idempotency_key=idempotency_key,
        execute=execute,
    )


def release_hold(
    session: Session, actor: Actor, *, hold_id: UUID, idempotency_key: str | None = None
) -> OperationResult:
    actor.require(Permission.MONEY_MOVE)

    def execute(s: Session) -> tuple[str, UUID]:
        hold = _lock_hold(s, actor.org_id, hold_id)
        if hold.status != HoldStatus.ACTIVE:
            raise HoldNotActive(f"hold is {hold.status}")
        _resolve_hold(s, actor, hold, HoldStatus.RELEASED)
        return "hold", hold.id

    return run_operation(
        session,
        actor,
        operation="hold.release",
        payload={"hold_id": str(hold_id)},
        idempotency_key=idempotency_key,
        execute=execute,
    )


def expire_holds(session: Session, *, as_of: datetime | None = None, limit: int = 100) -> int:
    """Expire overdue ACTIVE holds. Safe to run from several workers at once.

    ``FOR UPDATE SKIP LOCKED`` means two workers never pick the same hold and
    never block on each other. Each hold is expired in its own transaction, so
    a worker crash loses at most the hold it was working on (it stays ACTIVE
    and is picked up on the next run).
    """
    as_of = as_of or now()
    expired = 0
    for _ in range(limit):
        with session.begin():
            hold = session.execute(
                select(Hold)
                .where(Hold.status == HoldStatus.ACTIVE, Hold.expires_at <= as_of)
                .order_by(Hold.expires_at)
                .limit(1)
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if hold is None:
                break
            actor = Actor.system(hold.org_id, label="hold-expiry-worker")
            _resolve_hold(session, actor, hold, HoldStatus.EXPIRED)
            expired += 1
    return expired


# ---------------------------------------------------------------------------
# reversals
# ---------------------------------------------------------------------------


def reverse_transaction(
    session: Session,
    actor: Actor,
    *,
    transaction_id: UUID,
    amount: int | None = None,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> OperationResult:
    """Post a reversing entry. The original entry is never modified.

    ``amount`` < remaining gives a partial reversal (refund); the original
    stays POSTED with ``reversed_amount`` increased. A full reversal moves it
    to REVERSED. Reversals are allowed on suspended wallets (corrections must
    remain possible) but still respect overdraft rules: if the recipient has
    already spent the money the reversal fails with ``insufficient_funds``.
    """
    actor.require(Permission.MONEY_REVERSE)
    if amount is not None:
        amount = validate_amount(amount)
    reason = _clean_text(reason, "reason")
    payload = {"transaction_id": str(transaction_id), "amount": amount, "reason": reason}
    failure_fields: dict[str, Any] = {}

    def execute(s: Session) -> tuple[str, UUID]:
        original = s.execute(
            select(Transaction)
            .where(Transaction.id == transaction_id, Transaction.org_id == actor.org_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if original is None:
            raise NotFound("transaction not found")
        failure_fields.update(
            type=TransactionType.REVERSAL,
            amount=amount or max(original.posted_amount or original.amount, 1),
            currency=original.currency,
            source_wallet_id=original.destination_wallet_id,
            destination_wallet_id=original.source_wallet_id,
            original_transaction_id=original.id,
            description=reason,
        )
        if original.type not in REVERSIBLE_TYPES or original.status != TransactionStatus.POSTED:
            raise NotReversible(f"a {original.status} {original.type} cannot be reversed")
        assert original.posted_amount is not None
        remaining = original.posted_amount - original.reversed_amount
        to_reverse = remaining if amount is None else amount
        if to_reverse > remaining:
            raise ReversalExceedsRemaining(
                f"only {remaining} {original.currency} remains reversible", remaining=remaining
            )
        posted_entry = s.execute(
            select(JournalEntry).where(
                JournalEntry.transaction_id == original.id,
                JournalEntry.phase == EntryPhase.POSTED,
                JournalEntry.kind != EntryKind.REVERSAL,
            )
        ).scalar_one()
        lines = entry_lines(posted_entry)
        if any(ln.amount != original.posted_amount for ln in lines):
            raise NotReversible("only single-amount entries can be partially reversed")
        mirrored = [
            Line(ln.account_id, ln.direction, to_reverse, ln.currency) for ln in reversed_lines(lines)
        ]
        wallet_ids = [w for w in (original.source_wallet_id, original.destination_wallet_id) if w]
        _lock_wallets(s, actor.org_id, wallet_ids)
        locked = lock_accounts(s, actor.org_id, [ln.account_id for ln in mirrored])

        rev = _new_transaction(
            actor,
            idempotency_key=idempotency_key,
            **{**failure_fields, "amount": to_reverse},
        )
        s.add(rev)
        s.flush()
        post_entry(
            s,
            actor,
            locked=locked,
            phase=EntryPhase.POSTED,
            kind=EntryKind.REVERSAL,
            description=reason or f"reversal of transaction {original.id}",
            lines=mirrored,
            transaction_id=rev.id,
            reverses_entry_id=posted_entry.id,
            check_status=False,
        )
        _set_status(rev, TransactionStatus.POSTED)
        rev.posted_amount = to_reverse
        original.reversed_amount += to_reverse
        original.updated_at = now()
        if original.reversed_amount == original.posted_amount:
            _set_status(original, TransactionStatus.REVERSED)
        audit.record(
            s,
            actor,
            "transaction.reversed",
            target_type="transaction",
            target_id=original.id,
            metadata={"reversal_id": str(rev.id), "amount": to_reverse, "currency": original.currency},
        )
        return "transaction", rev.id

    def on_failure(s: Session, err: BusinessRuleViolation) -> tuple[str, UUID] | None:
        if not failure_fields:
            return None
        return _record_failed_transaction(s, actor, err, idempotency_key, **failure_fields)

    return run_operation(
        session,
        actor,
        operation="transaction.reverse",
        payload=payload,
        idempotency_key=idempotency_key,
        execute=execute,
        on_failure=on_failure,
    )


# ---------------------------------------------------------------------------
# manual entries (internal accounts only)
# ---------------------------------------------------------------------------


def post_manual_entry(
    session: Session,
    actor: Actor,
    *,
    description: str,
    lines: Sequence[dict[str, Any]],
    idempotency_key: str | None = None,
) -> OperationResult:
    """Balanced manual entry between *internal* accounts (e.g. fees -> revenue).

    Wallet and system accounts are excluded: customer balances change only
    through wallet operations, and the simulated funding account only through
    deposits/withdrawals. This keeps "no implicit money creation" checkable.
    """
    actor.require(Permission.LEDGER_MANUAL_ENTRY)
    desc = _clean_text(description, "description")
    if not desc:
        raise ValidationFailed("description is required", field="description")
    parsed: list[Line] = []
    for i, raw in enumerate(lines):
        try:
            parsed.append(
                Line(
                    UUID(str(raw["account_id"])),
                    Direction(raw["direction"]),
                    validate_amount(raw["amount"], field=f"lines[{i}].amount"),
                    normalize_currency(raw["currency"]),
                )
            )
        except (KeyError, ValueError) as exc:
            raise ValidationFailed(f"lines[{i}] is invalid", field=f"lines[{i}]") from exc
    try:
        validate_entry(parsed)
    except LedgerInvariantViolation as exc:
        raise ValidationFailed(exc.message, field="lines") from exc
    payload = {
        "description": desc,
        "lines": [[str(ln.account_id), ln.direction.value, ln.amount, ln.currency] for ln in parsed],
    }

    def execute(s: Session) -> tuple[str, UUID]:
        ids = [ln.account_id for ln in parsed]
        accounts = (
            s.execute(select(Account).where(Account.org_id == actor.org_id, Account.id.in_(ids)))
            .scalars()
            .all()
        )
        if len(accounts) != len(set(ids)):
            raise NotFound("account not found")
        wallet_backed = s.execute(select(Wallet.id).where(Wallet.account_id.in_(ids))).first()
        if wallet_backed or any(a.is_system for a in accounts):
            raise ValidationFailed("manual entries may only use internal, non-wallet, non-system accounts")
        locked = lock_accounts(s, actor.org_id, ids)
        entry = post_entry(
            s,
            actor,
            locked=locked,
            phase=EntryPhase.POSTED,
            kind=EntryKind.MANUAL,
            description=desc,
            lines=parsed,
        )
        audit.record(s, actor, "journal_entry.manual_posted", target_type="journal_entry", target_id=entry.id)
        return "journal_entry", entry.id

    return run_operation(
        session,
        actor,
        operation="journal_entry.manual",
        payload=payload,
        idempotency_key=idempotency_key,
        execute=execute,
    )
