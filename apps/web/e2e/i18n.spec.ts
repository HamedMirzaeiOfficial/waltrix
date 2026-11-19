import { expect, test } from "@playwright/test";

import { createWallet, fund, signUp } from "./helpers";

test("Persian: right-to-left layout, Persian digits, and a transfer typed in Persian digits", async ({ page }) => {
  await signUp(page);
  const alice = await createWallet(page, "Alice Synthetic");
  await createWallet(page, "Bob Synthetic");
  await fund(page, alice, "100");

  // The switch shows the target language in that language.
  await page.goto("/");
  await page.getByRole("button", { name: "فارسی" }).first().click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.locator("html")).toHaveAttribute("lang", "fa");
  await expect(page.getByRole("heading", { name: "نمای کلی" })).toBeVisible();

  // The choice survives a reload (set before React renders, so no LTR flash).
  await page.reload();
  await expect(page.getByRole("heading", { name: "نمای کلی" })).toBeVisible();

  await page.goto(`/transfer?from=${alice}`);
  await expect(page.getByText(/قابل استفاده: .*[۰-۹]/)).toBeVisible();
  await page.getByRole("combobox", { name: "به" }).click();
  await page.getByRole("option", { name: /Bob Synthetic/ }).click();
  await page.getByLabel(/مبلغ/).fill("۱۲٫۵۰");
  await page.getByRole("button", { name: "بازبینی انتقال" }).click();
  await expect(page.getByText("بازبینی و تأیید")).toBeVisible();
  await page.getByRole("button", { name: "تأیید انتقال" }).click();
  await expect(page.getByRole("heading", { name: "انتقال ثبت شد" })).toBeVisible();

  // Same money, whatever the digits: back in English the amount reads $12.50.
  await page.getByRole("button", { name: "English" }).first().click();
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
  await page.goto(`/wallets/${alice}`);
  await expect(page.getByText("$87.50").first()).toBeVisible();
});
