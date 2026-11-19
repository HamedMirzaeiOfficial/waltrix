"""Domain errors.

Every error carries a stable machine-readable ``code``. Transport layers (the
REST API, a CLI, a host application) map them to their own representation; the
engine itself knows nothing about HTTP.

``BusinessRuleViolation`` subclasses are *deterministic* outcomes of a valid
request (insufficient funds, suspended wallet...). They are recorded as FAILED
transactions and replayed for idempotent retries. Anything else is treated as
a transient/unexpected failure: the database transaction rolls back completely
and the idempotency key stays free so the client can retry.
"""

from __future__ import annotations

from typing import Any


class WaltrixError(Exception):
    code = "waltrix_error"
    status_hint = 400

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = {k: v for k, v in details.items() if v is not None}


class ValidationFailed(WaltrixError):
    code = "validation_failed"
    status_hint = 422


class NotFound(WaltrixError):
    """Raised for missing resources *and* for resources of another tenant.

    The two cases are indistinguishable on purpose (no existence oracle).
    """

    code = "not_found"
    status_hint = 404


class PermissionDenied(WaltrixError):
    code = "permission_denied"
    status_hint = 403


class AuthenticationFailed(WaltrixError):
    code = "authentication_failed"
    status_hint = 401


class Conflict(WaltrixError):
    code = "conflict"
    status_hint = 409


class IdempotencyKeyReused(Conflict):
    code = "idempotency_key_reused"


class ConcurrentRequest(Conflict):
    """A competing request held the lock too long; safe to retry with the same key."""

    code = "concurrent_request"


class InvalidStateTransition(Conflict):
    code = "invalid_state_transition"


class LedgerInvariantViolation(WaltrixError):
    """A programming error tried to post something that breaks the ledger rules.

    Never recorded as a business failure: the whole database transaction is
    rolled back.
    """

    code = "ledger_invariant_violation"
    status_hint = 500


class BusinessRuleViolation(WaltrixError):
    status_hint = 422


class InsufficientFunds(BusinessRuleViolation):
    code = "insufficient_funds"


class WalletNotActive(BusinessRuleViolation):
    code = "wallet_not_active"


class AccountNotActive(BusinessRuleViolation):
    code = "account_not_active"


class CurrencyMismatch(BusinessRuleViolation):
    code = "currency_mismatch"


class SameWallet(BusinessRuleViolation):
    code = "same_wallet"


class HoldNotActive(BusinessRuleViolation):
    code = "hold_not_active"


class HoldExpired(BusinessRuleViolation):
    code = "hold_expired"


class CaptureExceedsHold(BusinessRuleViolation):
    code = "capture_exceeds_hold"


class NotReversible(BusinessRuleViolation):
    code = "not_reversible"


class ReversalExceedsRemaining(BusinessRuleViolation):
    code = "reversal_exceeds_remaining"
