"""Read side: tenant-scoped lookups, keyset pagination, statements, overview stats.

Every query filters by ``org_id`` first. A resource of another tenant is
reported as "not found", exactly like a nonexistent id.
"""

from __future__ import annotations

import base64
import contextlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.orm import Session

from ..db.models import (
    Account,
    AuditEvent,
    Hold,
    JournalEntry,
    Posting,
    ReconciliationRun,
    Transaction,
    Wallet,
)
from ..enums import Direction, EntryPhase, NormalBalance, TransactionStatus
from ..errors import NotFound, ValidationFailed
from ..permissions import Permission
from .context import Actor

T = TypeVar("T")
MAX_PAGE = 100


@dataclass(frozen=True, slots=True)
class Page[T]:
    items: list[T]
    next_cursor: str | None

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None


def _encode_cursor(created_at: datetime, id_: Any) -> str:
    raw = json.dumps([created_at.isoformat(), str(id_)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        ts, id_ = json.loads(base64.urlsafe_b64decode(padded))
        return datetime.fromisoformat(ts), id_
    except (ValueError, TypeError) as exc:
        raise ValidationFailed("invalid cursor", field="cursor") from exc


def paginate(
    session: Session,
    stmt: Select[Any],
    model: Any,
    *,
    limit: int,
    cursor: str | None,
    ascending: bool = False,
) -> Page[Any]:
    """Keyset pagination on (created_at, id).

    Unlike OFFSET, results stay stable while new rows are inserted (ledgers
    grow constantly) and cost does not grow with page depth.
    """
    if not 1 <= limit <= MAX_PAGE:
        raise ValidationFailed(f"limit must be between 1 and {MAX_PAGE}", field="limit")
    if cursor:
        ts, id_ = _decode_cursor(cursor)
        if ascending:
            stmt = stmt.where(or_(model.created_at > ts, and_(model.created_at == ts, model.id > id_)))
        else:
            stmt = stmt.where(or_(model.created_at < ts, and_(model.created_at == ts, model.id < id_)))
    order = (
        (model.created_at.asc(), model.id.asc()) if ascending else (model.created_at.desc(), model.id.desc())
    )
    rows = list(session.execute(stmt.order_by(*order).limit(limit + 1)).unique().scalars())
    nxt = None
    if len(rows) > limit:
        rows = rows[:limit]
        nxt = _encode_cursor(rows[-1].created_at, rows[-1].id)
    return Page(rows, nxt)


# --- wallets and accounts -----------------------------------------------------


def get_wallet(session: Session, actor: Actor, wallet_id: UUID) -> Wallet:
    actor.require(Permission.WALLETS_READ)
    w = (
        session.execute(select(Wallet).where(Wallet.id == wallet_id, Wallet.org_id == actor.org_id))
        .unique()
        .scalar_one_or_none()
    )
    if w is None:
        raise NotFound("wallet not found")
    return w


def list_wallets(
    session: Session,
    actor: Actor,
    *,
    limit: int = 25,
    cursor: str | None = None,
    status: str | None = None,
    currency: str | None = None,
    search: str | None = None,
) -> Page[Wallet]:
    actor.require(Permission.WALLETS_READ)
    stmt = select(Wallet).where(Wallet.org_id == actor.org_id)
    if status:
        stmt = stmt.where(Wallet.status == status)
    if currency:
        stmt = stmt.where(Wallet.currency == currency.upper())
    if search:
        like = f"%{search.strip()[:100]}%"
        stmt = stmt.where(or_(Wallet.name.ilike(like), Wallet.owner_reference.ilike(like)))
    return paginate(session, stmt, Wallet, limit=limit, cursor=cursor)


def get_account(session: Session, actor: Actor, account_id: UUID) -> Account:
    actor.require(Permission.LEDGER_READ)
    a = session.execute(
        select(Account).where(Account.id == account_id, Account.org_id == actor.org_id)
    ).scalar_one_or_none()
    if a is None:
        raise NotFound("account not found")
    return a


def list_accounts(
    session: Session,
    actor: Actor,
    *,
    limit: int = 50,
    cursor: str | None = None,
    type: str | None = None,
    currency: str | None = None,
    include_wallets: bool = True,
) -> Page[Account]:
    actor.require(Permission.LEDGER_READ)
    stmt = select(Account).where(Account.org_id == actor.org_id)
    if type:
        stmt = stmt.where(Account.type == type)
    if currency:
        stmt = stmt.where(Account.currency == currency.upper())
    if not include_wallets:
        stmt = stmt.where(~Account.code.startswith("wallet:"))
    return paginate(session, stmt, Account, limit=limit, cursor=cursor)


# --- transactions ------------------------------------------------------------


def get_transaction(session: Session, actor: Actor, transaction_id: UUID) -> Transaction:
    actor.require(Permission.LEDGER_READ)
    t = session.execute(
        select(Transaction).where(Transaction.id == transaction_id, Transaction.org_id == actor.org_id)
    ).scalar_one_or_none()
    if t is None:
        raise NotFound("transaction not found")
    return t


def list_transactions(
    session: Session,
    actor: Actor,
    *,
    limit: int = 25,
    cursor: str | None = None,
    status: str | None = None,
    type: str | None = None,
    wallet_id: UUID | None = None,
    currency: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    search: str | None = None,
    sort: str = "-created_at",
) -> Page[Transaction]:
    actor.require(Permission.LEDGER_READ)
    if sort not in {"created_at", "-created_at"}:
        raise ValidationFailed("sort must be created_at or -created_at", field="sort")
    stmt = select(Transaction).where(Transaction.org_id == actor.org_id)
    if status:
        stmt = stmt.where(Transaction.status == status)
    if type:
        stmt = stmt.where(Transaction.type == type)
    if wallet_id:
        stmt = stmt.where(
            or_(Transaction.source_wallet_id == wallet_id, Transaction.destination_wallet_id == wallet_id)
        )
    if currency:
        stmt = stmt.where(Transaction.currency == currency.upper())
    if created_after:
        stmt = stmt.where(Transaction.created_at >= created_after)
    if created_before:
        stmt = stmt.where(Transaction.created_at < created_before)
    if search:
        term = search.strip()[:120]
        conds = [Transaction.reference == term, Transaction.description.ilike(f"%{term}%")]
        with contextlib.suppress(ValueError):
            conds.append(Transaction.id == UUID(term))
        stmt = stmt.where(or_(*conds))
    return paginate(session, stmt, Transaction, limit=limit, cursor=cursor, ascending=sort == "created_at")


def entries_for_transaction(session: Session, actor: Actor, transaction_id: UUID) -> list[JournalEntry]:
    get_transaction(session, actor, transaction_id)
    return list(
        session.execute(
            select(JournalEntry)
            .where(JournalEntry.transaction_id == transaction_id, JournalEntry.org_id == actor.org_id)
            .order_by(JournalEntry.entry_number)
        ).scalars()
    )


def reversals_of(session: Session, actor: Actor, transaction_id: UUID) -> list[Transaction]:
    return list(
        session.execute(
            select(Transaction)
            .where(Transaction.org_id == actor.org_id, Transaction.original_transaction_id == transaction_id)
            .order_by(Transaction.created_at)
        ).scalars()
    )


# --- journal -------------------------------------------------------------------


def get_entry(session: Session, actor: Actor, entry_id: UUID) -> JournalEntry:
    actor.require(Permission.LEDGER_READ)
    e = session.execute(
        select(JournalEntry).where(JournalEntry.id == entry_id, JournalEntry.org_id == actor.org_id)
    ).scalar_one_or_none()
    if e is None:
        raise NotFound("journal entry not found")
    return e


def list_entries(
    session: Session,
    actor: Actor,
    *,
    limit: int = 25,
    cursor: str | None = None,
    kind: str | None = None,
    phase: str | None = None,
    account_id: UUID | None = None,
) -> Page[JournalEntry]:
    actor.require(Permission.LEDGER_READ)
    stmt = select(JournalEntry).where(JournalEntry.org_id == actor.org_id)
    if kind:
        stmt = stmt.where(JournalEntry.kind == kind)
    if phase:
        stmt = stmt.where(JournalEntry.phase == phase)
    if account_id:
        stmt = stmt.where(
            JournalEntry.id.in_(select(Posting.entry_id).where(Posting.account_id == account_id))
        )
    return paginate(session, stmt, JournalEntry, limit=limit, cursor=cursor)


def accounts_by_id(session: Session, actor: Actor, ids: Sequence[UUID]) -> dict[UUID, Account]:
    if not ids:
        return {}
    rows = session.execute(
        select(Account).where(Account.org_id == actor.org_id, Account.id.in_(set(ids)))
    ).scalars()
    return {a.id: a for a in rows}


def wallets_by_account(session: Session, actor: Actor, account_ids: Sequence[UUID]) -> dict[UUID, Wallet]:
    if not account_ids:
        return {}
    rows = (
        session.execute(
            select(Wallet).where(Wallet.org_id == actor.org_id, Wallet.account_id.in_(set(account_ids)))
        )
        .unique()
        .scalars()
    )
    return {w.account_id: w for w in rows}


# --- holds ---------------------------------------------------------------------


def get_hold(session: Session, actor: Actor, hold_id: UUID) -> Hold:
    actor.require(Permission.LEDGER_READ)
    h = session.execute(
        select(Hold).where(Hold.id == hold_id, Hold.org_id == actor.org_id)
    ).scalar_one_or_none()
    if h is None:
        raise NotFound("hold not found")
    return h


def list_holds(
    session: Session,
    actor: Actor,
    *,
    limit: int = 25,
    cursor: str | None = None,
    status: str | None = None,
    wallet_id: UUID | None = None,
) -> Page[Hold]:
    actor.require(Permission.LEDGER_READ)
    stmt = select(Hold).where(Hold.org_id == actor.org_id)
    if status:
        stmt = stmt.where(Hold.status == status)
    if wallet_id:
        stmt = stmt.where(or_(Hold.wallet_id == wallet_id, Hold.destination_wallet_id == wallet_id))
    return paginate(session, stmt, Hold, limit=limit, cursor=cursor)


# --- statements ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StatementLine:
    posting_id: int
    entry_id: UUID
    entry_number: int
    kind: str
    description: str
    transaction_id: UUID | None
    direction: str
    amount: int
    balance_after: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Statement:
    account: Account
    opening_balance: int
    closing_balance: int
    total_debits: int
    total_credits: int
    lines: list[StatementLine]


def statement(
    session: Session,
    actor: Actor,
    account_id: UUID,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 500,
) -> Statement:
    """Posted-only statement with running balance, computed from the journal (not the cache)."""
    account = get_account(session, actor, account_id)
    sign = 1 if NormalBalance(account.normal_balance) is NormalBalance.CREDIT else -1
    signed = case((Posting.direction == Direction.CREDIT, Posting.amount), else_=-Posting.amount) * sign
    base = (
        select(Posting, JournalEntry)
        .join(JournalEntry, JournalEntry.id == Posting.entry_id)
        .where(Posting.account_id == account.id, JournalEntry.phase == EntryPhase.POSTED)
    )
    opening = 0
    if start is not None:
        opening = session.execute(
            select(func.coalesce(func.sum(signed), 0))
            .select_from(Posting)
            .join(JournalEntry, JournalEntry.id == Posting.entry_id)
            .where(
                Posting.account_id == account.id,
                JournalEntry.phase == EntryPhase.POSTED,
                JournalEntry.created_at < start,
            )
        ).scalar_one()
        base = base.where(JournalEntry.created_at >= start)
    if end is not None:
        base = base.where(JournalEntry.created_at < end)
    rows = session.execute(base.order_by(Posting.id).limit(min(limit, 5000))).all()
    running = int(opening)
    lines: list[StatementLine] = []
    debits = credits = 0
    for posting, entry in rows:
        delta = posting.amount if posting.direction == Direction.CREDIT else -posting.amount
        running += delta * sign
        if posting.direction == Direction.DEBIT:
            debits += posting.amount
        else:
            credits += posting.amount
        lines.append(
            StatementLine(
                posting.id,
                entry.id,
                entry.entry_number,
                str(entry.kind),
                entry.description,
                entry.transaction_id,
                str(posting.direction),
                posting.amount,
                running,
                entry.created_at,
            )
        )
    return Statement(account, int(opening), running, debits, credits, lines)


# --- audit and reconciliation reads -------------------------------------------


def list_audit_events(
    session: Session,
    actor: Actor,
    *,
    limit: int = 50,
    cursor: str | None = None,
    action: str | None = None,
    target_id: str | None = None,
    actor_id: str | None = None,
) -> Page[AuditEvent]:
    actor.require(Permission.AUDIT_READ)
    stmt = select(AuditEvent).where(AuditEvent.org_id == actor.org_id)
    if action:
        stmt = stmt.where(AuditEvent.action.startswith(action))
    if target_id:
        stmt = stmt.where(AuditEvent.target_id == target_id)
    if actor_id:
        stmt = stmt.where(AuditEvent.actor_id == actor_id)
    return paginate(session, stmt, AuditEvent, limit=limit, cursor=cursor)


def list_reconciliation_runs(
    session: Session, actor: Actor, *, limit: int = 20, cursor: str | None = None
) -> Page[ReconciliationRun]:
    actor.require(Permission.RECONCILIATION_READ)
    stmt = select(ReconciliationRun).where(ReconciliationRun.org_id == actor.org_id)
    return paginate(session, stmt, ReconciliationRun, limit=limit, cursor=cursor)


def get_reconciliation_run(session: Session, actor: Actor, run_id: UUID) -> ReconciliationRun:
    actor.require(Permission.RECONCILIATION_READ)
    r = session.execute(
        select(ReconciliationRun).where(
            ReconciliationRun.id == run_id, ReconciliationRun.org_id == actor.org_id
        )
    ).scalar_one_or_none()
    if r is None:
        raise NotFound("reconciliation run not found")
    return r


# --- overview ----------------------------------------------------------------


def overview(session: Session, actor: Actor, *, days: int = 30) -> dict[str, Any]:
    """Dashboard numbers, all computed from real rows. No invented statistics."""
    actor.require(Permission.LEDGER_READ)
    org = actor.org_id
    balances = session.execute(
        select(
            Wallet.currency,
            func.count(Wallet.id),
            func.coalesce(func.sum(Account.posted_credits - Account.posted_debits), 0),
            func.coalesce(func.sum(Account.pending_debits), 0),
        )
        .join(Account, Account.id == Wallet.account_id)
        .where(Wallet.org_id == org)
        .group_by(Wallet.currency)
        .order_by(Wallet.currency)
    ).all()
    status_counts = session.execute(
        select(Transaction.status, func.count()).where(Transaction.org_id == org).group_by(Transaction.status)
    ).all()
    day = func.date_trunc("day", Transaction.created_at)
    volume = session.execute(
        select(
            day.label("day"),
            Transaction.currency,
            func.count(),
            func.coalesce(func.sum(Transaction.posted_amount), 0),
        )
        .where(
            Transaction.org_id == org,
            Transaction.status.in_([TransactionStatus.POSTED, TransactionStatus.REVERSED]),
            Transaction.type != "reversal",
            Transaction.created_at >= func.now() - func.make_interval(0, 0, 0, days),
        )
        .group_by(day, Transaction.currency)
        .order_by(day)
    ).all()
    failed_24h = session.execute(
        select(func.count()).where(
            Transaction.org_id == org,
            Transaction.status == TransactionStatus.FAILED,
            Transaction.created_at >= func.now() - func.make_interval(0, 0, 0, 1),
        )
    ).scalar_one()
    active_holds = session.execute(
        select(Hold.currency, func.count(), func.coalesce(func.sum(Hold.amount), 0))
        .where(Hold.org_id == org, Hold.status == "active")
        .group_by(Hold.currency)
    ).all()
    last_run = session.execute(
        select(ReconciliationRun)
        .where(ReconciliationRun.org_id == org)
        .order_by(ReconciliationRun.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return {
        "balances": [
            {"currency": c, "wallet_count": n, "total_posted": int(p), "total_held": int(h)}
            for c, n, p, h in balances
        ],
        "transaction_counts": {str(s): int(n) for s, n in status_counts},
        "volume": [
            {"day": d.date().isoformat(), "currency": c, "count": int(n), "amount": int(a)}
            for d, c, n, a in volume
        ],
        "failed_last_24h": int(failed_24h),
        "active_holds": [{"currency": c, "count": int(n), "amount": int(a)} for c, n, a in active_holds],
        "last_reconciliation": last_run,
        "window_days": days,
    }
