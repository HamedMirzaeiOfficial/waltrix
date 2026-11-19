/**
 * Transfer UI state machine (pure; unit-tested).
 *
 *   edit ──REVIEW──► review ──SUBMIT──► submitting ──► success     (server confirmed: posted)
 *     ▲                │                    │      ├──► failed      (server confirmed: business rule)
 *     └─────EDIT───────┘                    │      ├──► rejected    (request refused, nothing happened)
 *                                           │      └──► unknown     (no definitive answer)
 *                                           │                │
 *                                           └◄───VERIFY──────┘      (same idempotency key: safe replay)
 *
 * Invariants:
 *  - The idempotency key is created when entering review and is kept for every
 *    submit/verify of that draft. Editing the draft discards it (new parameters
 *    need a new key, otherwise the server answers 409).
 *  - `success` is reachable only from a server response, never optimistically.
 *  - While `submitting`, SUBMIT is ignored (no double submission).
 */

export interface TransferDraft {
  sourceWalletId: string;
  destinationWalletId: string;
  amount: number; // minor units
  currency: string;
  description?: string;
}

export interface ConfirmedTransaction {
  id: string;
  status: string;
}

export type TransferState =
  | { kind: "edit"; draft?: TransferDraft }
  | { kind: "review"; draft: TransferDraft; key: string }
  | { kind: "submitting"; draft: TransferDraft; key: string; attempt: number; verifying: boolean }
  | { kind: "success"; draft: TransferDraft; key: string; tx: ConfirmedTransaction }
  | { kind: "failed"; draft: TransferDraft; key: string; code: string; message: string; transactionId: string | null }
  | { kind: "rejected"; draft: TransferDraft; message: string }
  | { kind: "unknown"; draft: TransferDraft; key: string; attempt: number; message: string };

export type TransferEvent =
  | { type: "REVIEW"; draft: TransferDraft; key: string }
  | { type: "EDIT" }
  | { type: "SUBMIT" }
  | { type: "VERIFY" }
  | { type: "SUCCEEDED"; tx: ConfirmedTransaction }
  | { type: "FAILED"; code: string; message: string; transactionId: string | null }
  | { type: "REJECTED"; message: string }
  | { type: "UNKNOWN"; message: string }
  | { type: "RESET" };

export const initialTransferState: TransferState = { kind: "edit" };

export function transferReducer(state: TransferState, event: TransferEvent): TransferState {
  switch (event.type) {
    case "REVIEW":
      return state.kind === "edit" || state.kind === "rejected"
        ? { kind: "review", draft: event.draft, key: event.key }
        : state;
    case "EDIT":
      return state.kind === "review" || state.kind === "rejected" ? { kind: "edit", draft: state.draft } : state;
    case "SUBMIT":
      return state.kind === "review"
        ? { kind: "submitting", draft: state.draft, key: state.key, attempt: 1, verifying: false }
        : state;
    case "VERIFY":
      return state.kind === "unknown"
        ? { kind: "submitting", draft: state.draft, key: state.key, attempt: state.attempt + 1, verifying: true }
        : state;
    case "SUCCEEDED":
      return state.kind === "submitting"
        ? { kind: "success", draft: state.draft, key: state.key, tx: event.tx }
        : state;
    case "FAILED":
      return state.kind === "submitting"
        ? {
            kind: "failed",
            draft: state.draft,
            key: state.key,
            code: event.code,
            message: event.message,
            transactionId: event.transactionId,
          }
        : state;
    case "REJECTED":
      // A rejection during *verification* is not proof that nothing happened
      // only if it is a conflict; the caller maps that case to UNKNOWN.
      return state.kind === "submitting" ? { kind: "rejected", draft: state.draft, message: event.message } : state;
    case "UNKNOWN":
      return state.kind === "submitting"
        ? { kind: "unknown", draft: state.draft, key: state.key, attempt: state.attempt, message: event.message }
        : state;
    case "RESET":
      return state.kind === "submitting" ? state : initialTransferState;
  }
}

/** True while leaving the page could hide an in-flight or unresolved operation. */
export function isUnresolved(state: TransferState): boolean {
  return state.kind === "submitting" || state.kind === "unknown";
}

/** Delay before automatic verification attempt `n` (1-based). Capped exponential backoff. */
export function verifyDelayMs(attempt: number): number {
  return Math.min(8000, 1000 * 2 ** Math.max(0, attempt - 1));
}

export const AUTO_VERIFY_ATTEMPTS = 3;
