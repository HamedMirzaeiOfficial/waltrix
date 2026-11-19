"""SQLAlchemy 2.x models.

Design notes (see docs/financial-model/invariants.md for the full list):

* Money columns are BIGINT minor units. No NUMERIC/FLOAT anywhere.
* ``journal_entries`` and ``postings`` are append-only: a trigger rejects
  UPDATE and DELETE (migration 0001). Corrections are reversing entries.
* A deferred constraint trigger re-checks at COMMIT that every entry balances
  per currency, so partial or unbalanced entries cannot be committed even by
  buggy code.
* Composite foreign keys tie a posting to an account of the *same
  organization and the same currency*: cross-tenant or cross-currency
  postings are impossible at the schema level.
* ``accounts`` carries materialized balances (posted/pending x debit/credit)
  that the engine updates in the same database transaction as the postings.
  Reconciliation re-derives them from the journal.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    MetaData,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ..enums import (
    AccountStatus,
    AccountType,
    ActorType,
    Direction,
    EntryKind,
    EntryPhase,
    HoldStatus,
    NormalBalance,
    ReconciliationStatus,
    Role,
    TransactionStatus,
    TransactionType,
    WalletStatus,
)

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def _enum(e: type, name: str) -> Enum:
    # Stored as VARCHAR + CHECK constraint (easier to evolve than native PG enums).
    return Enum(
        e,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda x: [m.value for m in x],
        validate_strings=True,
    )


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


CURRENCY_CHECK = "currency ~ '^[A-Z]{3}$'"


# ---------------------------------------------------------------------------
# Identity, tenancy and access
# ---------------------------------------------------------------------------


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = _created()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = _created()


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("org_id", "user_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[Role] = mapped_column(_enum(Role, "role"), nullable=False)
    created_at: Mapped[datetime] = _created()

    user: Mapped[User] = relationship(lazy="joined")
    organization: Mapped[Organization] = relationship(lazy="joined")


class UserSession(Base):
    """Dashboard login session. Only a SHA-256 hash of the token is stored."""

    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiKey(Base):
    """Server-to-server credential bound to exactly one organization.

    The secret is shown once at creation. We store its SHA-256 hash (the
    secret has 256 bits of entropy, so a slow KDF adds nothing) plus a short
    non-secret prefix for identification in the UI and logs.
    """

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    prefix: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    role: Mapped[Role] = mapped_column(_enum(Role, "role"), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


class Ledger(Base):
    __tablename__ = "ledgers"
    __table_args__ = (UniqueConstraint("org_id", "name"), UniqueConstraint("id", "org_id"))

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = _created()


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("ledger_id", "code", "currency"),
        # Targets for composite FKs from postings/wallets (tenant + currency safety).
        UniqueConstraint("id", "org_id", "currency"),
        UniqueConstraint("id", "org_id"),
        ForeignKeyConstraint(["ledger_id", "org_id"], ["ledgers.id", "ledgers.org_id"]),
        CheckConstraint(CURRENCY_CHECK, name="currency_format"),
        CheckConstraint(
            "posted_debits >= 0 AND posted_credits >= 0 AND pending_debits >= 0 AND pending_credits >= 0",
            name="non_negative_totals",
        ),
        # Last line of defense against overspending. The engine checks first
        # (under a row lock) to produce a friendly error; this catches bugs.
        CheckConstraint(
            "allow_negative "
            "OR (normal_balance = 'credit' AND posted_credits - posted_debits - pending_debits >= 0) "
            "OR (normal_balance = 'debit' AND posted_debits - posted_credits - pending_credits >= 0)",
            name="no_overdraft",
        ),
        CheckConstraint(
            "(type IN ('asset','expense') AND normal_balance = 'debit') "
            "OR (type IN ('liability','equity','revenue') AND normal_balance = 'credit')",
            name="normal_balance_matches_type",
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    ledger_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[AccountType] = mapped_column(_enum(AccountType, "account_type"), nullable=False)
    normal_balance: Mapped[NormalBalance] = mapped_column(
        _enum(NormalBalance, "normal_balance"), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    allow_negative: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    status: Mapped[AccountStatus] = mapped_column(
        _enum(AccountStatus, "account_status"),
        nullable=False,
        server_default=AccountStatus.ACTIVE.value,
    )
    posted_debits: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    posted_credits: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    pending_debits: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    pending_credits: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    # Incremented on every balance change; useful for optimistic readers and audits.
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class Wallet(Base):
    """User-facing abstraction over a single liability account.

    The wallet holds no money itself; its balance *is* the balance of
    ``account_id``, derived from the journal.
    """

    __tablename__ = "wallets"
    __table_args__ = (
        UniqueConstraint("id", "org_id"),
        ForeignKeyConstraint(
            ["account_id", "org_id", "currency"],
            ["accounts.id", "accounts.org_id", "accounts.currency"],
        ),
        CheckConstraint(CURRENCY_CHECK, name="currency_format"),
        Index("ix_wallets_org_created", "org_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_reference: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[WalletStatus] = mapped_column(
        _enum(WalletStatus, "wallet_status"),
        nullable=False,
        server_default=WalletStatus.ACTIVE.value,
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()

    account: Mapped[Account] = relationship(
        primaryjoin="Wallet.account_id == Account.id",
        foreign_keys="Wallet.account_id",
        lazy="joined",
        viewonly=True,
    )


class Transaction(Base):
    """Business-level operation record (what the user asked for).

    Mutable *status* only, governed by ``state_machine``. Money movement is
    recorded exclusively in journal entries linked via ``journal_entries.transaction_id``.
    """

    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("id", "org_id"),
        CheckConstraint(CURRENCY_CHECK, name="currency_format"),
        CheckConstraint("amount > 0", name="positive_amount"),
        CheckConstraint(
            "posted_amount IS NULL OR (posted_amount > 0 AND posted_amount <= amount)",
            name="posted_amount_range",
        ),
        CheckConstraint(
            "reversed_amount >= 0 AND reversed_amount <= COALESCE(posted_amount, 0)",
            name="reversed_amount_range",
        ),
        CheckConstraint(
            "(type = 'reversal') = (original_transaction_id IS NOT NULL)",
            name="reversal_has_original",
        ),
        ForeignKeyConstraint(
            ["original_transaction_id", "org_id"], ["transactions.id", "transactions.org_id"]
        ),
        ForeignKeyConstraint(["source_wallet_id", "org_id"], ["wallets.id", "wallets.org_id"]),
        ForeignKeyConstraint(["destination_wallet_id", "org_id"], ["wallets.id", "wallets.org_id"]),
        Index("ix_transactions_org_created", "org_id", "created_at", "id"),
        Index("ix_transactions_org_status", "org_id", "status"),
        Index("ix_transactions_source", "source_wallet_id", "created_at"),
        Index("ix_transactions_destination", "destination_wallet_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    type: Mapped[TransactionType] = mapped_column(_enum(TransactionType, "transaction_type"), nullable=False)
    status: Mapped[TransactionStatus] = mapped_column(
        _enum(TransactionStatus, "transaction_status"), nullable=False
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    posted_amount: Mapped[int | None] = mapped_column(BigInteger)
    reversed_amount: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    source_wallet_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    destination_wallet_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    original_transaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    description: Mapped[str | None] = mapped_column(String(500))
    reference: Mapped[str | None] = mapped_column(String(120))
    failure_code: Mapped[str | None] = mapped_column(String(64))
    failure_message: Mapped[str | None] = mapped_column(String(500))
    actor_type: Mapped[ActorType] = mapped_column(_enum(ActorType, "actor_type"), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JournalEntry(Base):
    """Authoritative financial record. Immutable once inserted."""

    __tablename__ = "journal_entries"
    __table_args__ = (
        UniqueConstraint("id", "org_id"),
        ForeignKeyConstraint(["ledger_id", "org_id"], ["ledgers.id", "ledgers.org_id"]),
        ForeignKeyConstraint(["transaction_id", "org_id"], ["transactions.id", "transactions.org_id"]),
        ForeignKeyConstraint(
            ["reverses_entry_id", "org_id"], ["journal_entries.id", "journal_entries.org_id"]
        ),
        Index("ix_journal_entries_org_created", "org_id", "created_at", "id"),
        Index("ix_journal_entries_transaction", "transaction_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    # Global, monotonically increasing, human-friendly number (gaps are possible
    # after rollbacks; the UUID is the identity, the number is for humans).
    entry_number: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False, unique=True)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    ledger_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    phase: Mapped[EntryPhase] = mapped_column(_enum(EntryPhase, "entry_phase"), nullable=False)
    kind: Mapped[EntryKind] = mapped_column(_enum(EntryKind, "entry_kind"), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reverses_entry_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_type: Mapped[ActorType] = mapped_column(_enum(ActorType, "actor_type"), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = _created()

    postings: Mapped[list[Posting]] = relationship(
        back_populates="entry", order_by="Posting.line_no", lazy="selectin"
    )


class Posting(Base):
    """One debit or credit line of a journal entry. Immutable."""

    __tablename__ = "postings"
    __table_args__ = (
        UniqueConstraint("entry_id", "line_no"),
        ForeignKeyConstraint(["entry_id", "org_id"], ["journal_entries.id", "journal_entries.org_id"]),
        ForeignKeyConstraint(
            ["account_id", "org_id", "currency"],
            ["accounts.id", "accounts.org_id", "accounts.currency"],
        ),
        CheckConstraint("amount > 0", name="positive_amount"),
        CheckConstraint(CURRENCY_CHECK, name="currency_format"),
        Index("ix_postings_account", "account_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    entry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    direction: Mapped[Direction] = mapped_column(_enum(Direction, "direction"), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    entry: Mapped[JournalEntry] = relationship(
        back_populates="postings",
        primaryjoin="Posting.entry_id == JournalEntry.id",
        foreign_keys="Posting.entry_id",
    )


class Hold(Base):
    """A reservation of funds. Backed by a PENDING journal entry."""

    __tablename__ = "holds"
    __table_args__ = (
        UniqueConstraint("id", "org_id"),
        ForeignKeyConstraint(["wallet_id", "org_id"], ["wallets.id", "wallets.org_id"]),
        ForeignKeyConstraint(["destination_wallet_id", "org_id"], ["wallets.id", "wallets.org_id"]),
        ForeignKeyConstraint(["transaction_id", "org_id"], ["transactions.id", "transactions.org_id"]),
        ForeignKeyConstraint(
            ["pending_entry_id", "org_id"], ["journal_entries.id", "journal_entries.org_id"]
        ),
        ForeignKeyConstraint(
            ["capture_entry_id", "org_id"], ["journal_entries.id", "journal_entries.org_id"]
        ),
        CheckConstraint("amount > 0", name="positive_amount"),
        CheckConstraint(
            "captured_amount IS NULL OR (captured_amount > 0 AND captured_amount <= amount)",
            name="captured_amount_range",
        ),
        CheckConstraint("(status = 'captured') = (capture_entry_id IS NOT NULL)", name="capture_has_entry"),
        CheckConstraint(CURRENCY_CHECK, name="currency_format"),
        Index("ix_holds_org_created", "org_id", "created_at", "id"),
        Index("ix_holds_active_expiry", "expires_at", postgresql_where=text("status = 'active'")),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    wallet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    destination_wallet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[HoldStatus] = mapped_column(_enum(HoldStatus, "hold_status"), nullable=False)
    captured_amount: Mapped[int | None] = mapped_column(BigInteger)
    transaction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    pending_entry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    capture_entry_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    description: Mapped[str | None] = mapped_column(String(500))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _created()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------------------
# Idempotency, audit, reconciliation
# ---------------------------------------------------------------------------


class IdempotencyRecord(Base):
    """Stores the outcome of a financial mutation under (org, operation, key).

    Inserted in the *same* database transaction as the financial writes, so a
    record exists if and only if the operation's result was committed.
    """

    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("org_id", "operation", "key"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)  # succeeded | failed
    resource_type: Mapped[str | None] = mapped_column(String(32))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class AuditEvent(Base):
    """Operational audit trail (who did what). Separate from financial postings. Append-only."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_org_created", "org_id", "created_at", "id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"))
    actor_type: Mapped[ActorType] = mapped_column(_enum(ActorType, "actor_type"), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64))
    actor_label: Mapped[str | None] = mapped_column(String(254))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = _created()


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_runs"
    __table_args__ = (Index("ix_reconciliation_runs_org_created", "org_id", "created_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    status: Mapped[ReconciliationStatus] = mapped_column(
        _enum(ReconciliationStatus, "reconciliation_status"), nullable=False
    )
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    actor_type: Mapped[ActorType] = mapped_column(_enum(ActorType, "actor_type"), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _created()
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)


__all__ = [
    "Account",
    "ApiKey",
    "AuditEvent",
    "Base",
    "Hold",
    "IdempotencyRecord",
    "JournalEntry",
    "Ledger",
    "Membership",
    "Organization",
    "Posting",
    "ReconciliationRun",
    "Transaction",
    "User",
    "UserSession",
    "Wallet",
]
