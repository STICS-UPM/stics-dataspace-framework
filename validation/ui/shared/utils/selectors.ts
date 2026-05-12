import { Locator, Page } from "@playwright/test";

export function materialField(page: Page, label: string | RegExp): Locator {
  return page.locator("mat-form-field").filter({ hasText: label }).first();
}

export function materialInput(page: Page, label: string | RegExp): Locator {
  return materialField(page, label).locator("input, textarea").first();
}

export function materialSelect(page: Page, label: string | RegExp): Locator {
  return materialField(page, label);
}

export function snackBar(page: Page): Locator {
  return page
    .locator(".mat-mdc-snack-bar-container, snack-bar-container, .mat-snack-bar-container")
    .first();
}

export function errorBanner(page: Page): Locator {
  return page.locator("text=/\\b403\\b|Forbidden|\\b500\\b|Internal Server Error|Access Denied/i");
}
