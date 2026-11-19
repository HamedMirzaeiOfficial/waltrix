# ADR 0001: One framework-independent ledger core

**English** · [فارسی](../../fa/architecture/decisions/0001-single-ledger-core.md)

**Status:** accepted

**Context.** The product must work as a dashboard *and* as an engine other applications embed. Duplicated
financial logic (one copy in the UI, one in the API, one in a worker) is the classic source of ledgers that
disagree with themselves.

**Decision.** All money rules live in `packages/ledger-core` (`waltrix_core`). It depends on SQLAlchemy
and PostgreSQL, not on FastAPI. Every mutating use case owns its database transaction. The API is a thin
adapter; the dashboard uses only the public REST API through the TypeScript SDK.

**Consequences.** A host Python application can call `waltrix_core.services.operations.transfer` directly
and get identical guarantees. The API layer stays small and boring. The core cannot use request-scoped
helpers from a web framework, so the acting identity is passed explicitly as an `Actor`.
