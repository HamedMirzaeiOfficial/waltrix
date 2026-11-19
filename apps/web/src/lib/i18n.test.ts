import { WaltrixApiError } from "@waltrix/sdk";
import { afterEach, describe, expect, it } from "vitest";

import { humanError } from "./errors";
import { dateTime, formatMoney, humanize, parseAmount } from "./format";
import { getLang, num, setLang, t, toAsciiDigits } from "./i18n";

afterEach(() => setLang("en"));

describe("i18n", () => {
  it("returns English source text in English and the Persian entry in Persian", () => {
    expect(t("Overview")).toBe("Overview");
    setLang("fa");
    expect(t("Overview")).toBe("نمای کلی");
  });

  it("falls back to readable English when a key has no translation", () => {
    setLang("fa");
    expect(t("A sentence nobody translated")).toBe("A sentence nobody translated");
  });

  it("fills placeholders and formats numbers in the current language", () => {
    expect(t("Page {page}", { page: 12 })).toBe("Page 12");
    setLang("fa");
    expect(t("Page {page}", { page: 12 })).toBe("صفحهٔ ۱۲");
    expect(num(1234)).toBe("۱٬۲۳۴");
  });

  it("sets lang and dir on <html> and remembers the choice", () => {
    setLang("fa");
    expect(getLang()).toBe("fa");
    expect(document.documentElement.dir).toBe("rtl");
    expect(document.documentElement.lang).toBe("fa");
    expect(localStorage.getItem("waltrix-lang")).toBe("fa");
    setLang("en");
    expect(document.documentElement.dir).toBe("ltr");
  });

  it("translates API enum values through humanize()", () => {
    setLang("fa");
    expect(humanize("finance_operator")).toBe("اپراتور مالی");
    expect(humanize("posted")).toBe("ثبت‌شده");
  });

  it("translates error messages by stable code, not by server text", () => {
    const err = new WaltrixApiError(422, "insufficient_funds", "insufficient funds in wallet");
    expect(humanError(err)).toBe("The source wallet does not have enough available balance.");
    setLang("fa");
    expect(humanError(err)).toBe("کیف پول مبدأ موجودی قابل استفادهٔ کافی ندارد.");
  });
});

describe("money and dates in Persian", () => {
  it("formats money with Persian digits without changing the amount", () => {
    const en = formatMoney(123456, "USD");
    setLang("fa");
    const fa = formatMoney(123456, "USD");
    expect(en).toBe("$1,234.56");
    expect(toAsciiDigits(fa).replace(/[^\d.]/g, "")).toBe("1234.56");
    expect(fa).toMatch(/[۰-۹]/);
  });

  it("parses amounts typed with Persian or Arabic-Indic digits", () => {
    expect(parseAmount("۱۲٫۵", "USD")).toBe(1250);
    expect(parseAmount("١٢٣", "USD")).toBe(12300);
    expect(parseAmount("۱٬۰۰۰", "USD")).toBe(100000);
    expect(parseAmount("12.345", "USD")).toBeNull();
  });

  it("shows dates in the Solar Hijri calendar in Persian", () => {
    setLang("fa");
    // 2026-03-21 is 1 Farvardin 1405, the Persian new year.
    expect(dateTime("2026-03-21T12:00:00Z")).toContain("۱۴۰۵");
  });
});
