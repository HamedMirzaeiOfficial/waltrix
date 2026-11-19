"""Sync (``Waltrix``) and async (``AsyncWaltrix``) clients.

Retry policy:

* Only *retry-safe* requests are retried: GETs, and POSTs carrying an
  ``Idempotency-Key`` (every money-moving method generates one automatically
  and reuses it across attempts).
* Retried conditions: timeouts, connection errors, HTTP 429, 502/503/504 and
  409 ``concurrent_request``. ``Retry-After`` is honored.
* Backoff: exponential with full jitter (``backoff_base * 2**attempt``,
  capped at ``backoff_max``).
* If a mutation still has no answer after the last attempt we raise
  ``UnknownOutcomeError`` with the idempotency key - never a silent success
  or a silent failure.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
from typing import Any, Concatenate, ParamSpec, TypeVar

import httpx

from . import _endpoints as ep
from .errors import APIError, UnknownOutcomeError, WaltrixError, from_response
from .types import Page

__version__ = "0.1.0"

P = ParamSpec("P")
T = TypeVar("T")
RETRY_STATUSES = {429, 502, 503, 504}
DEFAULT_BASE_URL = "http://127.0.0.1:4820"


class APIConnectionError(WaltrixError):
    """A read request could not reach the server after all retries."""


class _Base:
    def __init__(
        self,
        api_key: str | None,
        base_url: str,
        timeout: float,
        max_retries: int,
        backoff_base: float,
        backoff_max: float,
        default_headers: Mapping[str, str] | None,
    ) -> None:
        if api_key is not None and not api_key.startswith("wtx_key_"):
            raise ValueError("api_key must start with 'wtx_key_'")
        self.base_url = base_url.rstrip("/") + "/api/v1"
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self._headers = {"User-Agent": f"waltrix-python/{__version__}", "Accept": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        self._headers.update(default_headers or {})

    def _request_kwargs(self, spec: ep.Spec[Any]) -> dict[str, Any]:
        headers = dict(self._headers)
        if spec.idempotency_key:
            headers["Idempotency-Key"] = spec.idempotency_key
        return {
            "method": spec.method,
            "url": self.base_url + spec.path,
            "params": spec.params or None,
            "json": spec.json,
            "headers": headers,
            "timeout": self.timeout,
        }

    def _delay(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None and (ra := response.headers.get("retry-after")):
            try:
                return min(float(ra), self.backoff_max * 4)
            except ValueError:
                pass
        cap = min(self.backoff_max, self.backoff_base * (2**attempt))
        return random.uniform(0, cap)  # noqa: S311 - jitter, not security

    @staticmethod
    def _retryable_response(response: httpx.Response) -> bool:
        if response.status_code in RETRY_STATUSES:
            return True
        if response.status_code == 409:
            try:
                code = response.json().get("error", {}).get("code")
            except ValueError:
                return False
            return bool(code == "concurrent_request")
        return False

    @staticmethod
    def _parse(response: httpx.Response) -> Any:
        if response.status_code == 204:
            return None
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.is_success:
            return body
        raise from_response(response.status_code, body)

    def _give_up(self, spec: ep.Spec[Any], exc: BaseException | None, response: httpx.Response | None) -> Any:
        if response is not None and not (spec.method != "GET" and response.status_code >= 500):
            return self._parse(response)  # a definitive answer (e.g. 429 after retries)
        if spec.method == "GET":
            raise APIConnectionError(f"could not reach Waltrix: {exc!r}") from exc
        raise UnknownOutcomeError(
            "no definitive answer from the server; the operation may or may not have been applied. "
            "Retry with the same idempotency key.",
            idempotency_key=spec.idempotency_key,
            cause=exc,
        )


def _sync(fn: Callable[P, ep.Spec[T]]) -> Callable[Concatenate[Any, P], T]:
    def method(self: Any, /, *args: P.args, **kwargs: P.kwargs) -> T:
        result: T = self._client._send(fn(*args, **kwargs))
        return result

    method.__doc__ = fn.__doc__
    method.__name__ = fn.__name__
    return method


def _async(fn: Callable[P, ep.Spec[T]]) -> Callable[Concatenate[Any, P], Awaitable[T]]:
    async def method(self: Any, /, *args: P.args, **kwargs: P.kwargs) -> T:
        result: T = await self._client._send(fn(*args, **kwargs))
        return result

    method.__doc__ = fn.__doc__
    method.__name__ = fn.__name__
    return method


class _Resource:
    def __init__(self, client: Any) -> None:
        self._client = client


# --- sync ---------------------------------------------------------------------------------


class Wallets(_Resource):
    create = _sync(ep.create_wallet)
    get = _sync(ep.get_wallet)
    list = _sync(ep.list_wallets)
    balance = _sync(ep.get_balance)
    credit = _sync(ep.credit_wallet)
    debit = _sync(ep.debit_wallet)
    suspend = _sync(ep.suspend_wallet)
    activate = _sync(ep.activate_wallet)
    statement = _sync(ep.wallet_statement)


class Transfers(_Resource):
    create = _sync(ep.create_transfer)
    get = _sync(ep.get_transaction)


class Transactions(_Resource):
    list = _sync(ep.list_transactions)
    get = _sync(ep.get_transaction)


class Holds(_Resource):
    create = _sync(ep.create_hold)
    get = _sync(ep.get_hold)
    list = _sync(ep.list_holds)
    capture = _sync(ep.capture_hold)
    release = _sync(ep.release_hold)


class Reversals(_Resource):
    create = _sync(ep.create_reversal)


class JournalEntries(_Resource):
    list = _sync(ep.list_journal_entries)
    get = _sync(ep.get_journal_entry)


class Reconciliation(_Resource):
    run = _sync(ep.run_reconciliation)
    list = _sync(ep.list_reconciliation_runs)


class AuditEvents(_Resource):
    list = _sync(ep.list_audit_events)


class Waltrix(_Base):
    """Synchronous client.

    >>> client = Waltrix(api_key="wtx_key_...", base_url="http://127.0.0.1:4820")
    >>> tx = client.transfers.create(src, dst, 1250, "USD", idempotency_key="order-81")
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_base: float = 0.25,
        backoff_max: float = 4.0,
        default_headers: Mapping[str, str] | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        super().__init__(api_key, base_url, timeout, max_retries, backoff_base, backoff_max, default_headers)
        self._http = http_client or httpx.Client()
        self._owns_http = http_client is None
        self._sleep: Callable[[float], None] = time.sleep
        self.wallets = Wallets(self)
        self.transfers = Transfers(self)
        self.transactions = Transactions(self)
        self.holds = Holds(self)
        self.reversals = Reversals(self)
        self.journal_entries = JournalEntries(self)
        self.reconciliation = Reconciliation(self)
        self.audit_events = AuditEvents(self)

    def _send(self, spec: ep.Spec[T]) -> T:
        attempts = self.max_retries + 1 if spec.retry_safe else 1
        last_exc: BaseException | None = None
        last_resp: httpx.Response | None = None
        for attempt in range(attempts):
            try:
                resp = self._http.request(**self._request_kwargs(spec))
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc, last_resp = exc, None
            else:
                if not self._retryable_response(resp):
                    return self._parse(resp)  # type: ignore[no-any-return]
                last_exc, last_resp = None, resp
            if attempt + 1 < attempts:
                self._sleep(self._delay(attempt, last_resp))
        return self._give_up(spec, last_exc, last_resp)  # type: ignore[no-any-return]

    def paginate(self, list_method: Callable[..., Page[T]], **params: Any) -> Iterator[T]:
        """Iterate every item across pages: ``for w in client.paginate(client.wallets.list): ...``."""
        cursor: str | None = None
        while True:
            page = list_method(**params, **({"cursor": cursor} if cursor else {}))
            yield from page["data"]
            if not page["has_more"]:
                return
            cursor = page["next_cursor"]

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> Waltrix:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


# --- async ------------------------------------------------------------------------------


class AsyncWallets(_Resource):
    create = _async(ep.create_wallet)
    get = _async(ep.get_wallet)
    list = _async(ep.list_wallets)
    balance = _async(ep.get_balance)
    credit = _async(ep.credit_wallet)
    debit = _async(ep.debit_wallet)
    suspend = _async(ep.suspend_wallet)
    activate = _async(ep.activate_wallet)
    statement = _async(ep.wallet_statement)


class AsyncTransfers(_Resource):
    create = _async(ep.create_transfer)
    get = _async(ep.get_transaction)


class AsyncTransactions(_Resource):
    list = _async(ep.list_transactions)
    get = _async(ep.get_transaction)


class AsyncHolds(_Resource):
    create = _async(ep.create_hold)
    get = _async(ep.get_hold)
    list = _async(ep.list_holds)
    capture = _async(ep.capture_hold)
    release = _async(ep.release_hold)


class AsyncReversals(_Resource):
    create = _async(ep.create_reversal)


class AsyncJournalEntries(_Resource):
    list = _async(ep.list_journal_entries)
    get = _async(ep.get_journal_entry)


class AsyncReconciliation(_Resource):
    run = _async(ep.run_reconciliation)
    list = _async(ep.list_reconciliation_runs)


class AsyncAuditEvents(_Resource):
    list = _async(ep.list_audit_events)


class AsyncWaltrix(_Base):
    """Asynchronous client with the same surface: ``await client.transfers.create(...)``."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_base: float = 0.25,
        backoff_max: float = 4.0,
        default_headers: Mapping[str, str] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(api_key, base_url, timeout, max_retries, backoff_base, backoff_max, default_headers)
        self._http = http_client or httpx.AsyncClient()
        self._owns_http = http_client is None
        self._sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
        self.wallets = AsyncWallets(self)
        self.transfers = AsyncTransfers(self)
        self.transactions = AsyncTransactions(self)
        self.holds = AsyncHolds(self)
        self.reversals = AsyncReversals(self)
        self.journal_entries = AsyncJournalEntries(self)
        self.reconciliation = AsyncReconciliation(self)
        self.audit_events = AsyncAuditEvents(self)

    async def _send(self, spec: ep.Spec[T]) -> T:
        attempts = self.max_retries + 1 if spec.retry_safe else 1
        last_exc: BaseException | None = None
        last_resp: httpx.Response | None = None
        for attempt in range(attempts):
            try:
                resp = await self._http.request(**self._request_kwargs(spec))
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc, last_resp = exc, None
            else:
                if not self._retryable_response(resp):
                    return self._parse(resp)  # type: ignore[no-any-return]
                last_exc, last_resp = None, resp
            if attempt + 1 < attempts:
                await self._sleep(self._delay(attempt, last_resp))
        return self._give_up(spec, last_exc, last_resp)  # type: ignore[no-any-return]

    async def paginate(
        self, list_method: Callable[..., Awaitable[Page[T]]], **params: Any
    ) -> AsyncIterator[T]:
        cursor: str | None = None
        while True:
            page = await list_method(**params, **({"cursor": cursor} if cursor else {}))
            for item in page["data"]:
                yield item
            if not page["has_more"]:
                return
            cursor = page["next_cursor"]

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> AsyncWaltrix:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()


__all__ = ["APIConnectionError", "APIError", "AsyncWaltrix", "Waltrix"]
