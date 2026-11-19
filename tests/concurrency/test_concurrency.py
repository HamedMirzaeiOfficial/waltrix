"""Concurrency guarantees under real PostgreSQL contention.

Each worker thread uses its own Session (own connection). A Barrier releases
all workers at the same instant to maximize contention.
"""

from __future__ import annotations

import random
import threading
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from tests.helpers import balance, new_wallet, total_wallet_liabilities
from waltrix_core.db.models import Hold, Transaction
from waltrix_core.enums import HoldStatus
from waltrix_core.errors import ConcurrentRequest
from waltrix_core.services import operations, reconciliation
from waltrix_core.services.context import Actor
from waltrix_core.services.ledger import now
from waltrix_core.services.runner import OperationResult


def run_concurrently(factory: sessionmaker[Session], n: int, fn: Callable[[Session, int], Any]) -> list[Any]:
    barrier = threading.Barrier(n)

    def worker(i: int) -> Any:
        s = factory()
        try:
            barrier.wait(timeout=30)
            return fn(s, i)
        except Exception as exc:  # collected and asserted by the test
            return exc
        finally:
            s.close()

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(worker, range(n)))


def test_concurrent_debits_cannot_overspend(
    session: Session, session_factory: sessionmaker[Session], owner: Actor
) -> None:
    src = new_wallet(session, owner, funded=1_000)
    dst = new_wallet(session, owner)
    results = run_concurrently(
        session_factory,
        40,
        lambda s, i: operations.transfer(
            s, owner, source_wallet_id=src, destination_wallet_id=dst, amount=100, currency="USD"
        ),
    )
    assert not [r for r in results if isinstance(r, Exception)], results
    outcomes = Counter(r.outcome for r in results)
    assert outcomes == {"succeeded": 10, "failed": 30}
    assert {r.error_code for r in results if not r.succeeded} == {"insufficient_funds"}
    assert balance(session, src)["posted"] == 0
    assert balance(session, dst)["posted"] == 1_000


def test_concurrent_holds_and_transfers_respect_available(
    session: Session, session_factory: sessionmaker[Session], owner: Actor
) -> None:
    src = new_wallet(session, owner, funded=1_000)
    dst = new_wallet(session, owner)

    def op(s: Session, i: int) -> OperationResult:
        if i % 2:
            return operations.create_hold(
                s, owner, wallet_id=src, destination_wallet_id=dst, amount=150, currency="USD"
            )
        return operations.transfer(
            s, owner, source_wallet_id=src, destination_wallet_id=dst, amount=150, currency="USD"
        )

    results = run_concurrently(session_factory, 30, op)
    assert not [r for r in results if isinstance(r, Exception)]
    view = balance(session, src)
    succeeded = sum(r.succeeded for r in results)
    assert succeeded == 6  # floor(1000 / 150)
    assert view["available"] == 1_000 - 150 * succeeded and view["available"] >= 0


def test_same_idempotency_key_concurrently_executes_once(
    session: Session, session_factory: sessionmaker[Session], owner: Actor
) -> None:
    src = new_wallet(session, owner, funded=1_000)
    dst = new_wallet(session, owner)
    results = run_concurrently(
        session_factory,
        25,
        lambda s, i: operations.transfer(
            s,
            owner,
            source_wallet_id=src,
            destination_wallet_id=dst,
            amount=300,
            currency="USD",
            idempotency_key="order-7781",
        ),
    )
    assert not [r for r in results if isinstance(r, Exception)], results
    assert len({r.resource_id for r in results}) == 1
    assert sum(not r.replayed for r in results) == 1
    assert balance(session, dst)["posted"] == 300
    count = session.execute(
        select(func.count()).select_from(Transaction).where(Transaction.type == "transfer")
    ).scalar()
    assert count == 1


def test_opposite_transfers_do_not_deadlock(
    session: Session, session_factory: sessionmaker[Session], owner: Actor
) -> None:
    a = new_wallet(session, owner, funded=10_000)
    b = new_wallet(session, owner, funded=10_000)

    def op(s: Session, i: int) -> OperationResult:
        src, dst = (a, b) if i % 2 else (b, a)
        return operations.transfer(
            s, owner, source_wallet_id=src, destination_wallet_id=dst, amount=10 + i, currency="USD"
        )

    results = run_concurrently(session_factory, 40, op)
    errors = [r for r in results if isinstance(r, Exception)]
    assert not errors, errors  # a deadlock would surface as ConcurrentRequest
    assert all(r.succeeded for r in results)
    assert balance(session, a)["posted"] + balance(session, b)["posted"] == 20_000


def test_capture_and_release_race_has_one_winner(
    session: Session, session_factory: sessionmaker[Session], owner: Actor
) -> None:
    src = new_wallet(session, owner, funded=1_000)
    dst = new_wallet(session, owner)
    hold_ids = [
        operations.create_hold(
            session, owner, wallet_id=src, destination_wallet_id=dst, amount=100, currency="USD"
        ).resource_id
        for _ in range(5)
    ]

    def op(s: Session, i: int) -> OperationResult:
        hid = hold_ids[i % 5]
        if i % 2:
            return operations.capture_hold(s, owner, hold_id=hid)
        return operations.release_hold(s, owner, hold_id=hid)

    results = run_concurrently(session_factory, 20, op)
    assert not [r for r in results if isinstance(r, Exception)]
    assert sum(r.succeeded for r in results) == 5  # exactly one winner per hold
    captured = session.execute(
        select(func.count()).select_from(Hold).where(Hold.status == HoldStatus.CAPTURED)
    ).scalar()
    session.commit()
    assert balance(session, dst)["posted"] == 100 * captured
    assert reconciliation.run_reconciliation(session, owner).status == "passed"


def test_parallel_expiry_workers_never_double_release(
    session: Session, session_factory: sessionmaker[Session], owner: Actor
) -> None:
    src = new_wallet(session, owner, funded=10_000)
    dst = new_wallet(session, owner)
    for _ in range(30):
        operations.create_hold(
            session,
            owner,
            wallet_id=src,
            destination_wallet_id=dst,
            amount=100,
            currency="USD",
            expires_in_seconds=1,
        )
    later = now() + timedelta(minutes=1)
    results = run_concurrently(session_factory, 6, lambda s, i: operations.expire_holds(s, as_of=later))
    assert not [r for r in results if isinstance(r, Exception)], results
    assert sum(results) == 30
    assert balance(session, src) == {
        "posted": 10_000,
        "pending_outgoing": 0,
        "pending_incoming": 0,
        "available": 10_000,
    }
    assert reconciliation.run_reconciliation(session, owner).status == "passed"


def test_reversal_race_cannot_double_refund(
    session: Session, session_factory: sessionmaker[Session], owner: Actor
) -> None:
    a = new_wallet(session, owner, funded=1_000)
    b = new_wallet(session, owner)
    t = operations.transfer(
        session, owner, source_wallet_id=a, destination_wallet_id=b, amount=500, currency="USD"
    )
    results = run_concurrently(
        session_factory,
        12,
        lambda s, i: operations.reverse_transaction(s, owner, transaction_id=t.resource_id, amount=100),
    )
    assert not [r for r in results if isinstance(r, Exception)]
    assert sum(r.succeeded for r in results) == 5
    assert balance(session, a)["posted"] == 1_000
    assert reconciliation.run_reconciliation(session, owner).status == "passed"


@pytest.mark.stress
def test_stress_random_operations_preserve_invariants(
    session: Session, session_factory: sessionmaker[Session], owner: Actor
) -> None:
    """16 threads x 30 random operations on 6 overlapping wallets."""
    n_wallets, threads, ops_per_thread = 6, 16, 30
    wallets_ = [new_wallet(session, owner, funded=5_000) for _ in range(n_wallets)]
    deposited = 5_000 * n_wallets
    lock = threading.Lock()
    external = {"in": 0, "out": 0}
    hold_pool: list[UUID] = []
    posted_tx: list[UUID] = []

    def worker(s: Session, i: int) -> Counter[str]:
        rng = random.Random(i)
        stats: Counter[str] = Counter()
        for n in range(ops_per_thread):
            x, y = rng.sample(wallets_, 2)
            amount = rng.randint(1, 900)
            choice = rng.random()
            try:
                if choice < 0.45:
                    r = operations.transfer(
                        s,
                        owner,
                        source_wallet_id=x,
                        destination_wallet_id=y,
                        amount=amount,
                        currency="USD",
                        idempotency_key=f"t-{i}-{n}",
                    )
                    if r.succeeded:
                        with lock:
                            posted_tx.append(r.resource_id)  # type: ignore[arg-type]
                    # Retry of the same request (as a client would after a timeout): never doubles.
                    assert operations.transfer(
                        s,
                        owner,
                        source_wallet_id=x,
                        destination_wallet_id=y,
                        amount=amount,
                        currency="USD",
                        idempotency_key=f"t-{i}-{n}",
                    ).replayed
                elif choice < 0.6:
                    r = operations.create_hold(
                        s, owner, wallet_id=x, destination_wallet_id=y, amount=amount, currency="USD"
                    )
                    if r.succeeded:
                        with lock:
                            hold_pool.append(r.resource_id)  # type: ignore[arg-type]
                elif choice < 0.75:
                    with lock:
                        hid = hold_pool.pop() if hold_pool else None
                    if hid is None:
                        continue
                    r = (
                        operations.capture_hold(s, owner, hold_id=hid, amount=rng.randint(1, 50))
                        if rng.random() < 0.6
                        else operations.release_hold(s, owner, hold_id=hid)
                    )
                elif choice < 0.85:
                    with lock:
                        tid = rng.choice(posted_tx) if posted_tx else None
                    if tid is None:
                        continue
                    r = operations.reverse_transaction(
                        s, owner, transaction_id=tid, amount=rng.randint(1, 50)
                    )
                elif choice < 0.93:
                    r = operations.deposit(s, owner, wallet_id=x, amount=amount, currency="USD")
                    if r.succeeded:
                        with lock:
                            external["in"] += amount
                else:
                    r = operations.withdraw(s, owner, wallet_id=x, amount=amount, currency="USD")
                    if r.succeeded:
                        with lock:
                            external["out"] += amount
                stats[r.outcome] += 1
            except ConcurrentRequest:
                stats["busy"] += 1
        return stats

    results = run_concurrently(session_factory, threads, worker)
    errors = [r for r in results if isinstance(r, Exception)]
    assert not errors, errors
    totals: Counter[str] = sum(results, Counter())
    assert totals["succeeded"] > 100

    expected = deposited + external["in"] - external["out"]
    assert total_wallet_liabilities(session, owner.org_id, "USD") == expected
    negatives = session.execute(
        text(
            "SELECT count(*) FROM accounts WHERE NOT allow_negative AND "
            "posted_credits - posted_debits - pending_debits < 0 AND normal_balance = 'credit'"
        )
    ).scalar()
    session.commit()
    assert negatives == 0
    run = reconciliation.run_reconciliation(session, owner)
    assert run.status == "passed", run.findings
    print(f"\nstress: {dict(totals)} external={external} entries={run.summary['counts']}")
