import { expect, test } from "@playwright/test";

import { createWallet, fund, signUp } from "./helpers";

test("fund, transfer with review, and see the balanced journal entry", async ({ page }) => {
  await signUp(page);
  const alice = await createWallet(page, "Alice Synthetic");
  const bob = await createWallet(page, "Bob Synthetic");
  await fund(page, alice, "250.00");
  await expect(page.getByText("$250.00").first()).toBeVisible();

  await page.goto(`/transfer?from=${alice}`);
  await page.getByRole("combobox", { name: "To" }).click();
  await page.getByRole("option", { name: /Bob Synthetic/ }).click();
  await page.getByLabel(/Amount/).fill("42.10");
  await page.getByLabel(/Description/).fill("E2E dinner");
  await page.getByRole("button", { name: "Review transfer" }).click();
  await expect(page.getByText("Review and confirm")).toBeVisible();
  await expect(page.getByText("$207.90")).toBeVisible(); // balance after
  await page.getByRole("button", { name: "Confirm transfer" }).click();
  await expect(page.getByRole("heading", { name: "Transfer posted" })).toBeVisible();

  await page.getByRole("link", { name: /^[0-9a-f-]{36}$/ }).click();
  await expect(page.getByText("Journal entry #")).toBeVisible();
  await expect(page.getByText("Balanced")).toBeVisible();

  await page.goto(`/wallets/${bob}`);
  await expect(page.getByText("$42.10").first()).toBeVisible();
});

test("an overspend is a confirmed failure, recorded and visible", async ({ page }) => {
  await signUp(page);
  const a = await createWallet(page, "Low Balance");
  await createWallet(page, "Recipient");
  await fund(page, a, "10");
  // The UI blocks it client-side first...
  await page.goto(`/transfer?from=${a}`);
  await page.getByRole("combobox", { name: "To" }).click();
  await page.getByRole("option", { name: /Recipient/ }).click();
  await page.getByLabel(/Amount/).fill("10.01");
  await page.getByRole("button", { name: "Review transfer" }).click();
  await expect(page.getByRole("alert")).toContainText("Exceeds available balance");
  // ...and the server enforces it regardless of the client.
  const res = await page.evaluate(async (src) => {
    const me = await (await fetch("/api/v1/auth/me")).json();
    const org = me.memberships[0].organization.id;
    const wallets = await (await fetch("/api/v1/wallets", { headers: { "X-Waltrix-Organization": org } })).json();
    const dst = wallets.data.find((w: { id: string }) => w.id !== src).id;
    const r = await fetch("/api/v1/transfers", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Waltrix-Organization": org,
        "X-Requested-With": "waltrix-web",
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: JSON.stringify({ source_wallet_id: src, destination_wallet_id: dst, amount: 1001, currency: "USD" }),
    });
    return { status: r.status, body: await r.json() };
  }, a);
  expect(res.status).toBe(422);
  expect(res.body.error.code).toBe("insufficient_funds");
  await page.goto("/transactions?status=failed");
  await expect(page.getByRole("table").getByText("Failed").first()).toBeVisible();
});

test("reconciliation passes and the audit log records the run", async ({ page }) => {
  await signUp(page);
  const w = await createWallet(page, "Recon Wallet");
  await fund(page, w, "99.99");
  await page.goto("/reconciliation");
  await page.getByRole("button", { name: "Run now" }).click();
  await expect(page.getByText("Ledger reconciled")).toBeVisible();
  await page.goto("/audit");
  const table = page.getByRole("table");
  await expect(table.getByText("reconciliation.run")).toBeVisible();
  await expect(table.getByText("deposit.posted")).toBeVisible();
});

test("API key secret is shown once and only its prefix afterwards", async ({ page }) => {
  await signUp(page);
  await page.goto("/settings/api-keys");
  await page.getByRole("button", { name: "New key" }).click();
  await page.getByLabel("Name").fill("e2e-service");
  await page.getByRole("button", { name: "Create key" }).click();
  const secret = await page.getByRole("dialog").locator(".font-mono").first().innerText();
  expect(secret).toMatch(/^wtx_key_[0-9a-f]{8}_/);
  await page.getByRole("button", { name: "I saved it" }).click();
  await expect(page.getByText(secret)).toHaveCount(0);
  await expect(page.getByRole("table").getByText(/wtx_key_[0-9a-f]{8}_••••/)).toBeVisible();

  const r = await page.request.get("/api/v1/wallets", { headers: { Authorization: `Bearer ${secret}` } });
  expect(r.status()).toBe(200);
});
