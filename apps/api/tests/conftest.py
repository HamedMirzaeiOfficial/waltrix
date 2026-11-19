"""API test fixtures: the real app against the real test database."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from waltrix_api.main import create_app
from waltrix_api.ratelimit import limiter
from waltrix_api.settings import Settings


@pytest.fixture
def app_settings(database_url: str) -> Settings:
    return Settings(environment="test", database_url=database_url, log_json=False, log_level="WARNING")


@pytest.fixture
def client(engine: Engine, app_settings: Settings) -> Iterator[TestClient]:
    limiter.reset()
    app = create_app(app_settings, engine=engine)
    with TestClient(app, base_url="http://testserver") as c:
        yield c


class Dashboard:
    """A logged-in dashboard user bound to one organization."""

    def __init__(self, client: TestClient, email: str, org_name: str | None = "Acme") -> None:
        self.client = client
        self.email = email
        r = client.post("/api/v1/auth/register", json={"email": email, "password": "correct-horse-battery"})
        assert r.status_code == 201, r.text
        r = client.post("/api/v1/auth/login", json={"email": email, "password": "correct-horse-battery"})
        assert r.status_code == 200, r.text
        self.cookie = r.cookies.get("waltrix_session")
        self.org_id: str | None = None
        if org_name:
            r = self.request("POST", "/api/v1/organizations", json={"name": org_name})
            assert r.status_code == 201, r.text
            self.org_id = r.json()["id"]

    def headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h = {"X-Requested-With": "waltrix-web"}
        if self.org_id:
            h["X-Waltrix-Organization"] = self.org_id
        return {**h, **(extra or {})}

    def request(self, method: str, url: str, **kw):  # type: ignore[no-untyped-def]
        headers = self.headers(kw.pop("headers", None))
        self.client.cookies.clear()
        self.client.cookies.set("waltrix_session", self.cookie)
        return self.client.request(method, url, headers=headers, **kw)

    def wallet(self, name: str = "Wallet", currency: str = "USD", fund: int = 0) -> str:
        r = self.request(
            "POST",
            "/api/v1/wallets",
            json={"name": name, "owner_reference": name.lower(), "currency": currency},
        )
        assert r.status_code == 201, r.text
        wid = r.json()["id"]
        if fund:
            r = self.request(
                "POST",
                f"/api/v1/wallets/{wid}/credit",
                json={"amount": fund, "currency": currency},
                headers={"Idempotency-Key": f"fund-{wid}"},
            )
            assert r.status_code == 201, r.text
        return wid


@pytest.fixture
def dash(client: TestClient) -> Dashboard:
    return Dashboard(client, "owner@acme.test")
