/**
 * Public API shapes. Amounts are integers in minor units (e.g. cents) and are
 * always <= Number.MAX_SAFE_INTEGER, so plain `number` is exact.
 */

export type Currency = string;
export type TransactionStatus = "created" | "pending" | "posted" | "failed" | "reversed";
export type TransactionType = "transfer" | "deposit" | "withdrawal" | "hold" | "reversal";
export type HoldStatus = "active" | "captured" | "released" | "expired";
export type WalletStatus = "active" | "suspended" | "closed";
export type Role = "owner" | "admin" | "finance_operator" | "auditor" | "viewer";
export type AccountType = "asset" | "liability" | "equity" | "revenue" | "expense";
export type Direction = "debit" | "credit";

export interface Page<T> {
  data: T[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface Balance {
  currency: Currency;
  posted: number;
  pending_outgoing: number;
  pending_incoming: number;
  available: number;
}

export interface Wallet {
  id: string;
  name: string;
  owner_reference: string;
  currency: Currency;
  status: WalletStatus;
  account_id: string;
  balance: Balance;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Account {
  id: string;
  code: string;
  name: string;
  type: AccountType;
  normal_balance: Direction;
  currency: Currency;
  status: string;
  is_system: boolean;
  allow_negative: boolean;
  balance: Balance;
  created_at: string;
}

export interface Transaction {
  id: string;
  type: TransactionType;
  status: TransactionStatus;
  amount: number;
  posted_amount: number | null;
  reversed_amount: number;
  currency: Currency;
  source_wallet_id: string | null;
  destination_wallet_id: string | null;
  original_transaction_id: string | null;
  description: string | null;
  reference: string | null;
  failure_code: string | null;
  failure_message: string | null;
  actor_type: string;
  actor_id: string | null;
  correlation_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  posted_at: string | null;
}

export interface Posting {
  line_no: number;
  account_id: string;
  account_code: string | null;
  account_name: string | null;
  wallet_id: string | null;
  direction: Direction;
  amount: number;
  currency: Currency;
}

export interface JournalEntry {
  id: string;
  entry_number: number;
  phase: "pending" | "posted";
  kind: string;
  description: string;
  transaction_id: string | null;
  reverses_entry_id: string | null;
  actor_type: string;
  actor_id: string | null;
  correlation_id: string | null;
  effective_at: string;
  created_at: string;
  postings: Posting[];
}

export interface TransactionDetail extends Transaction {
  journal_entries: JournalEntry[];
  reversals: Transaction[];
  hold_id: string | null;
}

export interface Hold {
  id: string;
  wallet_id: string;
  destination_wallet_id: string;
  amount: number;
  captured_amount: number | null;
  currency: Currency;
  status: HoldStatus;
  transaction_id: string;
  pending_entry_id: string;
  capture_entry_id: string | null;
  description: string | null;
  expires_at: string;
  created_at: string;
  resolved_at: string | null;
}

export interface StatementLine {
  posting_id: number;
  entry_id: string;
  entry_number: number;
  kind: string;
  description: string;
  transaction_id: string | null;
  direction: Direction;
  amount: number;
  balance_after: number;
  created_at: string;
}

export interface Statement {
  account_id: string;
  currency: Currency;
  start: string | null;
  end: string | null;
  opening_balance: number;
  closing_balance: number;
  total_debits: number;
  total_credits: number;
  lines: StatementLine[];
}

export interface ReconciliationFinding {
  check: string;
  severity: "error" | "warning";
  details: Record<string, string | number | null>;
}

export interface ReconciliationRun {
  id: string;
  status: "passed" | "failed";
  summary: {
    checks: Record<string, number>;
    trial_balance: { currency: string; debits: number; credits: number; entries: number }[];
    counts: Record<string, number>;
    errors: number;
    warnings: number;
  };
  findings: ReconciliationFinding[];
  actor_type: string;
  actor_id: string | null;
  started_at: string;
  created_at: string;
  duration_ms: number;
}

export interface AuditEvent {
  id: string;
  actor_type: string;
  actor_id: string | null;
  actor_label: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  correlation_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface Overview {
  balances: { currency: Currency; wallet_count: number; total_posted: number; total_held: number }[];
  transaction_counts: Partial<Record<TransactionStatus, number>>;
  volume: { day: string; currency: Currency; count: number; amount: number }[];
  failed_last_24h: number;
  active_holds: { currency: Currency; count: number; amount: number }[];
  last_reconciliation: ReconciliationRun | null;
  window_days: number;
}

export interface User {
  id: string;
  email: string;
  display_name: string;
  created_at: string;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  created_at: string;
}

export interface Membership {
  organization: Organization;
  role: Role;
  permissions: string[];
}

export interface Me {
  user: User;
  memberships: Membership[];
}

export interface CurrentOrganization {
  organization: Organization;
  role: Role;
  permissions: string[];
  actor_type: string;
}

export interface Member {
  id: string;
  user: User;
  role: Role;
  created_at: string;
}

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  role: Role;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface ApiKeyCreated extends ApiKey {
  /** Shown exactly once. */
  secret: string;
}

export interface CurrencyInfo {
  code: Currency;
  exponent: number;
}

// --- inputs -------------------------------------------------------------------

export interface CreateWalletInput {
  name: string;
  owner_reference: string;
  currency: Currency;
  metadata?: Record<string, string | number | boolean | null>;
}

export interface FundingInput {
  amount: number;
  currency: Currency;
  description?: string;
  reference?: string;
}

export interface TransferInput {
  source_wallet_id: string;
  destination_wallet_id: string;
  amount: number;
  currency: Currency;
  description?: string;
  reference?: string;
  metadata?: Record<string, string | number | boolean | null>;
}

export interface HoldInput {
  wallet_id: string;
  destination_wallet_id: string;
  amount: number;
  currency: Currency;
  expires_in_seconds?: number;
  description?: string;
}

export interface ReversalInput {
  transaction_id: string;
  amount?: number;
  reason?: string;
}

export interface ManualEntryInput {
  description: string;
  lines: { account_id: string; direction: Direction; amount: number; currency: Currency }[];
}

export interface ListParams {
  limit?: number;
  cursor?: string;
}

export interface TransactionListParams extends ListParams {
  status?: TransactionStatus;
  type?: TransactionType;
  wallet_id?: string;
  currency?: Currency;
  created_after?: string;
  created_before?: string;
  search?: string;
  sort?: "created_at" | "-created_at";
}
