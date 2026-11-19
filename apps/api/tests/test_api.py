"""HTTP-level tests: authentication, authorization, tenancy, validation, idempotency, pagination."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from apps.api.tests.conftest import Dashboard


def _key(dash: Dashboard, role: str = "finance_operator") -> str:
    r = dash.request("POST", "/api/v1/api-keys", json={"name": "server", "role": role})
    assert r.status_code == 201, r.text
    assert r.json()["secret"].startswith("wtx_key_")
    return r.json()["secret"]


def _bearer(key: str, **extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}", **extra}


# --- authentication -----------------------------------------------------------------


def test_requires_authentication(client: TestClient) -> None:
    r = client.get("/api/v1/wallets")
    assert r.status_code == 401
    body = r.json()["error"]
    assert body["code"] == "authentication_failed" and body["correlation_id"]


def test_login_failure_is_generic(client: TestClient, dash: Dashboard) -> None:
    wrong_pw = client.post("/api/v1/auth/login", json={"email": dash.email, "password": "nope-nope-nope"})
    unknown = client.post(
        "/api/v1/auth/login", json={"email": "ghost@acme.test", "password": "nope-nope-nope"}
    )
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_session_cookie_flags(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json={"email": "c@acme.test", "password": "correct-horse-battery"})
    r = client.post("/api/v1/auth/login", json={"email": "c@acme.test", "password": "correct-horse-battery"})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api" in cookie


def test_cookie_auth_requires_csrf_header_on_mutations(dash: Dashboard) -> None:
    dash.client.cookies.clear()
    dash.client.cookies.set("waltrix_session", dash.cookie)
    r = dash.client.post(
        "/api/v1/wallets",
        json={"name": "x", "owner_reference": "x", "currency": "USD"},
        headers={"X-Waltrix-Organization": dash.org_id},
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"


def test_logout_revokes_session(dash: Dashboard) -> None:
    assert dash.request("POST", "/api/v1/auth/logout").status_code == 204
    assert dash.request("GET", "/api/v1/auth/me").status_code == 401


def test_login_rate_limited(client: TestClient) -> None:
    codes = [
        client.post("/api/v1/auth/login", json={"email": "x@y.test", "password": "zzzzzzzzzz"}).status_code
        for _ in range(12)
    ]
    assert codes[-1] == 429 and 401 in codes


# --- tenancy and roles ---------------------------------------------------------------------


def test_cross_tenant_access_is_404(client: TestClient, dash: Dashboard) -> None:
    mine = dash.wallet("Mine", fund=1_000)
    other = Dashboard(client, "boss@globex.test", "Globex")
    theirs = other.wallet("Theirs", fund=1_000)

    assert dash.request("GET", f"/api/v1/wallets/{theirs}").status_code == 404
    r = dash.request(
        "POST",
        "/api/v1/transfers",
        headers={"Idempotency-Key": "x1"},
        json={"source_wallet_id": mine, "destination_wallet_id": theirs, "amount": 1, "currency": "USD"},
    )
    assert r.status_code == 404
    # A user cannot switch to an organization they don't belong to by changing the header.
    r = dash.request("GET", "/api/v1/wallets", headers={"X-Waltrix-Organization": other.org_id})
    assert r.status_code == 404
    # Random UUIDs and other tenants' ids look identical (no enumeration oracle).
    a = dash.request("GET", f"/api/v1/transactions/{uuid.uuid4()}").json()["error"]
    tx = other.request("GET", "/api/v1/transactions").json()["data"][0]["id"]
    b = dash.request("GET", f"/api/v1/transactions/{tx}").json()["error"]
    assert (a["code"], a["message"]) == (b["code"], b["message"])


def test_api_key_is_bound_to_its_org(client: TestClient, dash: Dashboard) -> None:
    key = _key(dash)
    other = Dashboard(client, "boss@initech.test", "Initech")
    other.wallet("Theirs")
    client.cookies.clear()
    r = client.get("/api/v1/wallets", headers=_bearer(key, **{"X-Waltrix-Organization": other.org_id}))
    assert r.status_code == 200 and r.json()["data"] == []  # header ignored; own (empty) org returned


def test_role_permissions_enforced(client: TestClient, dash: Dashboard) -> None:
    a = dash.wallet("A", fund=500)
    b = dash.wallet("B")
    viewer_key = _key(dash, "viewer")
    auditor_key = _key(dash, "auditor")
    client.cookies.clear()
    body = {"source_wallet_id": a, "destination_wallet_id": b, "amount": 1, "currency": "USD"}
    r = client.post("/api/v1/transfers", json=body, headers=_bearer(viewer_key, **{"Idempotency-Key": "v"}))
    assert r.status_code == 403 and r.json()["error"]["code"] == "permission_denied"
    assert client.get("/api/v1/audit-events", headers=_bearer(viewer_key)).status_code == 403
    assert client.get("/api/v1/audit-events", headers=_bearer(auditor_key)).status_code == 200
    assert (
        client.post(
            "/api/v1/api-keys", json={"name": "x", "role": "viewer"}, headers=_bearer(auditor_key)
        ).status_code
        == 403
    )


def test_no_privilege_escalation_via_members(client: TestClient, dash: Dashboard) -> None:
    Dashboard(client, "op@acme.test", None)
    r = dash.request(
        "POST",
        "/api/v1/organizations/current/members",
        json={"email": "op@acme.test", "role": "finance_operator"},
    )
    assert r.status_code == 201
    members = dash.request("GET", "/api/v1/organizations/current/members").json()
    owner = next(m for m in members if m["role"] == "owner")
    # The only owner cannot be demoted.
    r = dash.request("PATCH", f"/api/v1/organizations/current/members/{owner['id']}", json={"role": "viewer"})
    assert r.status_code == 409


def test_revoked_and_rotated_keys(client: TestClient, dash: Dashboard) -> None:
    key = _key(dash)
    key_id = dash.request("GET", "/api/v1/api-keys").json()[0]["id"]
    r = dash.request("POST", f"/api/v1/api-keys/{key_id}/rotate", json={"grace_hours": 0})
    new = r.json()["secret"]
    client.cookies.clear()
    assert client.get("/api/v1/wallets", headers=_bearer(key)).status_code == 401
    assert client.get("/api/v1/wallets", headers=_bearer(new)).status_code == 200
    listed = dash.request("GET", "/api/v1/api-keys").json()
    assert all("secret" not in k and "secret_hash" not in k for k in listed)


# --- financial endpoints ------------------------------------------------------------------


def test_transfer_flow_and_idempotency(dash: Dashboard) -> None:
    a = dash.wallet("Alice", fund=10_000)
    b = dash.wallet("Bob")
    body = {
        "source_wallet_id": a,
        "destination_wallet_id": b,
        "amount": 2_550,
        "currency": "USD",
        "description": "Dinner",
    }
    r1 = dash.request("POST", "/api/v1/transfers", json=body, headers={"Idempotency-Key": "t-1"})
    assert r1.status_code == 201, r1.text
    tx = r1.json()
    assert tx["status"] == "posted" and tx["amount"] == 2_550
    r2 = dash.request("POST", "/api/v1/transfers", json=body, headers={"Idempotency-Key": "t-1"})
    assert (
        r2.status_code == 201 and r2.headers["Idempotent-Replayed"] == "true" and r2.json()["id"] == tx["id"]
    )
    r3 = dash.request(
        "POST", "/api/v1/transfers", json={**body, "amount": 1}, headers={"Idempotency-Key": "t-1"}
    )
    assert r3.status_code == 409 and r3.json()["error"]["code"] == "idempotency_key_reused"
    assert dash.request("GET", f"/api/v1/wallets/{b}/balance").json()["posted"] == 2_550

    detail = dash.request("GET", f"/api/v1/transactions/{tx['id']}").json()
    (entry,) = detail["journal_entries"]
    assert {(p["direction"], p["amount"], p["wallet_id"]) for p in entry["postings"]} == {
        ("debit", 2_550, a),
        ("credit", 2_550, b),
    }


def test_missing_idempotency_key_rejected(dash: Dashboard) -> None:
    a = dash.wallet("A", fund=100)
    r = dash.request("POST", f"/api/v1/wallets/{a}/debit", json={"amount": 1, "currency": "USD"})
    err = r.json()["error"]
    assert r.status_code == 422 and err["code"] == "validation_failed"
    assert any("Idempotency-Key" in f["field"] for f in err["details"]["fields"])


def test_insufficient_funds_returns_422_with_failed_transaction(dash: Dashboard) -> None:
    a = dash.wallet("A", fund=100)
    b = dash.wallet("B")
    r = dash.request(
        "POST",
        "/api/v1/transfers",
        headers={"Idempotency-Key": "big"},
        json={"source_wallet_id": a, "destination_wallet_id": b, "amount": 101, "currency": "USD"},
    )
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "insufficient_funds"
    failed = dash.request("GET", f"/api/v1/transactions/{err['details']['transaction_id']}").json()
    assert failed["status"] == "failed" and failed["journal_entries"] == []


@pytest.mark.parametrize("amount", [10.5, "100", True, 0, -3, 2**53])
def test_amount_validation(dash: Dashboard, amount: object) -> None:
    a = dash.wallet("A", fund=100)
    b = dash.wallet("B")
    r = dash.request(
        "POST",
        "/api/v1/transfers",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"source_wallet_id": a, "destination_wallet_id": b, "amount": amount, "currency": "USD"},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_failed"


def test_unknown_fields_rejected(dash: Dashboard) -> None:
    r = dash.request(
        "POST",
        "/api/v1/wallets",
        json={"name": "x", "owner_reference": "y", "currency": "USD", "balance": 1_000_000},
    )
    assert r.status_code == 422


def test_holds_and_reversal_endpoints(dash: Dashboard) -> None:
    a = dash.wallet("A", fund=1_000)
    m = dash.wallet("Merchant")
    h = dash.request(
        "POST",
        "/api/v1/holds",
        headers={"Idempotency-Key": "h1"},
        json={"wallet_id": a, "destination_wallet_id": m, "amount": 400, "currency": "USD"},
    ).json()
    assert h["status"] == "active"
    bal = dash.request("GET", f"/api/v1/wallets/{a}/balance").json()
    assert (bal["available"], bal["pending_outgoing"]) == (600, 400)
    c = dash.request(
        "POST", f"/api/v1/holds/{h['id']}/capture", json={"amount": 250}, headers={"Idempotency-Key": "c1"}
    )
    assert c.status_code == 200 and c.json()["captured_amount"] == 250
    rev = dash.request(
        "POST",
        "/api/v1/reversals",
        headers={"Idempotency-Key": "r1"},
        json={"transaction_id": h["transaction_id"], "amount": 50, "reason": "partial refund"},
    )
    assert rev.status_code == 201 and rev.json()["type"] == "reversal"
    assert dash.request("GET", f"/api/v1/wallets/{a}/balance").json()["available"] == 800
    stmt = dash.request("GET", f"/api/v1/wallets/{a}/statement").json()
    assert stmt["closing_balance"] == 800 and [ln["balance_after"] for ln in stmt["lines"]] == [
        1_000,
        750,
        800,
    ]


def test_wallet_status_endpoints(dash: Dashboard) -> None:
    a = dash.wallet("A", fund=10)
    assert (
        dash.request("POST", f"/api/v1/wallets/{a}/suspend", json={"reason": "kyc"}).json()["status"]
        == "suspended"
    )
    assert dash.request("POST", f"/api/v1/wallets/{a}/close").status_code == 409
    assert dash.request("POST", f"/api/v1/wallets/{a}/activate").json()["status"] == "active"


def test_reconciliation_and_audit(dash: Dashboard) -> None:
    dash.wallet("A", fund=100)
    run = dash.request("POST", "/api/v1/reconciliation/runs")
    assert run.status_code == 201 and run.json()["status"] == "passed"
    events = dash.request("GET", "/api/v1/audit-events").json()["data"]
    actions = {e["action"] for e in events}
    assert {"wallet.created", "deposit.posted", "reconciliation.run", "organization.created"} <= actions
    assert all(e["correlation_id"] for e in events if e["action"] == "deposit.posted")


def test_overview_uses_real_data(dash: Dashboard) -> None:
    dash.wallet("A", fund=1_234)
    dash.wallet("E", "EUR", fund=99)
    o = dash.request("GET", "/api/v1/overview").json()
    assert {b["currency"]: b["total_posted"] for b in o["balances"]} == {"EUR": 99, "USD": 1_234}
    assert o["transaction_counts"] == {"posted": 2}


# --- pagination, errors, health -------------------------------------------------------------


def test_cursor_pagination_is_complete_and_stable(dash: Dashboard) -> None:
    ids = {dash.wallet(f"W{i}") for i in range(7)}
    seen: list[str] = []
    cursor = None
    while True:
        params = {"limit": 3, **({"cursor": cursor} if cursor else {})}
        page = dash.request("GET", "/api/v1/wallets", params=params).json()
        seen += [w["id"] for w in page["data"]]
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
    assert len(seen) == len(set(seen)) == 7 and set(seen) == ids
    assert dash.request("GET", "/api/v1/wallets", params={"limit": 500}).status_code == 422
    assert dash.request("GET", "/api/v1/wallets", params={"cursor": "garbage!"}).status_code == 422


def test_transaction_filters(dash: Dashboard) -> None:
    a = dash.wallet("A", fund=100)
    b = dash.wallet("B")
    dash.request(
        "POST",
        "/api/v1/transfers",
        headers={"Idempotency-Key": "f1"},
        json={"source_wallet_id": a, "destination_wallet_id": b, "amount": 500, "currency": "USD"},
    )
    failed = dash.request("GET", "/api/v1/transactions", params={"status": "failed"}).json()["data"]
    assert len(failed) == 1 and failed[0]["failure_code"] == "insufficient_funds"
    by_wallet = dash.request("GET", "/api/v1/transactions", params={"wallet_id": b}).json()["data"]
    assert len(by_wallet) == 1
    assert dash.request("GET", "/api/v1/transactions", params={"status": "bogus"}).status_code == 422


def test_correlation_id_propagates(dash: Dashboard) -> None:
    r = dash.request("GET", "/api/v1/wallets", headers={"X-Correlation-ID": "trace-abc-123"})
    assert r.headers["x-correlation-id"] == "trace-abc-123"
    bad = dash.request("GET", "/api/v1/wallets", headers={"X-Correlation-ID": "<script>"})
    assert bad.headers["x-correlation-id"] != "<script>"


def test_health_ready_metrics(client: TestClient, dash: Dashboard) -> None:
    dash.wallet("A", fund=5)
    assert client.get("/healthz").json() == {"status": "ok"}
    ready = client.get("/readyz")
    assert ready.status_code == 200 and ready.json()["schema_version"] == "0001"
    metrics = client.get("/metrics").text
    assert 'waltrix_financial_operations_total{operation="wallet.credit",outcome="succeeded"}' in metrics
    assert "waltrix_financial_operation_duration_seconds_bucket" in metrics


def test_security_headers(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"


def test_openapi_documents_idempotency(client: TestClient) -> None:
    spec = client.get("/api/v1/openapi.json").json()
    params = spec["paths"]["/api/v1/transfers"]["post"]["parameters"]
    assert any(p["name"] == "Idempotency-Key" and p["required"] for p in params)
