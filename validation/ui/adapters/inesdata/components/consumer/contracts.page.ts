import { expect, Page, Response } from "@playwright/test";

import { clickMarked } from "../../../../shared/utils/live-marker";
import { snackBar } from "../../../../shared/utils/selectors";
import { waitForUiTransition } from "../../../../shared/utils/waiting";
import { selectLocalStoreDestination } from "../storage-destination";

export class ContractsPage {
  constructor(private readonly page: Page) {}

  async goto(baseUrl: string): Promise<void> {
    const contractsResponse = this.waitForContractsListResponse(15_000);
    await this.page.goto(`${baseUrl.replace(/\/$/, "")}/contracts`, {
      waitUntil: "domcontentloaded",
    });
    await contractsResponse;
    await waitForUiTransition(this.page);
  }

  async expectReady(): Promise<void> {
    await expect(this.page).toHaveURL(/\/contracts(?:\/)?$/);
    await expect(
      this.page.locator(".container .card mat-card, .no-items").first(),
    ).toBeVisible({ timeout: 30_000 });
  }

  async hasContractForAsset(assetId: string): Promise<boolean> {
    await this.showLargestPageSize();
    await this.goToFirstPage();

    if ((await this.contractCard(assetId).count()) > 0) {
      return true;
    }

    while (await this.goToNextPage()) {
      if ((await this.contractCard(assetId).count()) > 0) {
        return true;
      }
    }

    return false;
  }

  async showLargestPageSize(): Promise<void> {
    const pageSizeCombobox = this.page
      .getByRole("combobox", { name: /items per page/i })
      .first();

    if ((await pageSizeCombobox.count()) === 0) {
      return;
    }

    const currentValue = normalizeText(await pageSizeCombobox.innerText({ timeout: 1_000 }).catch(() => ""));
    if (/^20\b/.test(currentValue)) {
      return;
    }

    await clickMarked(pageSizeCombobox, { force: true });
    const largestOption = this.page.getByRole("option", { name: /^\s*20\s*$/ }).first();
    const optionVisible = await largestOption
      .waitFor({ state: "visible", timeout: 3_000 })
      .then(() => true)
      .catch(() => false);
    if (!optionVisible) {
      await this.page.keyboard.press("Escape").catch(() => undefined);
      return;
    }

    const contractsResponse = this.waitForContractsListResponse(15_000);
    await clickMarked(largestOption, { force: true });
    await contractsResponse;
    await waitForUiTransition(this.page);
  }

  async waitForContractsListResponse(timeoutMs = 10_000): Promise<boolean> {
    return this.page
      .waitForResponse(
        (response) => this.isSuccessfulContractsListResponse(response),
        { timeout: timeoutMs },
      )
      .then(() => true)
      .catch(() => false);
  }

  async startInesDataStoreTransfer(assetId: string, maxAttempts = 3): Promise<string> {
    let lastNotification = "";

    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      const card = this.contractCard(assetId);
      await expect(card).toBeVisible({ timeout: 30_000 });

      await clickMarked(card.getByRole("button", { name: /^Transfer$/i }));
      const dialog = this.page.getByRole("dialog", { name: /Transfer/i });
      await expect(dialog).toBeVisible({ timeout: 15_000 });

      await selectLocalStoreDestination(this.page);
      await clickMarked(dialog.getByRole("button", { name: /start transfer/i }));

      const notification = snackBar(this.page);
      await expect(notification).toBeVisible({ timeout: 30_000 });
      lastNotification = normalizeText((await notification.textContent()) ?? "");

      if (/transfer initiated successfully/i.test(lastNotification)) {
        return lastNotification;
      }

      if (/failed to create transfer request/i.test(lastNotification) && attempt < maxAttempts) {
        await notification.waitFor({ state: "hidden", timeout: 5_000 }).catch(() => undefined);
        await this.page.waitForTimeout(2_000 * attempt);
        continue;
      }

      throw new Error(
        `Transfer was not initiated for asset ${assetId}. Last notification: ${lastNotification || "none"}`,
      );
    }

    throw new Error(
      `Transfer was not initiated for asset ${assetId} after ${maxAttempts} attempts. Last notification: ${lastNotification || "none"}`,
    );
  }

  private contractCard(assetId: string) {
    return this.page.locator(".card mat-card").filter({ hasText: assetId }).first();
  }

  private async goToFirstPage(): Promise<void> {
    const previousButton = this.page.locator(
      "button.mat-paginator-navigation-previous, button[aria-label*='Previous page']",
    ).first();

    if ((await previousButton.count()) === 0) {
      return;
    }

    while (await previousButton.isEnabled().catch(() => false)) {
      const contractsResponse = this.waitForContractsListResponse(15_000);
      await clickMarked(previousButton);
      await contractsResponse;
      await waitForUiTransition(this.page);
    }
  }

  private async goToNextPage(): Promise<boolean> {
    const nextButton = this.page.locator(
      "button.mat-paginator-navigation-next, button[aria-label*='Next page']",
    ).first();

    if ((await nextButton.count()) === 0) {
      return false;
    }

    if (!(await nextButton.isEnabled().catch(() => false))) {
      return false;
    }

    const contractsResponse = this.waitForContractsListResponse(15_000);
    await clickMarked(nextButton);
    await contractsResponse;
    await waitForUiTransition(this.page);
    return true;
  }

  private isSuccessfulContractsListResponse(response: Response): boolean {
    const url = response.url();
    return (
      response.request().method() === "POST" &&
      response.status() >= 200 &&
      response.status() < 300 &&
      (url.includes("/management/v3/contractagreements/request") ||
        url.includes("/management/contractagreements/request"))
    );
  }
}

function normalizeText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}
