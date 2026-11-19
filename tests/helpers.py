"""Small helpers shared by integration and concurrency tests."""

from __future__ import annotations

import uuid
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from waltrix_core.db.models import Account, Wallet
from waltrix_core.services import operations, wallets
from waltrix_core.services.context import Actor
from waltrix_core.services.ledger import balance_view


def new_wallet(session: Session, actor: Actor, currency: str = "USD", funded: int = 0, name: str = "w") -> UUID:
    res = wallets.create_wallet(
        session, actor, name=name, owner_reference=f"cust_{uuid.uuid4().hex[:6]}", currency=currency
    )
    assert res.succeeded and res.resource_id
    if funded:
        dep = operations.deposit(session, actor, wallet_id=res.resource_id, amount=funded, currency=currency)
        assert dep.succeeded, dep
    return res.resource_id


def balance(session: Session, wallet_id: UUID) -> dict[str, int]:
    session.expire_all()
    w = session.get_one(Wallet, wallet_id)
    acc = session.get_one(Account, w.account_id, populate_existing=True)
    session.commit()
    return balance_view(acc)


def total_wallet_liabilities(session: Session, org_id: UUID, currency: str) -> int:
    value = session.execute(
        select(func.coalesce(func.sum(Account.posted_credits - Account.posted_debits), 0))
        .join(Wallet, Wallet.account_id == Account.id)
        .where(Wallet.org_id == org_id, Wallet.currency == currency)
    ).scalar_one()
    session.commit()
    return int(value)
