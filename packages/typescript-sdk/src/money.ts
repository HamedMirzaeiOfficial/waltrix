/**
 * Minor-unit helpers. Parsing works on the decimal *string* the user typed,
 * never on a float, so "0.1" + "0.2" style errors cannot happen.
 */

const EXPONENTS: Record<string, number> = {
  USD: 2, EUR: 2, GBP: 2, CHF: 2, CAD: 2, AUD: 2, AED: 2, IRR: 2, JPY: 0, KRW: 0,
};

export function currencyExponent(currency: string): number {
  const exp = EXPONENTS[currency.toUpperCase()];
  if (exp === undefined) throw new RangeError(`unsupported currency ${currency}`);
  return exp;
}

/** "12.5" USD -> 1250. Returns null for invalid input (too many decimals, signs, garbage). */
export function parseMoney(input: string, currency: string): number | null {
  const exp = currencyExponent(currency);
  const text = input.trim().replace(/[,\s_]/g, "");
  const re = exp === 0 ? /^\d+$/ : new RegExp(`^(\\d+)(?:\\.(\\d{1,${exp}}))?$`);
  const m = re.exec(text);
  if (!m) return null;
  const whole = exp === 0 ? text : (m[1] ?? "0");
  const frac = exp === 0 ? "" : (m[2] ?? "").padEnd(exp, "0");
  const digits = (whole + frac).replace(/^0+(?=\d)/, "");
  const value = Number(digits);
  if (!Number.isSafeInteger(value)) return null;
  return value;
}

/** 1250, "USD" -> "$12.50" (display only). */
export function formatMoney(amount: number, currency: string, locale = "en-US", opts: Intl.NumberFormatOptions = {}): string {
  const exp = currencyExponent(currency);
  const negative = amount < 0;
  const abs = Math.abs(amount);
  const units = Math.floor(abs / 10 ** exp);
  const frac = abs % 10 ** exp;
  // Build the decimal string from integers, then let Intl add grouping and the symbol.
  const decimal = exp === 0 ? `${units}` : `${units}.${String(frac).padStart(exp, "0")}`;
  const formatter = new Intl.NumberFormat(locale, {
    style: "currency", currency, minimumFractionDigits: exp, maximumFractionDigits: exp, ...opts,
  });
  const formatted = formatter.format(decimal as unknown as number);
  return negative ? `-${formatted}` : formatted;
}
