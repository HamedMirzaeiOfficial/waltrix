"""Structured logging, correlation IDs, metrics and the HTTP middleware that ties them together."""

from __future__ import annotations

import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from waltrix_core.services import runner

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_CID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

REGISTRY = CollectorRegistry()
HTTP_REQUESTS = Counter(
    "waltrix_http_requests_total", "HTTP requests", ["method", "route", "status"], registry=REGISTRY
)
HTTP_LATENCY = Histogram(
    "waltrix_http_request_duration_seconds", "HTTP request latency", ["method", "route"], registry=REGISTRY
)
OPERATIONS = Counter(
    "waltrix_financial_operations_total",
    "Financial operations by outcome (succeeded, failed, replayed, error)",
    ["operation", "outcome"],
    registry=REGISTRY,
)
OPERATION_LATENCY = Histogram(
    "waltrix_financial_operation_duration_seconds",
    "Time spent inside the financial transaction boundary",
    ["operation"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
    registry=REGISTRY,
)
OPERATION_FAILURES = Counter(
    "waltrix_financial_operation_failures_total",
    "Financial operations that failed (business rule) or errored",
    ["operation", "kind"],
    registry=REGISTRY,
)
RECONCILIATION_FINDINGS = Gauge(
    "waltrix_reconciliation_last_errors",
    "Error findings in the most recent reconciliation run",
    registry=REGISTRY,
)


def _observe_operation(operation: str, outcome: str, seconds: float) -> None:
    OPERATIONS.labels(operation, outcome).inc()
    OPERATION_LATENCY.labels(operation).observe(seconds)
    if outcome in {"failed", "error"}:
        OPERATION_FAILURES.labels(operation, outcome).inc()


if _observe_operation not in runner.OBSERVERS:
    runner.OBSERVERS.append(_observe_operation)


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Never logs request bodies or headers."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "correlation_id": correlation_id_var.get(),
        }
        for key in ("method", "path", "status", "duration_ms", "actor", "org"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter() if json_logs else logging.Formatter("%(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = True  # replaced by our access log


access_log = logging.getLogger("waltrix.access")


class RequestContextMiddleware:
    """Pure ASGI middleware: correlation ID, security headers, access log and HTTP metrics."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-correlation-id", b"").decode("latin-1")
        cid = incoming if _CID_RE.match(incoming) else uuid.uuid4().hex
        token = correlation_id_var.set(cid)
        scope.setdefault("state", {})["correlation_id"] = cid
        started = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                extra = [
                    (b"x-correlation-id", cid.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"),
                    (b"cache-control", b"no-store"),
                ]
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + extra
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - started
            route = scope.get("route")
            route_path = getattr(route, "path", "unmatched")
            HTTP_REQUESTS.labels(scope["method"], route_path, str(status_holder["status"])).inc()
            HTTP_LATENCY.labels(scope["method"], route_path).observe(elapsed)
            if route_path not in {"/healthz", "/metrics"}:
                access_log.info(
                    "request",
                    extra={
                        "method": scope["method"],
                        "path": route_path,
                        "status": status_holder["status"],
                        "duration_ms": round(elapsed * 1000, 2),
                    },
                )
            correlation_id_var.reset(token)
