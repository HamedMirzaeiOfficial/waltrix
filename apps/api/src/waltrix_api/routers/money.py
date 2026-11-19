"""Money movement: transfers, holds, reversals, and transaction history."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from waltrix_core.enums import HoldStatus, TransactionStatus, TransactionType
from waltrix_core.services import operations, queries
from waltrix_core.services.context import Actor

from .. import presenters
from .. import schemas as s
from ..deps import current_actor, get_db, idempotency_key

router = APIRouter()
Limit = Annotated[int, Query(ge=1, le=100)]


def _load_tx(db: Session, actor: Actor, tid: UUID) -> s.TransactionOut:
    return presenters.transaction(queries.get_transaction(db, actor, tid))


def _load_hold(db: Session, actor: Actor, hid: UUID) -> s.HoldOut:
    return presenters.hold(queries.get_hold(db, actor, hid))


# --- transfers ------------------------------------------------------------------


@router.post(
    "/transfers",
    response_model=s.TransactionOut,
    status_code=201,
    tags=["transfers"],
    responses={422: {"description": "Business rule rejected the transfer (recorded as FAILED)"}},
)
def create_transfer(
    body: s.TransferIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    key: str = Depends(idempotency_key),
) -> JSONResponse:
    result = operations.transfer(
        db,
        actor,
        source_wallet_id=body.source_wallet_id,
        destination_wallet_id=body.destination_wallet_id,
        amount=body.amount,
        currency=body.currency,
        description=body.description,
        reference=body.reference,
        metadata=body.metadata,
        idempotency_key=key,
    )
    return presenters.operation_response(db, actor, result, _load_tx)


@router.get("/transfers/{transaction_id}", response_model=s.TransactionDetailOut, tags=["transfers"])
def get_transfer(transaction_id: UUID, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    return presenters.transaction_detail(db, actor, queries.get_transaction(db, actor, transaction_id))


# --- transactions -------------------------------------------------------------------


@router.get("/transactions", response_model=s.PageOut[s.TransactionOut], tags=["transactions"])
def list_transactions(
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    limit: Limit = 25,
    cursor: str | None = None,
    status: TransactionStatus | None = None,
    type: TransactionType | None = None,
    wallet_id: UUID | None = None,
    currency: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    search: Annotated[str | None, Query(max_length=120)] = None,
    sort: Annotated[str, Query(pattern="^-?created_at$")] = "-created_at",
):
    return presenters.page(
        queries.list_transactions(
            db,
            actor,
            limit=limit,
            cursor=cursor,
            status=status,
            type=type,
            wallet_id=wallet_id,
            currency=currency,
            created_after=created_after,
            created_before=created_before,
            search=search,
            sort=sort,
        ),
        presenters.transaction,
    )


@router.get("/transactions/{transaction_id}", response_model=s.TransactionDetailOut, tags=["transactions"])
def get_transaction(
    transaction_id: UUID, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)
):
    return presenters.transaction_detail(db, actor, queries.get_transaction(db, actor, transaction_id))


# --- holds -------------------------------------------------------------------------


@router.get("/holds", response_model=s.PageOut[s.HoldOut], tags=["holds"])
def list_holds(
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    limit: Limit = 25,
    cursor: str | None = None,
    status: HoldStatus | None = None,
    wallet_id: UUID | None = None,
):
    return presenters.page(
        queries.list_holds(db, actor, limit=limit, cursor=cursor, status=status, wallet_id=wallet_id),
        presenters.hold,
    )


@router.post("/holds", response_model=s.HoldOut, status_code=201, tags=["holds"])
def create_hold(
    body: s.HoldIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    key: str = Depends(idempotency_key),
) -> JSONResponse:
    result = operations.create_hold(
        db,
        actor,
        wallet_id=body.wallet_id,
        destination_wallet_id=body.destination_wallet_id,
        amount=body.amount,
        currency=body.currency,
        expires_in_seconds=body.expires_in_seconds,
        description=body.description,
        idempotency_key=key,
    )
    return presenters.operation_response(db, actor, result, _load_hold)


@router.get("/holds/{hold_id}", response_model=s.HoldOut, tags=["holds"])
def get_hold(hold_id: UUID, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    return _load_hold(db, actor, hold_id)


@router.post("/holds/{hold_id}/capture", response_model=s.HoldOut, tags=["holds"])
def capture_hold(
    hold_id: UUID,
    body: s.HoldCaptureIn | None = None,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    key: str = Depends(idempotency_key),
) -> JSONResponse:
    result = operations.capture_hold(
        db, actor, hold_id=hold_id, amount=body.amount if body else None, idempotency_key=key
    )
    return presenters.operation_response(db, actor, result, _load_hold, success_status=200)


@router.post("/holds/{hold_id}/release", response_model=s.HoldOut, tags=["holds"])
def release_hold(
    hold_id: UUID,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    key: str = Depends(idempotency_key),
) -> JSONResponse:
    result = operations.release_hold(db, actor, hold_id=hold_id, idempotency_key=key)
    return presenters.operation_response(db, actor, result, _load_hold, success_status=200)


# --- reversals ----------------------------------------------------------------------


@router.post("/reversals", response_model=s.TransactionOut, status_code=201, tags=["reversals"])
def create_reversal(
    body: s.ReversalIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    key: str = Depends(idempotency_key),
) -> JSONResponse:
    result = operations.reverse_transaction(
        db,
        actor,
        transaction_id=body.transaction_id,
        amount=body.amount,
        reason=body.reason,
        idempotency_key=key,
    )
    return presenters.operation_response(db, actor, result, _load_tx)
