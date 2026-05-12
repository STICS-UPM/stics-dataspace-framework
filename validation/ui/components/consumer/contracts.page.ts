import { expect, Page } from "@playwright/test";

import { clickMarked } from "../../shared/utils/live-marker";
import { materialSelect, snackBar } from "../../shared/utils/selectors";
import { waitForUiTransition } from "../../shared/utils/waiting";

export class ContractsPage {
  constructor(private readonly page: Page) {}

  async goto(baseUrl: string): Promise<void> {
    await this.page.goto(`${baseUrl.replace(/\/$/, "")}/contracts`, {
      waitUntil: "domcontentloaded",
    });
  }

  async expectReady(): Promise<void> {
    await expect(this.page).toHaveURL(/\/contracts(?:\/)?$/);
    await expect(
      this.page.locator(".container .card mat-card, .no-items").first(),
    ).toBeVisible({ timeout: 30_000 });
  }

  async hasContractForAsset(assetId: string): Promise<boolean> {
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

  async startInesDataStoreTransfer(assetId: string): Promise<string> {
    const card = this.contractCard(assetId);
    await expect(card).toBeVisible({ timeout: 30_000 });

    await clickMarked(card.getByRole("button", { name: /^Transfer$/i }));
    const dialog = this.page.getByRole("dialog", { name: /Transfer/i });
    await expect(dialog).toBeVisible({ timeout: 15_000 });

    await clickMarked(materialSelect(this.page, "Destination"));
    await clickMarked(this.page.locator("mat-option").filter({ hasText: /InesDataStore/i }).first());
    await clickMarked(dialog.getByRole("button", { name: /start transfer/i }));

    const notification = snackBar(this.page);
    await expect(notification).toContainText(/transfer initiated successfully/i, {
      timeout: 30_000,
    });
    return ((await notification.textContent()) ?? "").replace(/\s+/g, " ").trim();
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
      await clickMarked(previousButton);
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

    await clickMarked(nextButton);
    await waitForUiTransition(this.page);
    return true;
  }
}
