"""Exceptions raised by the Waltrix client."""

from __future__ import annotations

from typing import Any


class WaltrixError(Exception):
    """Base class for every SDK error."""


class APIError(WaltrixError):
    """The server answered with an error response (the outcome is known)."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        super().__init__(f"[{status} {code}] {message}")
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}
        self.correlation_id = correlation_id


class AuthenticationError(APIError): ...


class PermissionDeniedError(APIError): ...


class NotFoundError(APIError): ...


class ValidationError(APIError): ...


class ConflictError(APIError): ...


class IdempotencyConflictError(ConflictError):
    """The Idempotency-Key was already used with different parameters."""


class RateLimitError(APIError): ...


class ServerError(APIError): ...


class OperationFailedError(APIError):
    """A business rule rejected the operation (e.g. ``insufficient_funds``).

    The failure is final and recorded; ``transaction_id`` points at the FAILED
    transaction when one was created. Retrying with the same key returns the
    same failure.
    """

    @property
    def transaction_id(self) -> str | None:
        return self.details.get("transaction_id")


class UnknownOutcomeError(WaltrixError):
    """We could not get an answer (timeout, connection reset, 5xx) after all retries.

    The operation **may or may not** have been applied. Retry later with the
    same ``idempotency_key`` (safe: it cannot apply twice), or look the
    resource up before deciding.
    """

    def __init__(
        self, message: str, *, idempotency_key: str | None, cause: BaseException | None = None
    ) -> None:
        super().__init__(message)
        self.idempotency_key = idempotency_key
        self.__cause__ = cause


_BY_STATUS: dict[int, type[APIError]] = {
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    429: RateLimitError,
}

# 422 codes that come from validation rather than business rules.
_VALIDATION_CODES = {"validation_failed"}


def from_response(status: int, body: Any) -> APIError:
    err = body.get("error", {}) if isinstance(body, dict) else {}
    code = err.get("code", "unknown_error")
    message = err.get("message", "request failed")
    details = err.get("details") or {}
    cid = err.get("correlation_id")
    cls: type[APIError]
    if status == 409 and code == "idempotency_key_reused":
        cls = IdempotencyConflictError
    elif status == 422:
        cls = ValidationError if code in _VALIDATION_CODES else OperationFailedError
    elif status >= 500:
        cls = ServerError
    else:
        cls = _BY_STATUS.get(status, APIError)
    return cls(status, code, message, details, cid)
