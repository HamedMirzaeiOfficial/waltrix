"""Property-based (stateful) test: the ledger behaves exactly like a trivial model.

Hypothesis generates random sequences of wallet operations. After every step
the engine's balances must equal a tiny in-memory model, and at the end
reconciliation must pass. Each example uses a fresh organization.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, precondition, rule
from sqlalchemy.orm import Session, sessionmaker

from tests.fixtures import make_org
from tests.helpers import balance, new_wallet
from waltrix_core.services import operations, reconciliation

amounts = st.integers(min_value=1, max_value=2_000)


@pytest.fixture
def factory(session_factory: sessionmaker[Session]) -> sessionmaker[Session]:
    return session_factory


def test_ledger_matches_model(factory: sessionmaker[Session]) -> None:
    class LedgerMachine(RuleBasedStateMachine):
        @initialize()
        def setup(self) -> None:
            self.s = factory()
            self.actor, _ = make_org(self.s, "Prop")
            self.w = [new_wallet(self.s, self.actor) for _ in range(3)]
            self.posted = {w: 0 for w in self.w}
            self.held = {w: 0 for w in self.w}
            self.holds: dict[UUID, tuple[UUID, UUID, int]] = {}
            self.txs: dict[UUID, list[int]] = {}  # id -> [posted, reversed, src_idx, dst_idx]

        def avail(self, w: UUID) -> int:
            return self.posted[w] - self.held[w]

        @rule(i=st.integers(0, 2), amount=amounts)
        def deposit(self, i: int, amount: int) -> None:
            r = operations.deposit(self.s, self.actor, wallet_id=self.w[i], amount=amount, currency="USD")
            assert r.succeeded
            self.posted[self.w[i]] += amount

        @rule(i=st.integers(0, 2), amount=amounts)
        def withdraw(self, i: int, amount: int) -> None:
            w = self.w[i]
            r = operations.withdraw(self.s, self.actor, wallet_id=w, amount=amount, currency="USD")
            assert r.succeeded == (amount <= self.avail(w))
            if r.succeeded:
                self.posted[w] -= amount

        @rule(i=st.integers(0, 2), j=st.integers(0, 2), amount=amounts)
        def transfer(self, i: int, j: int, amount: int) -> None:
            a, b = self.w[i], self.w[j]
            r = operations.transfer(
                self.s, self.actor, source_wallet_id=a, destination_wallet_id=b, amount=amount, currency="USD"
            )
            expected = i != j and amount <= self.avail(a)
            assert r.succeeded == expected, (r, self.avail(a))
            if expected:
                self.posted[a] -= amount
                self.posted[b] += amount
                self.txs[r.resource_id] = [amount, 0, i, j]  # type: ignore[index]

        @rule(i=st.integers(0, 2), j=st.integers(0, 2), amount=amounts)
        def hold(self, i: int, j: int, amount: int) -> None:
            a, b = self.w[i], self.w[j]
            r = operations.create_hold(
                self.s, self.actor, wallet_id=a, destination_wallet_id=b, amount=amount, currency="USD"
            )
            expected = i != j and amount <= self.avail(a)
            assert r.succeeded == expected
            if expected:
                self.held[a] += amount
                self.holds[r.resource_id] = (a, b, amount)  # type: ignore[index]

        @precondition(lambda self: self.holds)
        @rule(data=st.data())
        def resolve_hold(self, data: st.DataObject) -> None:
            hid = data.draw(st.sampled_from(sorted(self.holds)))
            a, b, amount = self.holds.pop(hid)
            capture = data.draw(st.one_of(st.none(), st.integers(1, amount)))
            self.held[a] -= amount
            if data.draw(st.booleans()):
                assert operations.capture_hold(self.s, self.actor, hold_id=hid, amount=capture).succeeded
                got = amount if capture is None else capture
                self.posted[a] -= got
                self.posted[b] += got
            else:
                assert operations.release_hold(self.s, self.actor, hold_id=hid).succeeded

        @precondition(lambda self: self.txs)
        @rule(data=st.data())
        def reverse(self, data: st.DataObject) -> None:
            tid = data.draw(st.sampled_from(sorted(self.txs)))
            posted, reversed_, i, j = self.txs[tid]
            amount = data.draw(st.integers(1, posted))
            src, dst = self.w[j], self.w[i]  # reversal flows back
            r = operations.reverse_transaction(self.s, self.actor, transaction_id=tid, amount=amount)
            remaining = posted - reversed_
            expected = 0 < amount <= remaining and amount <= self.avail(src)
            assert r.succeeded == expected, (r, amount, remaining, self.avail(src))
            if expected:
                self.posted[src] -= amount
                self.posted[dst] += amount
                self.txs[tid][1] += amount

        @invariant()
        def balances_match_model(self) -> None:
            if not hasattr(self, "s"):
                return
            for w in self.w:
                v = balance(self.s, w)
                assert v["posted"] == self.posted[w]
                assert v["pending_outgoing"] == self.held[w]
                assert v["available"] >= 0

        def teardown(self) -> None:
            if hasattr(self, "s"):
                run = reconciliation.run_reconciliation(self.s, self.actor)
                assert run.status == "passed", run.findings
                self.s.close()

    LedgerMachine.TestCase.settings = settings(
        max_examples=12,
        stateful_step_count=20,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    LedgerMachine.TestCase().runTest()
