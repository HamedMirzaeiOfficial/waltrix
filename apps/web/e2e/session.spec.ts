import { expect, test } from "@playwright/test";

import { PASSWORD, signUp } from "./helpers";

// Regression: choosing an existing organization used to bounce back to /organizations, because the
// session read the selected id from a module variable that did not trigger a re-render.
test("signing in again and choosing an existing organization opens the dashboard", async ({ page }) => {
  const email = await signUp(page, "Returning Org");
  await page.getByRole("button", { name: "Sign out" }).first().click();
  await page.waitForURL("**/login");

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL("**/organizations");
  await page.getByRole("button", { name: /Returning Org/ }).click();

  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page).toHaveURL((u) => u.pathname === "/");
});
