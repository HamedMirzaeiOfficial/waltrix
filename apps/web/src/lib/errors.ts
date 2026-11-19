import { WaltrixApiError, WaltrixNetworkError, WaltrixUnknownOutcomeError } from "@waltrix/sdk";

const MESSAGES: Record<string, string> = {
  insufficient_funds: "The source wallet does not have enough available balance.",
  wallet_not_active: "One of the wallets is suspended or closed.",
  currency_mismatch: "Both wallets must use the same currency as the transfer.",
  same_wallet: "Source and destination must be different wallets.",
  hold_not_active: "This hold has already been captured, released or expired.",
  hold_expired: "This hold has expired.",
  capture_exceeds_hold: "You cannot capture more than the held amount.",
  not_reversible: "This transaction cannot be reversed.",
  reversal_exceeds_remaining: "The amount exceeds what is left to reverse.",
  idempotency_key_reused: "This request conflicts with an earlier one. Start a new operation.",
  concurrent_request: "The wallet is busy with another operation. Try again in a moment.",
  permission_denied: "Your role does not allow this action.",
  not_found: "Not found, or you do not have access to it.",
  rate_limited: "Too many requests. Slow down and try again shortly.",
  authentication_failed: "Your session has expired. Please sign in again.",
  validation_failed: "Some fields are invalid.",
  csrf_failed: "Security check failed. Reload the page and try again.",
};

export function humanError(err: unknown): string {
  if (err instanceof WaltrixUnknownOutcomeError) {
    return "We could not confirm the result. The operation may or may not have been applied.";
  }
  if (err instanceof WaltrixNetworkError) return "Cannot reach the Waltrix API. Check your connection.";
  if (err instanceof WaltrixApiError) {
    if (err.code === "validation_failed") {
      const fields = (err.details["fields"] as { field: string; message: string }[] | undefined) ?? [];
      if (fields.length) return fields.map((f) => `${f.field || "request"}: ${f.message}`).join("; ");
    }
    return MESSAGES[err.code] ?? err.message;
  }
  return err instanceof Error ? err.message : "Something went wrong.";
}

export function isAuthError(err: unknown): boolean {
  return err instanceof WaltrixApiError && err.status === 401;
}
