"""Request and response schemas (the public API contract).

Money is always ``{amount: int (minor units), currency: "USD"}``. Amounts are
JSON integers capped at 2^53-1 so JavaScript clients never lose precision.
Strict ``StrictInt`` rejects ``10.5``, ``"10"`` and ``true``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints

from waltrix_core.enums import AccountType, Direction, NormalBalance, Role
from waltrix_core.money import MAX_AMOUNT

Amount = Annotated[StrictInt, Field(gt=0, le=MAX_AMOUNT, description="Positive integer in minor units")]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{3}$")]
ShortText = Annotated[str, StringConstraints(max_length=500)]
Metadata = Annotated[dict[str, str | int | bool | None], Field(max_length=20)]


class Model(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- generic -------------------------------------------------------------------


T = TypeVar("T")


class PageOut(BaseModel, Generic[T]):  # noqa: UP046 - explicit TypeVar keeps OpenAPI names stable
    data: list[T]
    next_cursor: str | None
    has_more: bool


# --- auth / orgs -------------------------------------------------------------


class RegisterIn(StrictModel):
    email: Annotated[str, StringConstraints(max_length=254)]
    password: Annotated[str, StringConstraints(min_length=10, max_length=256)]
    display_name: Annotated[str, StringConstraints(max_length=120)] = ""


class LoginIn(StrictModel):
    email: Annotated[str, StringConstraints(max_length=254)]
    password: Annotated[str, StringConstraints(max_length=256)]


class UserOut(Model):
    id: UUID
    email: str
    display_name: str
    created_at: datetime


class OrganizationOut(Model):
    id: UUID
    name: str
    slug: str
    created_at: datetime


class MembershipOut(BaseModel):
    organization: OrganizationOut
    role: Role
    permissions: list[str]


class MeOut(BaseModel):
    user: UserOut
    memberships: list[MembershipOut]


class OrganizationIn(StrictModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=120)]


class CurrentOrganizationOut(BaseModel):
    organization: OrganizationOut
    role: Role
    permissions: list[str]
    actor_type: str


class MemberOut(BaseModel):
    id: UUID
    user: UserOut
    role: Role
    created_at: datetime


class MemberIn(StrictModel):
    email: Annotated[str, StringConstraints(max_length=254)]
    role: Role


class MemberRoleIn(StrictModel):
    role: Role


class ApiKeyOut(Model):
    id: UUID
    name: str
    prefix: str
    role: Role
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreatedOut(ApiKeyOut):
    secret: str = Field(description="Shown exactly once. Store it in a secret manager.")


class ApiKeyIn(StrictModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    role: Literal[Role.FINANCE_OPERATOR, Role.AUDITOR, Role.VIEWER]
    expires_in_days: Annotated[int, Field(ge=1, le=730)] | None = None


class ApiKeyRotateIn(StrictModel):
    grace_hours: Annotated[int, Field(ge=0, le=168)] = 0


# --- accounts & wallets -----------------------------------------------------------


class BalanceOut(BaseModel):
    currency: str
    posted: int
    pending_outgoing: int
    pending_incoming: int
    available: int


class AccountOut(Model):
    id: UUID
    code: str
    name: str
    type: AccountType
    normal_balance: NormalBalance
    currency: str
    status: str
    is_system: bool
    allow_negative: bool
    balance: BalanceOut
    created_at: datetime


class AccountIn(StrictModel):
    code: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    type: AccountType
    currency: Currency


class WalletOut(BaseModel):
    id: UUID
    name: str
    owner_reference: str
    currency: str
    status: str
    account_id: UUID
    balance: BalanceOut
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class WalletIn(StrictModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    owner_reference: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    currency: Currency
    metadata: Metadata = Field(default_factory=dict)


class WalletStatusIn(StrictModel):
    reason: ShortText | None = None


class FundingIn(StrictModel):
    amount: Amount
    currency: Currency
    description: ShortText | None = None
    reference: Annotated[str, StringConstraints(max_length=120)] | None = None
    metadata: Metadata = Field(default_factory=dict)


# --- transactions --------------------------------------------------------------


class TransferIn(StrictModel):
    source_wallet_id: UUID
    destination_wallet_id: UUID
    amount: Amount
    currency: Currency
    description: ShortText | None = None
    reference: Annotated[str, StringConstraints(max_length=120)] | None = None
    metadata: Metadata = Field(default_factory=dict)


class TransactionOut(BaseModel):
    id: UUID
    type: str
    status: str
    amount: int
    posted_amount: int | None
    reversed_amount: int
    currency: str
    source_wallet_id: UUID | None
    destination_wallet_id: UUID | None
    original_transaction_id: UUID | None
    description: str | None
    reference: str | None
    failure_code: str | None
    failure_message: str | None
    actor_type: str
    actor_id: str | None
    correlation_id: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    posted_at: datetime | None


class PostingOut(BaseModel):
    line_no: int
    account_id: UUID
    account_code: str | None
    account_name: str | None
    wallet_id: UUID | None
    direction: Direction
    amount: int
    currency: str


class JournalEntryOut(BaseModel):
    id: UUID
    entry_number: int
    phase: str
    kind: str
    description: str
    transaction_id: UUID | None
    reverses_entry_id: UUID | None
    actor_type: str
    actor_id: str | None
    correlation_id: str | None
    effective_at: datetime
    created_at: datetime
    postings: list[PostingOut]


class TransactionDetailOut(TransactionOut):
    journal_entries: list[JournalEntryOut]
    reversals: list[TransactionOut]
    hold_id: UUID | None = None


class ManualLineIn(StrictModel):
    account_id: UUID
    direction: Direction
    amount: Amount
    currency: Currency


class ManualEntryIn(StrictModel):
    description: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    lines: Annotated[list[ManualLineIn], Field(min_length=2, max_length=20)]


class ReversalIn(StrictModel):
    transaction_id: UUID
    amount: Amount | None = Field(default=None, description="Omit for a full reversal")
    reason: ShortText | None = None


# --- holds -----------------------------------------------------------------------


class HoldIn(StrictModel):
    wallet_id: UUID
    destination_wallet_id: UUID
    amount: Amount
    currency: Currency
    expires_in_seconds: Annotated[int, Field(ge=1, le=30 * 86400)] | None = None
    description: ShortText | None = None


class HoldCaptureIn(StrictModel):
    amount: Amount | None = Field(default=None, description="Omit to capture the full hold")


class HoldOut(Model):
    id: UUID
    wallet_id: UUID
    destination_wallet_id: UUID
    amount: int
    captured_amount: int | None
    currency: str
    status: str
    transaction_id: UUID
    pending_entry_id: UUID
    capture_entry_id: UUID | None
    description: str | None
    expires_at: datetime
    created_at: datetime
    resolved_at: datetime | None


# --- statements, audit, reconciliation, overview -------------------------------------


class StatementLineOut(BaseModel):
    posting_id: int
    entry_id: UUID
    entry_number: int
    kind: str
    description: str
    transaction_id: UUID | None
    direction: str
    amount: int
    balance_after: int
    created_at: datetime


class StatementOut(BaseModel):
    account_id: UUID
    currency: str
    start: datetime | None
    end: datetime | None
    opening_balance: int
    closing_balance: int
    total_debits: int
    total_credits: int
    lines: list[StatementLineOut]


class AuditEventOut(BaseModel):
    id: UUID
    actor_type: str
    actor_id: str | None
    actor_label: str | None
    action: str
    target_type: str | None
    target_id: str | None
    correlation_id: str | None
    metadata: dict[str, Any]
    created_at: datetime


class ReconciliationRunOut(Model):
    id: UUID
    status: str
    summary: dict[str, Any]
    findings: list[dict[str, Any]]
    actor_type: str
    actor_id: str | None
    started_at: datetime
    created_at: datetime
    duration_ms: int


class OverviewOut(BaseModel):
    balances: list[dict[str, Any]]
    transaction_counts: dict[str, int]
    volume: list[dict[str, Any]]
    failed_last_24h: int
    active_holds: list[dict[str, Any]]
    last_reconciliation: ReconciliationRunOut | None
    window_days: int


class CurrencyOut(BaseModel):
    code: str
    exponent: int
