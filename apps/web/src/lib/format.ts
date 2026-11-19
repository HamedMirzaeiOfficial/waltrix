import { currencyExponent, formatMoney } from "@waltrix/sdk";

export { formatMoney };

export function money(amount: number | null | undefined, currency: string): string {
  if (amount === null || amount === undefined) return "-";
  return formatMoney(amount, currency);
}

/** Compact for chart axes: $12.4K. Display only. */
export function compactMoney(amount: number, currency: string): string {
  const major = amount / 10 ** currencyExponent(currency);
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(major);
}

const dtf = new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" });
const df = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

export function dateTime(iso: string | null | undefined): string {
  return iso ? dtf.format(new Date(iso)) : "-";
}

export function shortDate(iso: string): string {
  return df.format(new Date(iso));
}

export function relative(iso: string | null | undefined): string {
  if (!iso) return "-";
  const diff = (new Date(iso).getTime() - Date.now()) / 1000;
  const abs = Math.abs(diff);
  if (abs < 60) return rtf.format(Math.round(diff), "second");
  if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
  return rtf.format(Math.round(diff / 86400), "day");
}

export function humanize(code: string | null | undefined): string {
  if (!code) return "";
  return code.replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase());
}
