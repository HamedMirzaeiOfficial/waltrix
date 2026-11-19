# ADR 0005: Holds are immutable PENDING journal entries

**English** · [فارسی](../../fa/architecture/decisions/0005-holds-as-pending-entries.md)

**Status:** accepted

**Context.** A hold (an authorization) reserves funds now and moves some or all of them later, or never.
The reserved amount must reduce the available balance immediately, survive concurrent transfers, and
leave a full history, while the journal stays append-only.

**Decision.** A hold writes a balanced journal entry with phase `pending`; it moves the accounts' pending
columns, not posted balances. Capture writes a new `posted` entry (any amount up to the hold) and releases
the pending amount; release/expiry only releases it. The pending entry itself is never updated: whether it
still counts is derived from the hold's status, which reconciliation verifies.

**Why.** The journal stays append-only, available balance is `posted - outgoing pending`, and the full
history of an authorization (requested, captured partially, rest released) remains visible.

**Rejected.** A `reserved` column on the wallet with no journal entry: simpler, but the reservation would
have no audit trail and reconciliation could not re-derive it. Updating the pending entry on capture:
breaks immutability and loses the original amount.

**Consequences.** Every account needs `pending_debits` and `pending_credits` columns, and reconciliation
needs a dedicated check (`pending_balance_mismatch`) that sums the pending entries of ACTIVE holds. Only a
single capture per hold is supported; several partial captures would need a capture table.
