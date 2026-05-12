import { test, expect } from "@playwright/test";
import { portalUrlForDataspace } from "../../shared/target-runtime";

test("INESDATA-LING-02: linguistic catalog is visible", async ({ page }) => {
  const portalUrl = portalUrlForDataspace("linguistic");

  await page.goto(portalUrl);
  await expect(page.getByRole("heading", { name: /catalog|catálogo/i })).toBeVisible();
});
