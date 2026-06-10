import { expect, Page } from "@playwright/test";

import { clickMarked, fillMarked, pressMarked } from "../../../../shared/utils/live-marker";
import { materialInput, snackBar } from "../../../../shared/utils/selectors";
import { FAST_UI_RETRY_INTERVALS, waitForUiTransition } from "../../../../shared/utils/waiting";

export class PolicyCreatePage {
  constructor(private readonly page: Page) {}

  async goto(baseUrl: string): Promise<void> {
    await this.page.goto(`${baseUrl.replace(/\/$/, "")}/policies/create`, {
      waitUntil: "domcontentloaded",
    });
  }

  async gotoList(baseUrl: string): Promise<void> {
    await this.page.goto(`${baseUrl.replace(/\/$/, "")}/policies`, {
      waitUntil: "domcontentloaded",
    });
  }

  async expectReady(): Promise<void> {
    await expect(
      this.page.locator("mat-card-title", { hasText: /Create a new policy/i }),
    ).toBeVisible({ timeout: 10_000 });
  }

  async fillPolicyId(policyId: string): Promise<void> {
    await fillMarked(materialInput(this.page, /^ID$/), policyId);
  }

  async addParticipantIdConstraint(participantId: string): Promise<void> {
    await clickMarked(this.page.locator("policy-form-add-menu button[mat-icon-button]").first());
    await clickMarked(this.page.getByRole("menuitem").filter({ hasText: /^Participant ID$/i }));

    const input = this.page.locator("participant-id-select input").first();
    await expect(input).toBeVisible({ timeout: 5_000 });
    await fillMarked(input, participantId);
    await pressMarked(input, "Enter");

    await expect(this.page.locator("participant-id-select mat-chip").filter({ hasText: participantId })).toBeVisible({
      timeout: 5_000,
    });
  }

  async submit(): Promise<void> {
    await clickMarked(this.page.getByRole("button", { name: /^Create$/i }));
  }

  async waitForCreationSuccess(timeoutMs = 10_000): Promise<string> {
    const notification = snackBar(this.page);
    await expect(notification).toContainText(/successfully created/i, {
      timeout: timeoutMs,
    });
    return ((await notification.textContent()) ?? "").replace(/\s+/g, " ").trim();
  }

  async expectPolicyListed(policyId: string, timeoutMs = 60_000): Promise<void> {
    await expect(async () => {
      const found = await this.findPolicy(policyId);
      expect(found, `Policy ${policyId} is not visible in the policies list`).toBeTruthy();
    }).toPass({
      timeout: timeoutMs,
      intervals: FAST_UI_RETRY_INTERVALS,
    });
  }

  private async findPolicy(policyId: string): Promise<boolean> {
    await this.showLargestPageSize();
    await this.goToFirstPage();

    if (await this.pageContainsPolicy(policyId)) {
      return true;
    }

    while (await this.goToNextPage()) {
      if (await this.pageContainsPolicy(policyId)) {
        return true;
      }
    }

    return false;
  }

  private async showLargestPageSize(): Promise<void> {
    const pageSizeSelect = this.page.getByRole("combobox", { name: /items per page/i }).first();
    if ((await pageSizeSelect.count()) === 0) {
      return;
    }

    await clickMarked(pageSizeSelect).catch(() => undefined);
    const options = this.page.locator(".cdk-overlay-pane [role='option'], .cdk-overlay-pane mat-option");
    const optionTexts = await options.allTextContents().catch(() => []);
    const pageSizes = optionTexts
      .map((text) => Number.parseInt(text.replace(/\D+/g, ""), 10))
      .filter((value) => Number.isFinite(value));
    const largestPageSize = Math.max(...pageSizes, 0);
    if (!largestPageSize) {
      await this.page.keyboard.press("Escape").catch(() => undefined);
      return;
    }

    await clickMarked(options.filter({ hasText: new RegExp(`^\\s*${largestPageSize}\\s*$`) }).last(), {
      timeout: 5_000,
      force: true,
    }).catch(async () => {
      await this.page.keyboard.press("Escape").catch(() => undefined);
    });
    await waitForUiTransition(this.page);
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

  private async pageContainsPolicy(policyId: string): Promise<boolean> {
    try {
      await expect(this.page.locator("body")).toContainText(policyId, { timeout: 2_000 });
      return true;
    } catch {
      return false;
    }
  }
}
