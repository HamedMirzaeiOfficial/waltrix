"""Financial invariants, verified against real PostgreSQL.

Numbering follows docs/financial-model/invariants.md.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from tests.conftest import make_org
from tests.helpers import balance, new_wallet, total_wallet_liabilities
from waltrix_core.db.models import Account, JournalEntry, Posting, Transaction, Wallet
from waltrix_core.enums import EntryPhase, Role, TransactionStatus, WalletStatus
from waltrix_core.errors import (
    IdempotencyKeyReused,
    LedgerInvariantViolation,
    NotFound,
    PermissionDenied,
    ValidationFailed,
)
from waltrix_core.services import operations, reconciliation, wallets
from waltrix_core.services.context import Actor
from waltrix_core.services.ledger import now


def _recon_ok(session: Session, actor: Actor) -> None:
    run = reconciliation.run_reconciliation(session, actor)
    assert run.status == "passed", run.findings


# 1. Total debits always equal total credits ------------------------------------------


def test_1_trial_balance_holds_after_mixed_operations(session: Session, owner: Actor) -> None:
    a = new_wallet(session, owner, funded=10_000)
    b = new_wallet(session, owner, funded=5_000)
    operations.transfer(session, owner, source_wallet_id=a, destination_wallet_id=b, amount=2_500, currency="USD")
    operations.withdraw(session, owner, wallet_id=b, amount=1_000, currency="USD")
    hold = operations.create_hold(session, owner, wallet_id=a, destination_wallet_id=b, amount=700, currency="USD")
    operations.capture_hold(session, owner, hold_id=hold.resource_id, amount=300)
    debits, credits = session.execute(
        text(
            "SELECT sum(amount) FILTER (WHERE direction='debit'), sum(amount) FILTER (WHERE direction='credit') "
            "FROM postings"
        )
    ).one()
    session.commit()
    assert debits == credits
    _recon_ok(session, owner)


def test_1_database_rejects_unbalanced_entry_at_commit(session: Session, owner: Actor) -> None:
    """Even raw SQL bypassing the engine cannot commit an unbalanced entry."""
    a = new_wallet(session, owner)
    b = new_wallet(session, owner)
    wa, wb = session.get_one(Wallet, a), session.get_one(Wallet, b)
    session.commit()
    with pytest.raises(DBAPIError, match="unbalanced"):
        with session.begin():
            entry = JournalEntry(
                org_id=owner.org_id, ledger_id=wa.account.ledger_id, phase=EntryPhase.POSTED,
                kind="manual", description="tamper", actor_type="system",
            )
            session.add(entry)
            session.flush()
            session.add_all([
                Posting(entry_id=entry.id, org_id=owner.org_id, account_id=wa.account_id, line_no=1,
                        direction="debit", amount=100, currency="USD"),
                Posting(entry_id=entry.id, org_id=owner.org_id, account_id=wb.account_id, line_no=2,
                        direction="credit", amount=90, currency="USD"),
            ])
    assert session.execute(select(JournalEntry).where(JournalEntry.description == "tamper")).first() is None


def test_1_database_rejects_single_posting_entry(session: Session, owner: Actor) -> None:
    a = new_wallet(session, owner)
    wa = session.get_one(Wallet, a)
    session.commit()
    with pytest.raises(DBAPIError, match="at least 2"):
        with session.begin():
            entry = JournalEntry(org_id=owner.org_id, ledger_id=wa.account.ledger_id, phase="posted",
                                 kind="manual", description="x", actor_type="system")
            session.add(entry)


# 2. Internal transfers neither create nor destroy money --------------------------------


def test_2_transfers_conserve_total(session: Session, owner: Actor) -> None:
    ids = [new_wallet(session, owner, funded=1_000) for _ in range(4)]
    before = total_wallet_liabilities(session, owner.org_id, "USD")
    for i in range(12):
        operations.transfer(session, owner, source_wallet_id=ids[i % 4], destination_wallet_id=ids[(i + 1) % 4],
                            amount=37 * (i + 1), currency="USD")
    assert total_wallet_liabilities(session, owner.org_id, "USD") == before == 4_000
    _recon_ok(session, owner)


# 3. No partial journal entries --------------------------------------------------------


def test_3_failure_mid_operation_commits_nothing(session: Session, owner: Actor, monkeypatch: pytest.MonkeyPatch) -> None:
    a = new_wallet(session, owner, funded=1_000)
    b = new_wallet(session, owner)
    counts_before = session.execute(text("SELECT (SELECT count(*) FROM postings), (SELECT count(*) FROM transactions)")).one()
    session.commit()

    original = operations.post_entry

    def explode(*args, **kwargs):  # type: ignore[no-untyped-def]
        original(*args, **kwargs)  # postings are flushed...
        raise RuntimeError("simulated crash after posting")  # ...then the process "dies"

    monkeypatch.setattr(operations, "post_entry", explode)
    with pytest.raises(RuntimeError):
        operations.transfer(session, owner, source_wallet_id=a, destination_wallet_id=b, amount=500,
                            currency="USD", idempotency_key="crash-1")
    monkeypatch.setattr(operations, "post_entry", original)

    counts_after = session.execute(text("SELECT (SELECT count(*) FROM postings), (SELECT count(*) FROM transactions)")).one()
    session.commit()
    assert counts_after == counts_before
    assert balance(session, a)["posted"] == 1_000
    # The idempotency key was not consumed: the retry runs and succeeds once.
    retry = operations.transfer(session, owner, source_wallet_id=a, destination_wallet_id=b, amount=500,
                                currency="USD", idempotency_key="crash-1")
    assert retry.succeeded and not retry.replayed
    assert balance(session, b)["posted"] == 500


# 4. Posted journal entries are immutable ----------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE postings SET amount = amount + 1",
        "DELETE FROM postings",
        "UPDATE journal_entries SET description = 'edited'",
        "DELETE FROM journal_entries",
        "UPDATE audit_events SET action = 'x'",
    ],
)
def test_4_journal_is_append_only(session: Session, owner: Actor, sql: str) -> None:
    new_wallet(session, owner, funded=100)
    with pytest.raises(DBAPIError, match="append-only"):
        with session.begin():
            session.execute(text(sql))


# 5. Reversals preserve history -----------------------------------------------------------


def test_5_reversal_adds_entry_and_keeps_original(session: Session, owner: Actor) -> None:
    a = new_wallet(session, owner, funded=1_000)
    b = new_wallet(session, owner)
    t = operations.transfer(session, owner, source_wallet_id=a, destination_wallet_id=b, amount=400, currency="USD")
    original_entry = session.execute(select(JournalEntry).where(JournalEntry.transaction_id == t.resource_id)).scalar_one()
    original_lines = [(p.direction, p.amount) for p in original_entry.postings]
    session.commit()

    r = operations.reverse_transaction(session, owner, transaction_id=t.resource_id, reason="customer dispute")
    assert r.succeeded
    session.expire_all()
    still_there = session.get_one(JournalEntry, original_entry.id)
    assert [(p.direction, p.amount) for p in still_there.postings] == original_lines
    rev_entry = session.execute(select(JournalEntry).where(JournalEntry.transaction_id == r.resource_id)).scalar_one()
    assert rev_entry.reverses_entry_id == original_entry.id
    assert session.get_one(Transaction, t.resource_id).status == TransactionStatus.REVERSED
    session.commit()
    assert balance(session, a)["posted"] == 1_000 and balance(session, b)["posted"] == 0
    # A second full reversal is refused.
    again = operations.reverse_transaction(session, owner, transaction_id=t.resource_id)
    assert not again.succeeded and again.error_code == "not_reversible"
    _recon_ok(session, owner)


def test_5_partial_reversals_track_remaining(session: Session, owner: Actor) -> None:
    a = new_wallet(session, owner, funded=1_000)
    b = new_wallet(session, owner)
    t = operations.transfer(session, owner, source_wallet_id=a, destination_wallet_id=b, amount=600, currency="USD")
    assert operations.reverse_transaction(session, owner, transaction_id=t.resource_id, amount=200).succeeded
    assert operations.reverse_transaction(session, owner, transaction_id=t.resource_id, amount=300).succeeded
    too_much = operations.reverse_transaction(session, owner, transaction_id=t.resource_id, amount=200)
    assert too_much.error_code == "reversal_exceeds_remaining"
    tx = session.get_one(Transaction, t.resource_id, populate_existing=True)
    assert (tx.status, tx.reversed_amount) == (TransactionStatus.POSTED, 500)
    session.commit()
    assert operations.reverse_transaction(session, owner, transaction_id=t.resource_id).succeeded
    assert session.get_one(Transaction, t.resource_id, populate_existing=True).status == TransactionStatus.REVERSED
    session.commit()
    _recon_ok(session, owner)


def test_5_reversal_cannot_overdraw_recipient(session: Session, owner: Actor) -> None:
    a = new_wallet(session, owner, funded=1_000)
    b = new_wallet(session, owner)
    c = new_wallet(session, owner)
    t = operations.transfer(session, owner, source_wallet_id=a, destination_wallet_id=b, amount=500, currency="USD")
    operations.transfer(session, owner, source_wallet_id=b, destination_wallet_id=c, amount=400, currency="USD")
    r = operations.reverse_transaction(session, owner, transaction_id=t.resource_id)
    assert r.error_code == "insufficient_funds"
    assert balance(session, b)["posted"] == 100


# 6. Duplicate requests do not duplicate transfers --------------------------------------


def test_6_idempotent_replay_and_conflict(session: Session, owner: Actor) -> None:
    a = new_wallet(session, owner, funded=1_000)
    b = new_wallet(session, owner)
    kw = dict(source_wallet_id=a, destination_wallet_id=b, amount=250, currency="USD", idempotency_key="pay-42")
    first = operations.transfer(session, owner, **kw)  # type: ignore[arg-type]
    second = operations.transfer(session, owner, **kw)  # type: ignore[arg-type]
    assert first.resource_id == second.resource_id and second.replayed
    assert balance(session, b)["posted"] == 250
    with pytest.raises(IdempotencyKeyReused):
        operations.transfer(session, owner, **{**kw, "amount": 251})  # type: ignore[arg-type]
    # Same key on a different operation is a different scope.
    dep = operations.deposit(session, owner, wallet_id=b, amount=1, currency="USD", idempotency_key="pay-42")
    assert dep.succeeded and not dep.replayed


def test_6_business_failure_is_replayed_not_rerun(session: Session, owner: Actor) -> None:
    a = new_wallet(session, owner, funded=100)
    b = new_wallet(session, owner)
    kw = dict(source_wallet_id=a, destination_wallet_id=b, amount=500, currency="USD", idempotency_key="k-fail")
    f1 = operations.transfer(session, owner, **kw)  # type: ignore[arg-type]
    assert f1.error_code == "insufficient_funds" and f1.resource_id
    operations.deposit(session, owner, wallet_id=a, amount=1_000, currency="USD")
    f2 = operations.transfer(session, owner, **kw)  # type: ignore[arg-type]
    assert f2.replayed and f2.error_code == "insufficient_funds" and f2.resource_id == f1.resource_id
    assert session.get_one(Transaction, f1.resource_id).status == TransactionStatus.FAILED


def test_6_expired_key_can_be_reused(session: Session, owner: Actor) -> None:
    a = new_wallet(session, owner, funded=1_000)
    b = new_wallet(session, owner)
    kw = dict(source_wallet_id=a, destination_wallet_id=b, amount=10, currency="USD", idempotency_key="old")
    operations.transfer(session, owner, **kw)  # type: ignore[arg-type]
    with session.begin():
        session.execute(text("UPDATE idempotency_records SET expires_at = now() - interval '1 second'"))
    again = operations.transfer(session, owner, **{**kw, "amount": 20})  # type: ignore[arg-type]
    assert again.succeeded and not again.replayed


# 7. Overspending (sequential; concurrent version in tests/concurrency) ------------------


def test_7_cannot_overspend_or_spend_held_funds(session: Session, owner: Actor) -> None:
    a = new_wallet(session, owner, funded=1_000)
    b = new_wallet(session, owner)
    hold = operations.create_hold(session, owner, wallet_id=a, destination_wallet_id=b, amount=800, currency="USD")
    assert hold.succeeded
    assert balance(session, a) == {"posted": 1_000, "pending_outgoing": 800, "pending_incoming": 0, "available": 200}
    over = operations.transfer(session, owner, source_wallet_id=a, destination_wallet_id=b, amount=201, currency="USD")
    assert over.error_code == "insufficient_funds"
    assert operations.transfer(session, owner, source_wallet_id=a, destination_wallet_id=b, amount=200,
                               currency="USD").succeeded


def test_7_database_check_blocks_overdraft_even_if_engine_is_bypassed(session: Session, owner: Actor) -> None:
    a = new_wallet(session, owner, funded=100)
    w = session.get_one(Wallet, a)
    session.commit()
    with pytest.raises(IntegrityError, match="no_overdraft"):
        with session.begin():
            session.execute(text("UPDATE accounts SET posted_debits = 101 WHERE id = :id"), {"id": w.account_id})


# 8. Cross-tenant access is rejected ----------------------------------------------------


def test_8_cross_tenant_wallets_are_invisible(session: Session, owner: Actor) -> None:
    mine = new_wallet(session, owner, funded=1_000)
    other, _ = make_org(session, "Globex")
    theirs = new_wallet(session, other, funded=1_000)
    with pytest.raises(NotFound):
        operations.transfer(session, owner, source_wallet_id=mine, destination_wallet_id=theirs, amount=1, currency="USD")
    with pytest.raises(NotFound):
        operations.transfer(session, owner, source_wallet_id=theirs, destination_wallet_id=mine, amount=1, currency="USD")
    assert balance(session, theirs)["posted"] == 1_000


def test_8_schema_rejects_cross_tenant_posting(session: Session, owner: Actor) -> None:
    mine = new_wallet(session, owner)
    other, _ = make_org(session, "Initech")
    theirs = new_wallet(session, other)
    wm, wt = session.get_one(Wallet, mine), session.get_one(Wallet, theirs)
    session.commit()
    with pytest.raises(IntegrityError):
        with session.begin():
            e = JournalEntry(org_id=owner.org_id, ledger_id=wm.account.ledger_id, phase="posted",
                             kind="manual", description="x", actor_type="system")
            session.add(e)
            session.flush()
            session.add_all([
                Posting(entry_id=e.id, org_id=owner.org_id, account_id=wm.account_id, line_no=1,
                        direction="debit", amount=1, currency="USD"),
                Posting(entry_id=e.id, org_id=owner.org_id, account_id=wt.account_id, line_no=2,
                        direction="credit", amount=1, currency="USD"),
            ])
            session.flush()


def test_8_permissions_enforced_in_engine(session: Session, owner: Actor) -> None:
    a = new_wallet(session, owner, funded=100)
    b = new_wallet(session, owner)
    viewer = Actor(owner.org_id, owner.actor_type, owner.actor_id, owner.label, Role.VIEWER)
    with pytest.raises(PermissionDenied):
        operations.transfer(session, viewer, source_wallet_id=a, destination_wallet_id=b, amount=1, currency="USD")


# 9. Multi-currency isolation -------------------------------------------------------------


def test_9_no_cross_currency_transfer(session: Session, owner: Actor) -> None:
    usd = new_wallet(session, owner, "USD", funded=1_000)
    eur = new_wallet(session, owner, "EUR", funded=1_000)
    r = operations.transfer(session, owner, source_wallet_id=usd, destination_wallet_id=eur, amount=10, currency="USD")
    assert r.error_code == "currency_mismatch"
    assert total_wallet_liabilities(session, owner.org_id, "USD") == 1_000
    assert total_wallet_liabilities(session, owner.org_id, "EUR") == 1_000


def test_9_schema_rejects_posting_in_wrong_currency(session: Session, owner: Actor) -> None:
    usd = new_wallet(session, owner, "USD")
    w = session.get_one(Wallet, usd)
    session.commit()
    with pytest.raises(IntegrityError):
        with session.begin():
            e = JournalEntry(org_id=owner.org_id, ledger_id=w.account.ledger_id, phase="posted",
                             kind="manual", description="x", actor_type="system")
            session.add(e)
            session.flush()
            session.add(Posting(entry_id=e.id, org_id=owner.org_id, account_id=w.account_id, line_no=1,
                                direction="debit", amount=1, currency="EUR"))
            session.flush()


# 10. Materialized balances reconcile with the journal ------------------------------------


def test_10_reconciliation_detects_tampered_cache(session: Session, owner: Actor) -> None:
    a = new_wallet(session, owner, funded=1_000)
    _recon_ok(session, owner)
    w = session.get_one(Wallet, a)
    session.commit()
    with session.begin():  # simulate a bug / manual DB edit that only touched the cache
        session.execute(text("UPDATE accounts SET posted_credits = posted_credits + 5 WHERE id = :id"),
                        {"id": w.account_id})
    run = reconciliation.run_reconciliation(session, owner)
    checks = {f["check"] for f in run.findings}
    assert run.status == "failed"
    assert {"posted_balance_mismatch", "funding_vs_wallets"} <= checks


# Holds -------------------------------------------------------------------------------------


def test_hold_capture_partial_releases_remainder(session: Session, owner: Actor) -> None:
    a = new_wallet(session, owner, funded=1_000)
    m = new_wallet(session, owner)
    h = operations.create_hold(session, owner, wallet_id=a, destination_wallet_id=m, amount=600, currency="USD")
    c = operations.capture_hold(session, owner, hold_id=h.resource_id, amount=450)
    assert c.succeeded
    assert balance(session, a) == {"posted": 550, "pending_outgoing": 0, "pending_incoming": 0, "available": 550}
    assert balance(session, m)["posted"] == 450
    again = operations.capture_hold(session, owner, hold_id=h.resource_id)
    assert again.error_code == "hold_not_active"
    _recon_ok(session, owner)


def test_hold_release_and_expiry(session: Session, owner: Actor) -> None:
    a = new_wallet(session, owner, funded=1_000)
    m = new_wallet(session, owner)
    h1 = operations.create_hold(session, owner, wallet_id=a, destination_wallet_id=m, amount=300, currency="USD")
    h2 = operations.create_hold(session, owner, wallet_id=a, destination_wallet_id=m, amount=200, currency="USD",
                                expires_in_seconds=60)
    assert operations.release_hold(session, owner, hold_id=h1.resource_id).succeeded
    assert balance(session, a)["available"] == 800
    assert operations.expire_holds(session, as_of=now() + timedelta(minutes=5)) == 1
    assert balance(session, a)["available"] == 1_000
    late = operations.capture_hold(session, owner, hold_id=h2.resource_id)
    assert late.error_code == "hold_not_active"
    _recon_ok(session, owner)


def test_capture_exceeding_hold_rejected(session: Session, owner: Actor) -> None:
    a = new_wallet(session, owner, funded=1_000)
    m = new_wallet(session, owner)
    h = operations.create_hold(session, owner, wallet_id=a, destination_wallet_id=m, amount=100, currency="USD")
    assert operations.capture_hold(session, owner, hold_id=h.resource_id, amount=101).error_code == "capture_exceeds_hold"


# Wallet lifecycle ----------------------------------------------------------------------


def test_suspended_wallet_cannot_send_or_receive(session: Session, owner: Actor) -> None:
    a = new_wallet(session, owner, funded=1_000)
    b = new_wallet(session, owner)
    wallets.set_wallet_status(session, owner, wallet_id=b, status=WalletStatus.SUSPENDED)
    r = operations.transfer(session, owner, source_wallet_id=a, destination_wallet_id=b, amount=1, currency="USD")
    assert r.error_code == "wallet_not_active"
    wallets.set_wallet_status(session, owner, wallet_id=b, status=WalletStatus.ACTIVE)
    assert operations.transfer(session, owner, source_wallet_id=a, destination_wallet_id=b, amount=1,
                               currency="USD").succeeded


def test_wallet_with_balance_cannot_close(session: Session, owner: Actor) -> None:
    from waltrix_core.errors import Conflict

    a = new_wallet(session, owner, funded=1)
    with pytest.raises(Conflict):
        wallets.set_wallet_status(session, owner, wallet_id=a, status=WalletStatus.CLOSED)
    operations.withdraw(session, owner, wallet_id=a, amount=1, currency="USD")
    assert wallets.set_wallet_status(session, owner, wallet_id=a, status=WalletStatus.CLOSED).status == "closed"


def test_withdraw_cannot_exceed_funding(session: Session, owner: Actor) -> None:
    a = new_wallet(session, owner, funded=50)
    assert operations.withdraw(session, owner, wallet_id=a, amount=51, currency="USD").error_code == "insufficient_funds"


def test_validation_errors_are_not_recorded(session: Session, owner: Actor) -> None:
    a = new_wallet(session, owner, funded=50)
    with pytest.raises(ValidationFailed):
        operations.transfer(session, owner, source_wallet_id=a, destination_wallet_id=uuid.uuid4(),
                            amount=1.5, currency="USD")  # type: ignore[arg-type]
    assert session.execute(select(Transaction).where(Transaction.status == "failed")).first() is None


def test_manual_entry_only_on_internal_accounts(session: Session, owner: Actor) -> None:
    rev = wallets.create_internal_account(session, owner, code="revenue:fees", name="Fees", type="revenue", currency="USD")
    exp = wallets.create_internal_account(session, owner, code="expense:promo", name="Promo", type="expense",
                                          currency="USD")
    ok = operations.post_manual_entry(session, owner, description="reclass", lines=[
        {"account_id": exp.id, "direction": "debit", "amount": 10, "currency": "USD"},
        {"account_id": rev.id, "direction": "credit", "amount": 10, "currency": "USD"},
    ])
    assert ok.succeeded
    exp_id, rev_id = exp.id, rev.id  # a rollback below expires ORM objects
    a = new_wallet(session, owner)
    acc = session.get_one(Wallet, a).account_id
    session.commit()
    with pytest.raises(ValidationFailed):
        operations.post_manual_entry(session, owner, description="sneaky", lines=[
            {"account_id": exp_id, "direction": "debit", "amount": 10, "currency": "USD"},
            {"account_id": acc, "direction": "credit", "amount": 10, "currency": "USD"},
        ])
    with pytest.raises(ValidationFailed):
        operations.post_manual_entry(session, owner, description="unbalanced", lines=[
            {"account_id": exp_id, "direction": "debit", "amount": 10, "currency": "USD"},
            {"account_id": rev_id, "direction": "credit", "amount": 9, "currency": "USD"},
        ])
    _recon_ok(session, owner)


def test_engine_requires_fresh_transaction(session: Session, owner: Actor) -> None:
    session.execute(select(Account)).all()  # autobegins
    with pytest.raises(RuntimeError):
        new_wallet(session, owner)
    session.rollback()


def test_ledger_invariant_type_is_internal() -> None:
    assert LedgerInvariantViolation.status_hint == 500
