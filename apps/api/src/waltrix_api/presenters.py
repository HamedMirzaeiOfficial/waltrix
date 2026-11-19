"""ORM -> response schema conversion, plus the shared response for financial operations."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from waltrix_core.db.models import Account, AuditEvent, Hold, JournalEntry, Transaction, Wallet
from waltrix_core.permissions import permissions_for
from waltrix_core.services import queries
from waltrix_core.services.context import Actor
from waltrix_core.services.ledger import balance_view
from waltrix_core.services.runner import OperationResult

from . import schemas as s
from .errors import error_body


def balance(account: Account) -> s.BalanceOut:
    return s.BalanceOut(currency=account.currency, **balance_view(account))


def account(a: Account) -> s.AccountOut:
    return s.AccountOut(
        id=a.id,
        code=a.code,
        name=a.name,
        type=a.type,
        normal_balance=a.normal_balance,
        currency=a.currency,
        status=a.status,
        is_system=a.is_system,
        allow_negative=a.allow_negative,
        balance=balance(a),
        created_at=a.created_at,
    )


def wallet(w: Wallet) -> s.WalletOut:
    return s.WalletOut(
        id=w.id,
        name=w.name,
        owner_reference=w.owner_reference,
        currency=w.currency,
        status=w.status,
        account_id=w.account_id,
        balance=balance(w.account),
        metadata=w.metadata_,
        created_at=w.created_at,
        updated_at=w.updated_at,
    )


def transaction(t: Transaction) -> s.TransactionOut:
    return s.TransactionOut(
        id=t.id,
        type=t.type,
        status=t.status,
        amount=t.amount,
        posted_amount=t.posted_amount,
        reversed_amount=t.reversed_amount,
        currency=t.currency,
        source_wallet_id=t.source_wallet_id,
        destination_wallet_id=t.destination_wallet_id,
        original_transaction_id=t.original_transaction_id,
        description=t.description,
        reference=t.reference,
        failure_code=t.failure_code,
        failure_message=t.failure_message,
        actor_type=t.actor_type,
        actor_id=t.actor_id,
        correlation_id=t.correlation_id,
        metadata=t.metadata_,
        created_at=t.created_at,
        updated_at=t.updated_at,
        posted_at=t.posted_at,
    )


def entries(db: Session, actor: Actor, rows: Sequence[JournalEntry]) -> list[s.JournalEntryOut]:
    account_ids = [p.account_id for e in rows for p in e.postings]
    accounts = queries.accounts_by_id(db, actor, account_ids)
    wallets = queries.wallets_by_account(db, actor, account_ids)
    out = []
    for e in rows:
        out.append(
            s.JournalEntryOut(
                id=e.id,
                entry_number=e.entry_number,
                phase=e.phase,
                kind=e.kind,
                description=e.description,
                transaction_id=e.transaction_id,
                reverses_entry_id=e.reverses_entry_id,
                actor_type=e.actor_type,
                actor_id=e.actor_id,
                correlation_id=e.correlation_id,
                effective_at=e.effective_at,
                created_at=e.created_at,
                postings=[
                    s.PostingOut(
                        line_no=p.line_no,
                        account_id=p.account_id,
                        account_code=accounts[p.account_id].code if p.account_id in accounts else None,
                        account_name=accounts[p.account_id].name if p.account_id in accounts else None,
                        wallet_id=wallets[p.account_id].id if p.account_id in wallets else None,
                        direction=p.direction,
                        amount=p.amount,
                        currency=p.currency,
                    )
                    for p in e.postings
                ],
            )
        )
    return out


def transaction_detail(db: Session, actor: Actor, t: Transaction) -> s.TransactionDetailOut:
    hold_id = db.execute(select(Hold.id).where(Hold.transaction_id == t.id)).scalar_one_or_none()
    return s.TransactionDetailOut(
        **transaction(t).model_dump(),
        journal_entries=entries(db, actor, queries.entries_for_transaction(db, actor, t.id)),
        reversals=[transaction(r) for r in queries.reversals_of(db, actor, t.id)],
        hold_id=hold_id,
    )


def hold(h: Hold) -> s.HoldOut:
    return s.HoldOut.model_validate(h)


def audit_event(e: AuditEvent) -> s.AuditEventOut:
    return s.AuditEventOut(
        id=e.id,
        actor_type=e.actor_type,
        actor_id=e.actor_id,
        actor_label=e.actor_label,
        action=e.action,
        target_type=e.target_type,
        target_id=e.target_id,
        correlation_id=e.correlation_id,
        metadata=e.metadata_,
        created_at=e.created_at,
    )


def page(p: queries.Page[Any], convert: Callable[[Any], Any]) -> dict[str, Any]:
    return {"data": [convert(x) for x in p.items], "next_cursor": p.next_cursor, "has_more": p.has_more}


def membership_out(org: Any, role: Any) -> s.MembershipOut:
    return s.MembershipOut(
        organization=s.OrganizationOut.model_validate(org),
        role=role,
        permissions=sorted(str(p) for p in permissions_for(role)),
    )


def operation_response(
    db: Session,
    actor: Actor,
    result: OperationResult,
    load: Callable[[Session, Actor, UUID], Any],
    *,
    success_status: int = 201,
) -> JSONResponse:
    """Uniform HTTP mapping for financial operations.

    * succeeded -> ``success_status`` + resource
    * failed (business rule) -> 422 + error, with the FAILED transaction id when one was recorded
    * replayed -> same as the original, plus ``Idempotent-Replayed: true``

    A replay returns the *current* state of the original resource (e.g. a
    transfer that has since been reversed shows ``reversed``). The outcome -
    which resource, success or failure - is what is guaranteed to match.
    """
    headers = {"Idempotent-Replayed": "true"} if result.replayed else {}
    db.rollback()  # fresh read after the operation's own transaction
    if result.succeeded and result.resource_id is not None:
        body = load(db, actor, result.resource_id)
        return JSONResponse(body.model_dump(mode="json"), status_code=success_status, headers=headers)
    details: dict[str, Any] = {}
    if result.resource_type == "transaction" and result.resource_id is not None:
        details["transaction_id"] = str(result.resource_id)
    return JSONResponse(
        error_body(
            result.error_code or "operation_failed", result.error_message or "operation failed", details
        ),
        status_code=422,
        headers=headers,
    )
