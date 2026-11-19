import { expect, test } from "@playwright/test";

import { createWallet, signUp } from "./helpers";

test("mobile navigation and stacked tables", async ({ page }) => {
  await signUp(page, "Mobile Org");
  await createWallet(page, "Pocket Wallet");
  await page.goto("/");
  await page.getByRole("button", { name: "Open menu" }).click();
  await page.getByRole("dialog", { name: "Menu" }).getByRole("link", { name: "Wallets" }).click();
  await expect(page.getByRole("heading", { name: "Wallets" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Wallets" }).getByText("Pocket Wallet")).toBeVisible();
});
