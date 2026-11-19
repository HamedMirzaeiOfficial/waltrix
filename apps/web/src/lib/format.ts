import { currencyExponent, formatMoney as sdkFormatMoney, parseMoney } from "@waltrix/sdk";

import { intlLocale, isRtl, msg, t, toAsciiDigits } from "./i18n";

/**
 * Amounts read left to right in both languages ("-$12.50", never "$12.50-"). In Persian the string is
 * wrapped in Unicode isolates (LRI ... PDI) so it stays one LTR unit inside right-to-left text.
 */
function ltr(text: string): string {
  return isRtl() ? `\u2066${text}\u2069` : text;
}

/** Display only. Persian digits in Persian; the amount itself is always integer minor units. */
export function formatMoney(amount: number, currency: string): string {
  return ltr(sdkFormatMoney(amount, currency, intlLocale()));
}

export function money(amount: number | null | undefined, currency: string): string {
  if (amount === null || amount === undefined) return "-";
  return formatMoney(amount, currency);
}

/** Parse what the user typed (Persian or Latin digits) into minor units; null when invalid. */
export function parseAmount(input: string, currency: string): number | null {
  return parseMoney(toAsciiDigits(input), currency);
}

/** Compact for chart axes: $12.4K. Display only. */
export function compactMoney(amount: number, currency: string): string {
  const major = amount / 10 ** currencyExponent(currency);
  return ltr(
    new Intl.NumberFormat(intlLocale(), {
      style: "currency",
      currency,
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(major),
  );
}

// Formatters are created per call: the language can change at runtime and Intl objects are cheap.
// In Persian, fa-IR gives Persian digits and the Solar Hijri calendar.
export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  return new Intl.DateTimeFormat(intlLocale(), { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
}

export function shortDate(iso: string): string {
  return new Intl.DateTimeFormat(intlLocale(), { month: "short", day: "numeric" }).format(new Date(iso));
}

export function relative(iso: string | null | undefined): string {
  if (!iso) return "-";
  const rtf = new Intl.RelativeTimeFormat(intlLocale(), { numeric: "auto" });
  const diff = (new Date(iso).getTime() - Date.now()) / 1000;
  const abs = Math.abs(diff);
  if (abs < 60) return rtf.format(Math.round(diff), "second");
  if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
  return rtf.format(Math.round(diff / 86400), "day");
}

/** "finance_operator" -> "Finance operator", then translated. Labels for API enum values. */
export function humanize(code: string | null | undefined): string {
  if (!code) return "";
  return t(code.replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase()));
}

/*
 * Enum values reach humanize() at runtime, so the i18n check cannot see them as t() literals.
 * Listing them here keeps their Persian entries checked and marked as used.
 */
export const ENUM_LABELS = [
  // transaction status and type, hold and wallet status
  msg("Created"),
  msg("Pending"),
  msg("Posted"),
  msg("Failed"),
  msg("Reversed"),
  msg("Transfer"),
  msg("Deposit"),
  msg("Withdrawal"),
  msg("Hold"),
  msg("Reversal"),
  msg("Active"),
  msg("Captured"),
  msg("Released"),
  msg("Expired"),
  msg("Suspended"),
  msg("Closed"),
  msg("Revoked"),
  msg("Passed"),
  // journal entry kinds and phases
  msg("Capture"),
  msg("Manual"),
  // roles and actors
  msg("Owner"),
  msg("Admin"),
  msg("Finance operator"),
  msg("Auditor"),
  msg("Viewer"),
  msg("User"),
  msg("Api key"),
  msg("System"),
  // accounts
  msg("Asset"),
  msg("Liability"),
  msg("Equity"),
  msg("Revenue"),
  msg("Expense"),
  msg("Debit"),
  msg("Credit"),
  // wallet status actions
  msg("Suspend"),
  msg("Activate"),
  msg("Close"),
  // failure codes shown as titles
  msg("Insufficient funds"),
  msg("Wallet not active"),
  msg("Account not active"),
  msg("Currency mismatch"),
  msg("Same wallet"),
  msg("Hold not active"),
  msg("Hold expired"),
  msg("Hold released"),
  msg("Capture exceeds hold"),
  msg("Not reversible"),
  msg("Reversal exceeds remaining"),
  msg("Invalid state transition"),
  msg("Ledger invariant violation"),
  msg("Operation failed"),
  // reconciliation severities
  msg("Error"),
  msg("Warning"),
];
