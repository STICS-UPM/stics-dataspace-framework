import { expect, Locator, Page } from "@playwright/test";

export const UI_WAIT_BUDGETS = {
  shortTransitionMs: 1_000,
  pollIntervalMs: 1_000,
} as const;

export const EVENTUAL_UI_RETRY_INTERVALS = [1_000, 2_000];
export const FAST_UI_RETRY_INTERVALS = [500, 1_000, 2_000];

export async function waitForUiTransition(
  page: Page,
  timeoutMs: number = UI_WAIT_BUDGETS.shortTransitionMs,
): Promise<void> {
  await Promise.race([
    page.waitForLoadState("domcontentloaded", { timeout: timeoutMs }).catch(() => undefined),
    page.waitForLoadState("load", { timeout: timeoutMs }).catch(() => undefined),
  ]);
}

export async function waitForEventualConsistencyPoll(
  page: Page,
  intervalMs = UI_WAIT_BUDGETS.pollIntervalMs,
): Promise<void> {
  if (intervalMs > 0) {
    await page.waitForTimeout(intervalMs);
  }
}

export async function waitForInputValue(
  locator: Locator,
  expectedValue: string,
  timeoutMs = UI_WAIT_BUDGETS.shortTransitionMs,
): Promise<void> {
  await expect(locator).toHaveValue(expectedValue, { timeout: timeoutMs }).catch(() => undefined);
}
