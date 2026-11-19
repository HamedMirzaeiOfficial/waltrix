"""Wallets: management, balances, statements and simulated funding."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from waltrix_core.enums import WalletStatus
from waltrix_core.services import operations, queries, wallets
from waltrix_core.services.context import Actor

from .. import presenters
from .. import schemas as s
from ..deps import current_actor, get_db, idempotency_key, optional_idempotency_key
from .ledger import statement_out

router = APIRouter(prefix="/wallets", tags=["wallets"])

Limit = Annotated[int, Query(ge=1, le=100)]


def _load_wallet(db: Session, actor: Actor, wid: UUID) -> s.WalletOut:
    return presenters.wallet(queries.get_wallet(db, actor, wid))


def _load_tx(db: Session, actor: Actor, tid: UUID) -> s.TransactionOut:
    return presenters.transaction(queries.get_transaction(db, actor, tid))


@router.get("", response_model=s.PageOut[s.WalletOut])
def list_wallets(
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    limit: Limit = 25,
    cursor: str | None = None,
    status: WalletStatus | None = None,
    currency: str | None = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
):
    return presenters.page(
        queries.list_wallets(
            db, actor, limit=limit, cursor=cursor, status=status, currency=currency, search=search
        ),
        presenters.wallet,
    )


@router.post("", response_model=s.WalletOut, status_code=201)
def create_wallet(
    body: s.WalletIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    key: str | None = Depends(optional_idempotency_key),
) -> JSONResponse:
    result = wallets.create_wallet(
        db,
        actor,
        name=body.name,
        owner_reference=body.owner_reference,
        currency=body.currency,
        metadata=body.metadata,
        idempotency_key=key,
    )
    return presenters.operation_response(db, actor, result, _load_wallet)


@router.get("/{wallet_id}", response_model=s.WalletOut)
def get_wallet(wallet_id: UUID, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    return _load_wallet(db, actor, wallet_id)


@router.get("/{wallet_id}/balance", response_model=s.BalanceOut)
def get_balance(wallet_id: UUID, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    return presenters.balance(queries.get_wallet(db, actor, wallet_id).account)


def _status_route(target: WalletStatus):  # type: ignore[no-untyped-def]
    def handler(
        wallet_id: UUID,
        body: s.WalletStatusIn | None = None,
        db: Session = Depends(get_db),
        actor: Actor = Depends(current_actor),
    ) -> s.WalletOut:
        db.commit()
        wallets.set_wallet_status(
            db, actor, wallet_id=wallet_id, status=target, reason=body.reason if body else None
        )
        return _load_wallet(db, actor, wallet_id)

    return handler


router.add_api_route(
    "/{wallet_id}/activate",
    _status_route(WalletStatus.ACTIVE),
    methods=["POST"],
    response_model=s.WalletOut,
    summary="Activate wallet",
)
router.add_api_route(
    "/{wallet_id}/suspend",
    _status_route(WalletStatus.SUSPENDED),
    methods=["POST"],
    response_model=s.WalletOut,
    summary="Suspend wallet",
)
router.add_api_route(
    "/{wallet_id}/close",
    _status_route(WalletStatus.CLOSED),
    methods=["POST"],
    response_model=s.WalletOut,
    summary="Close wallet (zero balance, no active holds)",
)


@router.post(
    "/{wallet_id}/credit",
    response_model=s.TransactionOut,
    status_code=201,
    summary="Credit a wallet from the SIMULATED funding source",
)
def credit(
    wallet_id: UUID,
    body: s.FundingIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    key: str = Depends(idempotency_key),
) -> JSONResponse:
    result = operations.deposit(
        db,
        actor,
        wallet_id=wallet_id,
        amount=body.amount,
        currency=body.currency,
        description=body.description,
        reference=body.reference,
        metadata=body.metadata,
        idempotency_key=key,
    )
    return presenters.operation_response(db, actor, result, _load_tx)


@router.post(
    "/{wallet_id}/debit",
    response_model=s.TransactionOut,
    status_code=201,
    summary="Debit a wallet back to the SIMULATED funding source",
)
def debit(
    wallet_id: UUID,
    body: s.FundingIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    key: str = Depends(idempotency_key),
) -> JSONResponse:
    result = operations.withdraw(
        db,
        actor,
        wallet_id=wallet_id,
        amount=body.amount,
        currency=body.currency,
        description=body.description,
        reference=body.reference,
        metadata=body.metadata,
        idempotency_key=key,
    )
    return presenters.operation_response(db, actor, result, _load_tx)


@router.get("/{wallet_id}/statement", response_model=s.StatementOut)
def wallet_statement(
    wallet_id: UUID,
    start: datetime | None = None,
    end: datetime | None = None,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    w = queries.get_wallet(db, actor, wallet_id)
    return statement_out(queries.statement(db, actor, w.account_id, start=start, end=end), start, end)
