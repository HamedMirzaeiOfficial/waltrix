# waltrix-core

Framework-independent double-entry ledger and wallet engine used by the Waltrix API.

```python
from waltrix_core.db import make_engine, make_session_factory
from waltrix_core.migrate import upgrade
from waltrix_core.services import operations

upgrade(DATABASE_URL)                      # Alembic migrations ship with the package
Session = make_session_factory(make_engine(DATABASE_URL))
result = operations.transfer(Session(), actor, source_wallet_id=a, destination_wallet_id=b,
                             amount=1250, currency="USD", idempotency_key="order-81")
```

- `money`, `rules`, `state_machine`, `permissions`: pure domain logic (no I/O).
- `db.models`: SQLAlchemy 2 schema; `migrations/`: Alembic, including the immutability and balance triggers.
- `services`: transaction boundaries, posting engine, idempotency, holds, reversals, reconciliation, queries.

See the repository `docs/` for the financial model and concurrency design.
