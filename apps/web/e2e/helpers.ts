import { expect, type Page } from "@playwright/test";

export const PASSWORD = "correct-horse-battery";

export async function signUp(page: Page, org = "E2E Org"): Promise<string> {
  const email = `e2e-${Date.now()}-${Math.random().toString(16).slice(2, 6)}@example.test`;
  await page.goto("/login");
  await page.getByRole("button", { name: "Create an account" }).click();
  await page.getByLabel("Name").fill("E2E Operator");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: /create account/i }).click();
  await page.waitForURL("**/organizations");
  await page.getByLabel("New organization name").fill(org);
  await page.getByRole("button", { name: "Create" }).click();
  await page.waitForURL((u) => u.pathname === "/");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  return email;
}

export async function createWallet(page: Page, name: string, currency = "USD"): Promise<string> {
  await page.goto("/wallets");
  await page.getByRole("button", { name: "New wallet" }).first().click();
  await page.getByLabel("Display name").fill(name);
  await page.getByLabel("Owner reference").fill(`cust_${name.toLowerCase().replace(/\W/g, "")}`);
  if (currency !== "USD") {
    await page.getByLabel("Currency").click();
    await page.getByRole("option", { name: currency }).click();
  }
  await page.getByRole("button", { name: "Create wallet" }).click();
  await page.waitForURL(/\/wallets\/[0-9a-f-]{36}$/);
  return page.url().split("/").pop()!;
}

export async function fund(page: Page, walletId: string, amount: string) {
  await page.goto(`/wallets/${walletId}`);
  await page.getByRole("button", { name: "Add funds" }).click();
  await page.getByLabel(/Amount/).fill(amount);
  await page.getByRole("dialog").getByRole("button", { name: "Add funds" }).click();
  await expect(page.getByRole("dialog").getByText("Confirmed")).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "Close" }).first().click();
}
