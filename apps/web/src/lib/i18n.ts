import FA from "@/locales/fa.json";

/*
 * Tiny i18n layer. The English source text is the key: t(english) returns the Persian entry from
 * src/locales/fa.json when the dashboard is in Persian and the English text otherwise, so a missing
 * translation degrades to readable English instead of a raw key. `npm run i18n:check` fails CI when a
 * t()/msg() string has no Persian entry.
 *
 * The current language is module state. index.html sets <html lang dir> before React loads (no flash
 * of the wrong direction); <LangProvider> in App.tsx remounts the UI below the query cache when the
 * user switches, so plain helpers such as dateTime() and humanError() translate without a hook.
 */

export type Lang = "en" | "fa";

export const LANG_STORAGE_KEY = "waltrix-lang";
const DICT: Record<string, string> = FA;

function initialLang(): Lang {
  if (typeof document !== "undefined" && document.documentElement.lang === "fa") return "fa";
  return "en";
}

let current: Lang = initialLang();

export function getLang(): Lang {
  return current;
}

/** Switch language: updates module state, <html lang dir> and the saved preference. */
export function setLang(lang: Lang): void {
  current = lang;
  if (typeof document !== "undefined") {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "fa" ? "rtl" : "ltr";
  }
  try {
    localStorage.setItem(LANG_STORAGE_KEY, lang);
  } catch {
    /* storage can be blocked; the choice then lasts for this page only */
  }
}

/** Translate `text`, replacing `{name}` placeholders with `vars.name`. */
export function t(text: string, vars?: Record<string, string | number>): string {
  const out = current === "fa" ? (DICT[text] ?? text) : text;
  if (!vars) return out;
  return out.replace(/\{(\w+)\}/g, (whole, key: string) => {
    if (!(key in vars)) return whole;
    const value = vars[key]!;
    return typeof value === "number" ? num(value) : value;
  });
}

/** Marks a string for translation without translating it yet (constant tables rendered later with t()). */
export function msg(text: string): string {
  return text;
}

/** BCP 47 locale for Intl: Persian digits and the Solar Hijri calendar in Persian. */
export function intlLocale(): string {
  return current === "fa" ? "fa-IR" : "en-US";
}

export function isRtl(): boolean {
  return current === "fa";
}

/** Plain integer/count formatting in the current language (Persian digits in fa). */
export function num(value: number): string {
  return new Intl.NumberFormat(intlLocale()).format(value);
}

/**
 * Persian and Arabic-Indic digits and separators typed into a money field, converted to ASCII so the
 * SDK's string-based parser sees "1234.5". Display formatting is separate (see format.ts).
 */
export function toAsciiDigits(input: string): string {
  return input
    .replace(/[۰-۹]/g, (d) => String(d.charCodeAt(0) - 0x06f0))
    .replace(/[٠-٩]/g, (d) => String(d.charCodeAt(0) - 0x0660))
    .replace(/[٫]/g, ".")
    .replace(/[٬،]/g, ",");
}

/** t() for optional values such as form errors whose text was marked with msg(). */
export function tMaybe(text: string | undefined): string | undefined {
  return text ? t(text) : undefined;
}
