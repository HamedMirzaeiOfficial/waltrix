"""Ledger explorer: accounts, journal entries, statements, manual entries."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from waltrix_core.enums import AccountType, EntryKind, EntryPhase
from waltrix_core.services import operations, queries, wallets
from waltrix_core.services.context import Actor

from .. import presenters
from .. import schemas as s
from ..deps import current_actor, get_db, idempotency_key

router = APIRouter(tags=["ledger"])
Limit = Annotated[int, Query(ge=1, le=100)]


def statement_out(st: queries.Statement, start: datetime | None, end: datetime | None) -> s.StatementOut:
    return s.StatementOut(
        account_id=st.account.id,
        currency=st.account.currency,
        start=start,
        end=end,
        opening_balance=st.opening_balance,
        closing_balance=st.closing_balance,
        total_debits=st.total_debits,
        total_credits=st.total_credits,
        lines=[
            s.StatementLineOut(**{f: getattr(ln, f) for f in s.StatementLineOut.model_fields})
            for ln in st.lines
        ],
    )


@router.get("/accounts", response_model=s.PageOut[s.AccountOut])
def list_accounts(
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    limit: Limit = 50,
    cursor: str | None = None,
    type: AccountType | None = None,
    currency: str | None = None,
    include_wallets: bool = True,
):
    return presenters.page(
        queries.list_accounts(
            db,
            actor,
            limit=limit,
            cursor=cursor,
            type=type,
            currency=currency,
            include_wallets=include_wallets,
        ),
        presenters.account,
    )


@router.post("/accounts", response_model=s.AccountOut, status_code=201)
def create_account(body: s.AccountIn, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    return presenters.account(
        wallets.create_internal_account(
            db, actor, code=body.code, name=body.name, type=body.type, currency=body.currency
        )
    )


@router.get("/accounts/{account_id}", response_model=s.AccountOut)
def get_account(account_id: UUID, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    return presenters.account(queries.get_account(db, actor, account_id))


@router.get("/accounts/{account_id}/statement", response_model=s.StatementOut)
def account_statement(
    account_id: UUID,
    start: datetime | None = None,
    end: datetime | None = None,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    return statement_out(queries.statement(db, actor, account_id, start=start, end=end), start, end)


@router.get("/journal-entries", response_model=s.PageOut[s.JournalEntryOut])
def list_entries(
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    limit: Limit = 25,
    cursor: str | None = None,
    kind: EntryKind | None = None,
    phase: EntryPhase | None = None,
    account_id: UUID | None = None,
):
    p = queries.list_entries(
        db, actor, limit=limit, cursor=cursor, kind=kind, phase=phase, account_id=account_id
    )
    return {
        "data": presenters.entries(db, actor, p.items),
        "next_cursor": p.next_cursor,
        "has_more": p.has_more,
    }


@router.get("/journal-entries/{entry_id}", response_model=s.JournalEntryOut)
def get_entry(entry_id: UUID, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    return presenters.entries(db, actor, [queries.get_entry(db, actor, entry_id)])[0]


@router.post(
    "/journal-entries",
    response_model=s.JournalEntryOut,
    status_code=201,
    summary="Post a balanced manual entry between internal (non-wallet) accounts",
)
def post_manual(
    body: s.ManualEntryIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    key: str = Depends(idempotency_key),
) -> JSONResponse:
    result = operations.post_manual_entry(
        db,
        actor,
        description=body.description,
        lines=[ln.model_dump() for ln in body.lines],
        idempotency_key=key,
    )
    return presenters.operation_response(
        db, actor, result, lambda d, a, i: presenters.entries(d, a, [queries.get_entry(d, a, i)])[0]
    )
