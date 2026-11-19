# Chapter 1 — The architecture map

**English** · [فارسی](../01-architecture.md)

Files for this chapter: `packages/ledger-core/`, `apps/api/src/waltrix_api/main.py`, `apps/web/src/lib/api.ts`, [ADR 0001](../../architecture/decisions/0001-single-ledger-core.md)

## 1. The problem: the project has two faces

The brief says Waltrix must be both a **standalone dashboard** and a **financial engine** that other applications embed. The usual danger is that financial logic ends up in two or three copies: one in the UI ("is the balance enough?"), one in the API, one in a worker. One day those copies disagree, and your ledger contradicts itself.

**The rule in this project:** financial logic lives in exactly one place: `packages/ledger-core` (the Python package `waltrix_core`).

## 2. Layers and the direction of dependencies

```
apps/web  ─►  @waltrix/sdk  ─HTTP─►  apps/api  ─►  waltrix_core.services  ─►  PostgreSQL
                                        ▲                 ▲
                         waltrix CLI ───┘                 └── (a host Python application)
```

| Layer | Path | Knows about | Does not know about |
| --- | --- | --- | --- |
| Pure domain | `money.py`, `rules.py`, `state_machine.py`, `permissions.py` | integers, enums | SQL, HTTP |
| Persistence | `db/models.py`, `migrations/` | SQLAlchemy, PostgreSQL | HTTP |
| Use cases | `services/*.py` | sessions, transactions, locks | status codes, cookies |
| Transport | `apps/api` | FastAPI, headers, authentication | posting rules |
| Clients | the SDKs, `apps/web` | the public REST contract | the database |

Dependencies point **downwards** only. A simple test of the rule: you will not find `posted_debits +=` anywhere in `apps/api`. The API only translates domain errors into HTTP (`errors.py`).

**Lesson:** a "layer" means a direction of dependency, not a folder. If the core did `import fastapi`, you could no longer use it in a worker or a CLI without a web server.

## 3. The dashboard has no private endpoints

`apps/web/src/lib/api.ts`:

```ts
export const api = new Waltrix({
  baseUrl: import.meta.env.BASE_URL.replace(/\/$/, ""),
  session: { organizationId: () => organizationId },
});
```

The dashboard uses the same TypeScript SDK an external customer uses, only in session (cookie) mode instead of with an API key. As a result:

- every capability of the dashboard also exists in the public API (dogfooding);
- any SDK bug shows up in the dashboard first;
- the Playwright tests are effectively tests of the public API contract too.

## 4. Why not microservices?

The strongest guarantees a ledger has (atomic multi-row writes, row locks, constraints) come from **one database transaction**. If "wallets" and "ledger" were two services with two databases, that guarantee would be gone and you would have to replace it with sagas and compensation: more complex, slower, with more intermediate states.

Waltrix is one API process plus idempotent maintenance commands (`waltrix expire-holds`, `reconcile`). There is deliberately no Redis and no Celery; nothing actually needs them. The brief also said "only when really needed".

**Lesson:** start an architecture from the guarantees you need, not from a list of technologies.

## 5. The standalone core in practice

A host Python application can write directly:

```python
from waltrix_core.migrate import upgrade
from waltrix_core.services import operations

upgrade(DATABASE_URL)  # migrations ship inside the package
result = operations.transfer(session, actor, source_wallet_id=a, destination_wallet_id=b,
                             amount=1250, currency="USD", idempotency_key="order-81")
```

and it gets the same guarantees as the API, because the same function runs. The `Actor` (in `services/context.py`) is passed explicitly: the core has no access to a web framework's "current request", so identity has to be an explicit object.

## 6. Repository layout

```
apps/api                  FastAPI + CLI + HTTP tests
apps/web                  React dashboard + Vitest + Playwright
packages/ledger-core      domain + services + migrations
packages/python-sdk       Python client (sync and async)
packages/typescript-sdk   TypeScript client
examples/                 two runnable integrations
tests/                    unit, property, integration and concurrency tests (real PostgreSQL)
```

## Exercises

1. Search `apps/api` for any balance calculation (`grep -rn "balance" apps/api/src`). What do you find, and why is none of it a financial calculation?
2. Write a small Python script that creates and funds a wallet with `waltrix_core`, without the API. What do you have to build yourself (session, `Actor`)?
3. Suppose you want to add a "transfer fee". List which files in which layer must change. Does the UI need to know how the fee is calculated?
