# ADR 0005: Holds are immutable PENDING journal entries

**Status:** accepted

**Decision.** A hold writes a balanced journal entry with phase `pending`; it moves the accounts' pending
columns, not posted balances. Capture writes a new `posted` entry (any amount up to the hold) and releases
the pending amount; release/expiry only releases it. The pending entry itself is never updated: whether it
still counts is derived from the hold's status, which reconciliation verifies.

**Why.** The journal stays append-only, available balance is `posted - outgoing pending`, and the full
history of an authorization (requested, captured partially, rest released) remains visible.
