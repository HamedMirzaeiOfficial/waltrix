"""SDK behavior: retries, idempotency-key reuse, error mapping, pagination, and a real-server round trip."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.fixtures import make_org
from waltrix import (
    AsyncWaltrix,
    IdempotencyConflictError,
    NotFoundError,
    OperationFailedError,
    UnknownOutcomeError,
    ValidationError,
    Waltrix,
)
from waltrix.client import APIConnectionError
from waltrix_core.enums import Role
from waltrix_core.services import identity

KEY = "wtx_key_test_secret"
TX = {"id": "t1", "status": "posted", "amount": 100, "currency": "USD"}


def _client(handler, **kw) -> Waltrix:  # type: ignore[no-untyped-def]
    c = Waltrix(KEY, http_client=httpx.Client(transport=httpx.MockTransport(handler)), backoff_base=0, **kw)
    c._sleep = lambda _: None
    return c


def test_retries_reuse_the_same_idempotency_key() -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.headers["Idempotency-Key"])
        if len(seen) < 3:
            raise httpx.ReadTimeout("slow", request=req)
        return httpx.Response(201, json=TX)

    assert _client(handler).transfers.create("a", "b", 100, "USD")["id"] == "t1"
    assert len(seen) == 3 and len(set(seen)) == 1


def test_explicit_key_is_sent() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["Idempotency-Key"] == "order-1"
        assert req.headers["Authorization"] == f"Bearer {KEY}"
        assert json.loads(req.content)["amount"] == 100
        return httpx.Response(201, json=TX)

    _client(handler).transfers.create("a", "b", 100, "USD", idempotency_key="order-1")


def test_exhausted_mutation_raises_unknown_outcome_with_key() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=req)

    with pytest.raises(UnknownOutcomeError) as info:
        _client(handler, max_retries=2).transfers.create("a", "b", 100, "USD", idempotency_key="k-9")
    assert info.value.idempotency_key == "k-9"


def test_503_on_mutation_is_unknown_outcome_not_failure() -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"error": {"code": "unavailable", "message": "x"}})

    with pytest.raises(UnknownOutcomeError):
        _client(handler, max_retries=1).holds.release("h1")
    assert calls == 2


def test_post_without_idempotency_key_is_never_retried() -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(UnknownOutcomeError):
        _client(handler).reconciliation.run()
    assert calls == 1


def test_get_retries_then_connection_error() -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("down", request=req)

    with pytest.raises(APIConnectionError):
        _client(handler, max_retries=2).wallets.get("w1")
    assert calls == 3


def test_concurrent_request_409_is_retried_and_retry_after_honored() -> None:
    delays: list[float] = []
    responses = [
        httpx.Response(409, json={"error": {"code": "concurrent_request", "message": "busy"}}),
        httpx.Response(
            429, headers={"Retry-After": "2"}, json={"error": {"code": "rate_limited", "message": "x"}}
        ),
        httpx.Response(201, json=TX),
    ]
    c = _client(lambda req: responses.pop(0))
    c._sleep = delays.append
    c.transfers.create("a", "b", 1, "USD")
    assert delays[1] == 2.0


def test_error_mapping() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/transfers"):
            return httpx.Response(
                422,
                json={
                    "error": {
                        "code": "insufficient_funds",
                        "message": "no",
                        "details": {"transaction_id": "t-failed"},
                        "correlation_id": "c1",
                    }
                },
            )
        if req.url.path.endswith("/reversals"):
            return httpx.Response(409, json={"error": {"code": "idempotency_key_reused", "message": "x"}})
        if req.url.path.endswith("/holds"):
            return httpx.Response(422, json={"error": {"code": "validation_failed", "message": "x"}})
        return httpx.Response(404, json={"error": {"code": "not_found", "message": "x"}})

    c = _client(handler)
    with pytest.raises(OperationFailedError) as info:
        c.transfers.create("a", "b", 1, "USD")
    assert info.value.transaction_id == "t-failed" and info.value.correlation_id == "c1"
    with pytest.raises(IdempotencyConflictError):
        c.reversals.create("t1")
    with pytest.raises(ValidationError):
        c.holds.create("a", "b", 1, "USD")
    with pytest.raises(NotFoundError):
        c.wallets.get("nope")


@pytest.mark.parametrize("amount", [1.5, True, 0, -1, 2**53])
def test_amount_validated_client_side(amount: object) -> None:
    c = _client(lambda req: httpx.Response(500))
    with pytest.raises((TypeError, ValueError)):
        c.transfers.create("a", "b", amount, "USD")  # type: ignore[arg-type]


def test_path_segments_cannot_escape() -> None:
    c = _client(lambda req: httpx.Response(200, json={}))
    with pytest.raises(ValueError):
        c.wallets.get("../api-keys")


def test_invalid_api_key_format_rejected() -> None:
    with pytest.raises(ValueError):
        Waltrix("sk_live_wrong")


def test_paginate_follows_cursors() -> None:
    pages = {
        None: {"data": [{"id": 1}, {"id": 2}], "next_cursor": "c2", "has_more": True},
        "c2": {"data": [{"id": 3}], "next_cursor": None, "has_more": False},
    }

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=pages[req.url.params.get("cursor")])

    c = _client(handler)
    assert [w["id"] for w in c.paginate(c.wallets.list, limit=2)] == [1, 2, 3]


def test_async_client_retries_with_same_key() -> None:
    seen: list[str] = []

    async def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.headers["Idempotency-Key"])
        if len(seen) == 1:
            raise httpx.ReadTimeout("slow", request=req)
        return httpx.Response(201, json=TX)

    async def main() -> None:
        c = AsyncWaltrix(KEY, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

        async def no_sleep(_: float) -> None:
            return None

        c._sleep = no_sleep
        assert (await c.transfers.create("a", "b", 100, "USD"))["id"] == "t1"
        await c.aclose()

    asyncio.run(main())
    assert len(seen) == 2 and seen[0] == seen[1]


# --- against the real API and database ---------------------------------------------------


def test_round_trip_against_real_server(client: TestClient, session: Session) -> None:
    actor, _ = make_org(session, "SDK Co")
    _, secret = identity.create_api_key(session, actor, name="sdk", role=Role.FINANCE_OPERATOR)
    sdk = Waltrix(secret, base_url="http://testserver", http_client=client)

    a = sdk.wallets.create("Alice", "cust_a", "USD")
    b = sdk.wallets.create("Bob", "cust_b", "USD")
    sdk.wallets.credit(a["id"], 5_000, "USD", idempotency_key="fund-a")
    replay = sdk.wallets.credit(a["id"], 5_000, "USD", idempotency_key="fund-a")
    assert sdk.wallets.balance(a["id"])["posted"] == 5_000  # replay did not double-fund
    assert replay["status"] == "posted"

    tx = sdk.transfers.create(a["id"], b["id"], 1_200, "USD", description="sdk transfer")
    detail = sdk.transactions.get(tx["id"])
    assert detail["status"] == "posted" and len(detail["journal_entries"]) == 1

    with pytest.raises(OperationFailedError) as info:
        sdk.transfers.create(a["id"], b["id"], 999_999, "USD")
    assert info.value.code == "insufficient_funds"
    assert sdk.transactions.get(info.value.transaction_id)["status"] == "failed"  # type: ignore[arg-type]

    hold = sdk.holds.create(a["id"], b["id"], 300, "USD")
    assert sdk.holds.capture(hold["id"], amount=100)["status"] == "captured"
    sdk.reversals.create(tx["id"], amount=200, reason="partial refund")

    all_tx = list(sdk.paginate(sdk.transactions.list, limit=2))
    assert len(all_tx) == 5  # credit, transfer, failed transfer, hold, reversal
    assert sdk.wallets.balance(a["id"])["posted"] == 5_000 - 1_200 - 100 + 200
