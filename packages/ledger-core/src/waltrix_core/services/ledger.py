"""The double-entry posting engine.

Only this module writes ``journal_entries``/``postings`` and changes the
materialized balance columns on ``accounts``. Every caller must:

1. be inside a database transaction;
2. have locked every touched account with ``lock_accounts`` (which sorts by
   id, giving a global lock order and therefore no deadlocks between
   posting transactions).

``post_entry`` then validates the entry (pure rules), checks account state
and overdraft rules against the *locked* rows, inserts the entry and its
postings and updates balances, all in the caller's transaction.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..db.models import Account, JournalEntry, Ledger, Posting
from ..enums import (
    NORMAL_BALANCE,
    AccountStatus,
    AccountType,
    Direction,
    EntryKind,
    EntryPhase,
    NormalBalance,
)
from ..errors import AccountNotActive, InsufficientFunds, LedgerInvariantViolation
from ..rules import Line, available_balance, signed_balance, validate_entry
from .context import Actor

DEFAULT_LEDGER = "main"
FUNDING_ACCOUNT_CODE = "system:simulated_funding"


def now() -> datetime:
    return datetime.now(UTC)


def get_or_create_default_ledger(session: Session, org_id: UUID) -> Ledger:
    session.execute(insert(Ledger).values(org_id=org_id, name=DEFAULT_LEDGER).on_conflict_do_nothing())
    return session.execute(
        select(Ledger).where(Ledger.org_id == org_id, Ledger.name == DEFAULT_LEDGER)
    ).scalar_one()


def ensure_account(
    session: Session,
    org_id: UUID,
    *,
    code: str,
    name: str,
    type: AccountType,
    currency: str,
    allow_negative: bool = False,
    is_system: bool = False,
) -> Account:
    """Idempotently create an account (safe under concurrency via ON CONFLICT)."""
    ledger = get_or_create_default_ledger(session, org_id)
    session.execute(
        insert(Account)
        .values(
            org_id=org_id,
            ledger_id=ledger.id,
            code=code,
            name=name,
            type=type,
            normal_balance=NORMAL_BALANCE[type],
            currency=currency,
            allow_negative=allow_negative,
            is_system=is_system,
        )
        .on_conflict_do_nothing(index_elements=["ledger_id", "code", "currency"])
    )
    return session.execute(
        select(Account).where(
            Account.ledger_id == ledger.id, Account.code == code, Account.currency == currency
        )
    ).scalar_one()


def ensure_funding_account(session: Session, org_id: UUID, currency: str) -> Account:
    """The clearing asset that represents the *simulated* external funding source.

    Debited when a wallet is funded, credited when money is withdrawn. Its
    balance always equals the net amount that entered from outside, so it is
    never allowed to go negative: money cannot be withdrawn that never came in.
    """
    return ensure_account(
        session,
        org_id,
        code=FUNDING_ACCOUNT_CODE,
        name=f"Simulated funding source ({currency}) - synthetic, no real bank",
        type=AccountType.ASSET,
        currency=currency,
        allow_negative=False,
        is_system=True,
    )


def lock_accounts(session: Session, org_id: UUID, account_ids: Iterable[UUID]) -> dict[UUID, Account]:
    """``SELECT ... FOR UPDATE`` the accounts in ascending id order.

    Deterministic ordering is what prevents deadlocks: two transfers A->B and
    B->A both lock min(A,B) first, so one simply waits for the other.
    ``populate_existing`` makes sure we read the balances *after* the lock was
    granted, not stale values from the identity map.
    """
    ids = sorted(set(account_ids))
    rows = (
        session.execute(
            select(Account)
            .where(Account.org_id == org_id, Account.id.in_(ids))
            .order_by(Account.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        .scalars()
        .all()
    )
    found = {a.id: a for a in rows}
    missing = set(ids) - set(found)
    if missing:
        raise LedgerInvariantViolation("account not found in this organization")
    return found


def balance_view(account: Account) -> dict[str, int]:
    normal = NormalBalance(account.normal_balance)
    posted = signed_balance(normal, account.posted_debits, account.posted_credits)
    if normal is NormalBalance.CREDIT:
        pending_out, pending_in = account.pending_debits, account.pending_credits
    else:
        pending_out, pending_in = account.pending_credits, account.pending_debits
    return {
        "posted": posted,
        "pending_outgoing": pending_out,
        "pending_incoming": pending_in,
        "available": available_balance(
            normal,
            account.posted_debits,
            account.posted_credits,
            account.pending_debits,
            account.pending_credits,
        ),
    }


def _apply(account: Account, line: Line, phase: EntryPhase, sign: int = 1) -> None:
    amount = sign * line.amount
    if phase is EntryPhase.POSTED:
        if line.direction is Direction.DEBIT:
            account.posted_debits += amount
        else:
            account.posted_credits += amount
    else:
        if line.direction is Direction.DEBIT:
            account.pending_debits += amount
        else:
            account.pending_credits += amount
    account.version += 1
    account.updated_at = now()


def _check_overdraft(account: Account) -> None:
    if account.allow_negative:
        return
    view = balance_view(account)
    if view["available"] < 0:
        raise InsufficientFunds(
            "insufficient available balance",
            account_id=str(account.id),
            currency=account.currency,
        )


def post_entry(
    session: Session,
    actor: Actor,
    *,
    locked: dict[UUID, Account],
    phase: EntryPhase,
    kind: EntryKind,
    description: str,
    lines: Sequence[Line],
    transaction_id: UUID | None = None,
    reverses_entry_id: UUID | None = None,
    check_status: bool = True,
) -> JournalEntry:
    validate_entry(lines)
    touched: list[Account] = []
    for line in lines:
        account = locked.get(line.account_id)
        if account is None:
            raise LedgerInvariantViolation("posting to an account that was not locked")
        if account.currency != line.currency:
            raise LedgerInvariantViolation("posting currency differs from account currency")
        if check_status and account.status != AccountStatus.ACTIVE:
            raise AccountNotActive("account is not active", account_id=str(account.id))
        touched.append(account)

    ledger_id = touched[0].ledger_id
    if any(a.ledger_id != ledger_id for a in touched):
        raise LedgerInvariantViolation("all postings of an entry must be in the same ledger")

    for line in lines:
        _apply(locked[line.account_id], line, phase)
    for account in {a.id: a for a in touched}.values():
        _check_overdraft(account)

    entry = JournalEntry(
        org_id=actor.org_id,
        ledger_id=ledger_id,
        phase=phase,
        kind=kind,
        description=description,
        transaction_id=transaction_id,
        reverses_entry_id=reverses_entry_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        correlation_id=actor.correlation_id,
    )
    session.add(entry)
    session.flush()
    for i, line in enumerate(lines, start=1):
        session.add(
            Posting(
                entry_id=entry.id,
                org_id=actor.org_id,
                account_id=line.account_id,
                line_no=i,
                direction=line.direction,
                amount=line.amount,
                currency=line.currency,
            )
        )
    session.flush()
    return entry


def entry_lines(entry: JournalEntry) -> list[Line]:
    return [Line(p.account_id, Direction(p.direction), p.amount, p.currency) for p in entry.postings]


def release_pending(locked: dict[UUID, Account], pending_entry: JournalEntry) -> None:
    """Undo the pending-balance effect of a PENDING entry (hold capture/release/expiry).

    The pending entry itself is immutable and stays in the journal; whether it
    still counts is determined by its hold's status. Reconciliation checks that
    pending columns equal the sum of PENDING entries of ACTIVE holds.
    """
    if pending_entry.phase != EntryPhase.PENDING:
        raise LedgerInvariantViolation("only pending entries can be released")
    for line in entry_lines(pending_entry):
        account = locked.get(line.account_id)
        if account is None:
            raise LedgerInvariantViolation("releasing pending amount on an unlocked account")
        _apply(account, line, EntryPhase.PENDING, sign=-1)
