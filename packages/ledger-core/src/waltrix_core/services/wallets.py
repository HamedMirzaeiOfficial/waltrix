"""Wallet and internal account management (non-financial mutations)."""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import Account, Hold, Wallet
from ..enums import NORMAL_BALANCE, AccountStatus, AccountType, HoldStatus, WalletStatus
from ..errors import Conflict, InvalidStateTransition, NotFound, ValidationFailed
from ..money import normalize_currency
from ..permissions import Permission
from . import audit
from .context import Actor
from .ledger import balance_view, get_or_create_default_ledger, now
from .runner import OperationResult, run_operation

WALLET_TRANSITIONS: dict[WalletStatus, frozenset[WalletStatus]] = {
    WalletStatus.ACTIVE: frozenset({WalletStatus.SUSPENDED, WalletStatus.CLOSED}),
    WalletStatus.SUSPENDED: frozenset({WalletStatus.ACTIVE, WalletStatus.CLOSED}),
    WalletStatus.CLOSED: frozenset(),
}


def _text(value: str, field: str, limit: int) -> str:
    value = (value or "").strip()
    if not value:
        raise ValidationFailed(f"{field} is required", field=field)
    if len(value) > limit:
        raise ValidationFailed(f"{field} must be at most {limit} characters", field=field)
    return value


def create_wallet(
    session: Session,
    actor: Actor,
    *,
    name: str,
    owner_reference: str,
    currency: str,
    metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> OperationResult:
    """Create a wallet and its backing liability account atomically."""
    actor.require(Permission.WALLETS_MANAGE)
    name = _text(name, "name", 120)
    owner_reference = _text(owner_reference, "owner_reference", 120)
    currency = normalize_currency(currency)
    metadata = metadata or {}
    payload = {"name": name, "owner_reference": owner_reference, "currency": currency, "metadata": metadata}

    def execute(s: Session) -> tuple[str, UUID]:
        ledger = get_or_create_default_ledger(s, actor.org_id)
        wallet_id = uuid.uuid4()
        account = Account(
            org_id=actor.org_id,
            ledger_id=ledger.id,
            code=f"wallet:{wallet_id}",
            name=f"Wallet - {name}",
            type=AccountType.LIABILITY,
            normal_balance=NORMAL_BALANCE[AccountType.LIABILITY],
            currency=currency,
            allow_negative=False,
            is_system=False,
        )
        s.add(account)
        s.flush()
        wallet = Wallet(
            id=wallet_id,
            org_id=actor.org_id,
            account_id=account.id,
            currency=currency,
            name=name,
            owner_reference=owner_reference,
            status=WalletStatus.ACTIVE,
            metadata_=metadata,
        )
        s.add(wallet)
        s.flush()
        audit.record(
            s,
            actor,
            "wallet.created",
            target_type="wallet",
            target_id=wallet.id,
            metadata={"currency": currency},
        )
        return "wallet", wallet.id

    return run_operation(
        session,
        actor,
        operation="wallet.create",
        payload=payload,
        idempotency_key=idempotency_key,
        execute=execute,
    )


def set_wallet_status(
    session: Session, actor: Actor, *, wallet_id: UUID, status: WalletStatus, reason: str | None = None
) -> Wallet:
    """Activate, suspend or close a wallet.

    ``FOR UPDATE`` on the wallet waits for in-flight money movements (which
    hold ``FOR SHARE``), so the change applies cleanly between operations.
    Closing requires a zero balance and no active holds.
    """
    actor.require(Permission.WALLETS_MANAGE)
    target = WalletStatus(status)
    with session.begin():
        wallet = (
            session.execute(
                select(Wallet)
                .where(Wallet.id == wallet_id, Wallet.org_id == actor.org_id)
                .with_for_update(of=Wallet)
                .execution_options(populate_existing=True)
            )
            .unique()
            .scalar_one_or_none()
        )
        if wallet is None:
            raise NotFound("wallet not found")
        current = WalletStatus(wallet.status)
        if target == current:
            return wallet
        if target not in WALLET_TRANSITIONS[current]:
            raise InvalidStateTransition(f"wallet cannot move from {current} to {target}")
        account = session.execute(
            select(Account)
            .where(Account.id == wallet.account_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one()
        if target is WalletStatus.CLOSED:
            view = balance_view(account)
            active_holds = session.execute(
                select(func.count())
                .select_from(Hold)
                .where(
                    Hold.status == HoldStatus.ACTIVE,
                    (Hold.wallet_id == wallet.id) | (Hold.destination_wallet_id == wallet.id),
                )
            ).scalar_one()
            if view["posted"] != 0 or active_holds:
                raise Conflict("only wallets with a zero balance and no active holds can be closed")
            account.status = AccountStatus.CLOSED
        wallet.status = target
        wallet.updated_at = now()
        audit.record(
            session,
            actor,
            f"wallet.{target}",
            target_type="wallet",
            target_id=wallet.id,
            metadata={"from": str(current), "reason": reason},
        )
    return wallet


def create_internal_account(
    session: Session,
    actor: Actor,
    *,
    code: str,
    name: str,
    type: AccountType,
    currency: str,
) -> Account:
    """Internal (non-wallet) account, e.g. ``revenue:fees``. Never allowed negative."""
    actor.require(Permission.ACCOUNTS_MANAGE)
    code = _text(code, "code", 120)
    if code.startswith(("wallet:", "system:")):
        raise ValidationFailed("codes starting with wallet: or system: are reserved", field="code")
    name = _text(name, "name", 200)
    currency = normalize_currency(currency)
    account_type = AccountType(type)
    with session.begin():
        ledger = get_or_create_default_ledger(session, actor.org_id)
        exists = session.execute(
            select(Account.id).where(
                Account.ledger_id == ledger.id, Account.code == code, Account.currency == currency
            )
        ).first()
        if exists:
            raise Conflict("an account with this code and currency already exists")
        account = Account(
            org_id=actor.org_id,
            ledger_id=ledger.id,
            code=code,
            name=name,
            type=account_type,
            normal_balance=NORMAL_BALANCE[account_type],
            currency=currency,
        )
        session.add(account)
        session.flush()
        audit.record(session, actor, "account.created", target_type="account", target_id=account.id)
    return account
