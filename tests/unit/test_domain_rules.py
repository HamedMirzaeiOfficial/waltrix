"""Pure domain tests (no database): money, posting rules, state machines, permissions."""

from __future__ import annotations

import uuid

import pytest
from hypothesis import given
from hypothesis import strategies as st

from waltrix_core.enums import Direction, HoldStatus, NormalBalance, Role, TransactionStatus
from waltrix_core.errors import InvalidStateTransition, LedgerInvariantViolation, ValidationFailed
from waltrix_core.money import MAX_AMOUNT, Money, normalize_currency, validate_amount
from waltrix_core.permissions import API_KEY_ROLES, Permission, has_permission
from waltrix_core.rules import Line, available_balance, reversed_lines, validate_entry
from waltrix_core.state_machine import (
    HOLD_TRANSITIONS,
    TRANSACTION_TRANSITIONS,
    check_hold_transition,
    check_transaction_transition,
)

A, B, C = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
D, CR = Direction.DEBIT, Direction.CREDIT


class TestMoney:
    @pytest.mark.parametrize("bad", [1.5, 10.0, "10", None, True, False, 0, -1, MAX_AMOUNT + 1])
    def test_rejects_non_integer_or_out_of_range(self, bad: object) -> None:
        with pytest.raises(ValidationFailed):
            validate_amount(bad)

    def test_accepts_positive_ints(self) -> None:
        assert validate_amount(1) == 1
        assert validate_amount(MAX_AMOUNT) == MAX_AMOUNT

    @pytest.mark.parametrize("code", ["usd", " eur ", "JPY"])
    def test_currency_normalized(self, code: str) -> None:
        assert normalize_currency(code) == code.strip().upper()

    @pytest.mark.parametrize("code", ["US", "USDT", "XXX", "12A", ""])
    def test_currency_rejected(self, code: str) -> None:
        with pytest.raises(ValidationFailed):
            normalize_currency(code)

    def test_money_refuses_mixed_currency(self) -> None:
        with pytest.raises(ValueError):
            Money(100, "USD") + Money(100, "EUR")
        with pytest.raises(TypeError):
            Money(1.5, "USD")  # type: ignore[arg-type]

    def test_format_uses_minor_units(self) -> None:
        assert Money(123456, "USD").format() == "1,234.56 USD"
        assert Money(500, "JPY").format() == "500 JPY"


class TestPostingRules:
    def test_balanced_entry_is_valid(self) -> None:
        validate_entry([Line(A, D, 100, "USD"), Line(B, CR, 100, "USD")])

    def test_needs_two_lines(self) -> None:
        with pytest.raises(LedgerInvariantViolation):
            validate_entry([Line(A, D, 100, "USD")])

    def test_unbalanced_rejected(self) -> None:
        with pytest.raises(LedgerInvariantViolation, match="does not balance"):
            validate_entry([Line(A, D, 100, "USD"), Line(B, CR, 99, "USD")])

    def test_currencies_never_net_against_each_other(self) -> None:
        # Sum of numbers balances (100 == 100) but across currencies: must be rejected.
        with pytest.raises(LedgerInvariantViolation):
            validate_entry([Line(A, D, 100, "USD"), Line(B, CR, 100, "EUR")])

    def test_multi_currency_entry_balanced_per_currency(self) -> None:
        validate_entry(
            [
                Line(A, D, 100, "USD"),
                Line(B, CR, 100, "USD"),
                Line(C, D, 90, "EUR"),
                Line(uuid.uuid4(), CR, 90, "EUR"),
            ]
        )

    def test_same_account_both_sides_rejected(self) -> None:
        with pytest.raises(LedgerInvariantViolation):
            validate_entry([Line(A, D, 100, "USD"), Line(A, CR, 100, "USD")])

    @pytest.mark.parametrize("amount", [0, -5, 1.0])
    def test_non_positive_or_float_amount(self, amount: object) -> None:
        with pytest.raises(LedgerInvariantViolation):
            validate_entry([Line(A, D, amount, "USD"), Line(B, CR, amount, "USD")])  # type: ignore[arg-type]

    @given(
        st.lists(st.integers(min_value=1, max_value=10**12), min_size=1, max_size=8),
        st.integers(min_value=1, max_value=8),
    )
    def test_property_split_credits_balance(self, debits: list[int], n_credit: int) -> None:
        """Any set of debits balanced by an arbitrary split of credits is valid."""
        total = sum(debits)
        lines = [Line(uuid.uuid4(), D, amt, "USD") for amt in debits]
        n_credit = min(n_credit, total)
        share, rest = divmod(total, n_credit)
        credits = [share] * n_credit
        credits[0] += rest
        lines += [Line(uuid.uuid4(), CR, amt, "USD") for amt in credits]
        validate_entry(lines)
        # ...and its mirror image is valid too and exactly cancels it.
        mirror = reversed_lines(lines)
        validate_entry(mirror)
        net = sum((ln.amount if ln.direction is D else -ln.amount) for ln in lines + mirror)
        assert net == 0

    @given(st.lists(st.integers(min_value=1, max_value=10**9), min_size=2, max_size=6), st.integers(1, 10**6))
    def test_property_any_perturbation_is_rejected(self, amounts: list[int], delta: int) -> None:
        total = sum(amounts)
        lines = [Line(uuid.uuid4(), D, a, "USD") for a in amounts]
        lines.append(Line(uuid.uuid4(), CR, total + delta, "USD"))
        with pytest.raises(LedgerInvariantViolation):
            validate_entry(lines)

    def test_available_balance_excludes_incoming_pending(self) -> None:
        # credit-normal wallet: 1000 posted in, 200 held out, 500 pending in
        assert available_balance(NormalBalance.CREDIT, 0, 1000, 200, 500) == 800
        assert available_balance(NormalBalance.DEBIT, 1000, 0, 500, 200) == 800


class TestStateMachines:
    @pytest.mark.parametrize("current", list(TransactionStatus))
    @pytest.mark.parametrize("target", list(TransactionStatus))
    def test_transaction_transitions_exhaustive(
        self, current: TransactionStatus, target: TransactionStatus
    ) -> None:
        allowed = target in TRANSACTION_TRANSITIONS[current]
        if allowed:
            check_transaction_transition(current, target)
        else:
            with pytest.raises(InvalidStateTransition):
                check_transaction_transition(current, target)

    def test_terminal_states(self) -> None:
        assert TRANSACTION_TRANSITIONS[TransactionStatus.FAILED] == frozenset()
        assert TRANSACTION_TRANSITIONS[TransactionStatus.REVERSED] == frozenset()
        for s in (HoldStatus.CAPTURED, HoldStatus.RELEASED, HoldStatus.EXPIRED):
            assert HOLD_TRANSITIONS[s] == frozenset()
            with pytest.raises(InvalidStateTransition):
                check_hold_transition(s, HoldStatus.ACTIVE)

    def test_posted_cannot_go_back_to_pending(self) -> None:
        with pytest.raises(InvalidStateTransition):
            check_transaction_transition(TransactionStatus.POSTED, TransactionStatus.PENDING)


class TestPermissions:
    def test_viewer_cannot_move_money(self) -> None:
        assert not has_permission(Role.VIEWER, Permission.MONEY_MOVE)
        assert has_permission(Role.VIEWER, Permission.WALLETS_READ)

    def test_auditor_reads_audit_but_cannot_move_money(self) -> None:
        assert has_permission(Role.AUDITOR, Permission.AUDIT_READ)
        assert not has_permission(Role.AUDITOR, Permission.MONEY_MOVE)

    def test_finance_operator_cannot_manage_members_or_keys(self) -> None:
        assert has_permission(Role.FINANCE_OPERATOR, Permission.MONEY_MOVE)
        assert not has_permission(Role.FINANCE_OPERATOR, Permission.MEMBERS_MANAGE)
        assert not has_permission(Role.FINANCE_OPERATOR, Permission.API_KEYS_MANAGE)

    def test_admin_cannot_manage_org_owner_can(self) -> None:
        assert not has_permission(Role.ADMIN, Permission.ORG_MANAGE)
        assert has_permission(Role.OWNER, Permission.ORG_MANAGE)

    def test_api_keys_never_admin(self) -> None:
        assert Role.OWNER not in API_KEY_ROLES and Role.ADMIN not in API_KEY_ROLES
