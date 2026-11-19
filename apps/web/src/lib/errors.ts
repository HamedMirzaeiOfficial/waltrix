import { WaltrixApiError, WaltrixNetworkError, WaltrixUnknownOutcomeError } from "@waltrix/sdk";

import { msg, t } from "./i18n";

// Keyed by the API's stable error code, so the message is translated here and not on the server.
const MESSAGES: Record<string, string> = {
  insufficient_funds: msg("The source wallet does not have enough available balance."),
  wallet_not_active: msg("One of the wallets is suspended or closed."),
  account_not_active: msg("One of the accounts is not active."),
  currency_mismatch: msg("Both wallets must use the same currency as the transfer."),
  same_wallet: msg("Source and destination must be different wallets."),
  hold_not_active: msg("This hold has already been captured, released or expired."),
  hold_expired: msg("This hold has expired."),
  hold_released: msg("This hold has already been released."),
  capture_exceeds_hold: msg("You cannot capture more than the held amount."),
  not_reversible: msg("This transaction cannot be reversed."),
  reversal_exceeds_remaining: msg("The amount exceeds what is left to reverse."),
  idempotency_key_reused: msg("This request conflicts with an earlier one. Start a new operation."),
  concurrent_request: msg("The wallet is busy with another operation. Try again in a moment."),
  permission_denied: msg("Your role does not allow this action."),
  not_found: msg("Not found, or you do not have access to it."),
  rate_limited: msg("Too many requests. Slow down and try again shortly."),
  authentication_failed: msg("Your session has expired. Please sign in again."),
  validation_failed: msg("Some fields are invalid."),
  csrf_failed: msg("Security check failed. Reload the page and try again."),
};

export function humanError(err: unknown): string {
  if (err instanceof WaltrixUnknownOutcomeError) {
    return t("We could not confirm the result. The operation may or may not have been applied.");
  }
  if (err instanceof WaltrixNetworkError) return t("Cannot reach the Waltrix API. Check your connection.");
  if (err instanceof WaltrixApiError) {
    if (err.code === "validation_failed") {
      // Field messages come from the API in English; the field name stays as the API spells it.
      const fields = (err.details["fields"] as { field: string; message: string }[] | undefined) ?? [];
      if (fields.length) return fields.map((f) => `${f.field || "request"}: ${f.message}`).join("; ");
    }
    const known = MESSAGES[err.code];
    return known ? t(known) : err.message;
  }
  return err instanceof Error ? err.message : t("Something went wrong.");
}

export function isAuthError(err: unknown): boolean {
  return err instanceof WaltrixApiError && err.status === 401;
}
