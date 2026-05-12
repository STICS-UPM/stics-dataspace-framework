import { expect, Page } from "@playwright/test";

import { clickMarked, fillMarked, pressMarked } from "../../shared/utils/live-marker";
import { materialInput, materialSelect, snackBar } from "../../shared/utils/selectors";
import {
  FAST_UI_RETRY_INTERVALS,
  waitForEventualConsistencyPoll,
  waitForUiTransition,
} from "../../shared/utils/waiting";

type ContractDefinitionListExpectations = {
  policyId?: string;
  assetId?: string;
};

export class ContractDefinitionCreatePage {
  constructor(private readonly page: Page) {}

  async goto(baseUrl: string): Promise<void> {
    await this.page.goto(`${baseUrl.replace(/\/$/, "")}/contract-definitions/create`, {
      waitUntil: "domcontentloaded",
    });
  }

  async gotoList(baseUrl: string): Promise<void> {
    await this.page.goto(`${baseUrl.replace(/\/$/, "")}/contract-definitions`, {
      waitUntil: "domcontentloaded",
    });
  }

  async expectReady(): Promise<void> {
    await expect(
      this.page.locator("mat-card-title", { hasText: /Create a contract definition/i }),
    ).toBeVisible({ timeout: 10_000 });
  }

  async fillContractDefinitionId(contractDefinitionId: string): Promise<void> {
    await fillMarked(materialInput(this.page, /^ID$/), contractDefinitionId);
  }

  async selectMatchingPolicies(policyId: string, timeoutMs = 120_000): Promise<void> {
    const deadline = Date.now() + timeoutMs;
    let attempt = 0;

    while (Date.now() < deadline) {
      attempt += 1;

      if (attempt > 1) {
        await this.page.reload({ waitUntil: "domcontentloaded", timeout: 10_000 });
        await this.expectReady();
      }

      const accessSelected = await this.trySelectPolicyOption(/Access policy/i, policyId);
      if (!accessSelected) {
        await waitForEventualConsistencyPoll(this.page);
        continue;
      }

      const contractSelected = await this.trySelectPolicyOption(/Contract policy/i, policyId);
      if (contractSelected) {
        return;
      }

      await waitForEventualConsistencyPoll(this.page);
    }

    throw new Error(
      `Policy '${policyId}' exists in the policies list but did not become selectable in both contract definition policy selectors within ${timeoutMs}ms. ` +
      "This usually means the contract definition form is not loading/searching the full policy catalog.",
    );
  }

  async addAsset(assetId: string): Promise<void> {
    const assetInput = this.page.locator("input[placeholder='Search assets']").first();
    await expect(assetInput).toBeVisible({ timeout: 5_000 });
    await fillMarked(assetInput, assetId);
    await pressMarked(assetInput, "ArrowDown").catch(() => {});
    const option = this.page
      .locator(".cdk-overlay-pane [role='option'], .cdk-overlay-pane mat-option")
      .filter({ hasText: new RegExp(`^\\s*${escapeRegExp(assetId)}\\s*$`) })
      .last();
    await expect(option).toBeVisible({ timeout: 5_000 });
    await option.scrollIntoViewIfNeeded().catch(() => {});
    await clickMarked(option, { timeout: 5_000, force: true });

    await expect(this.page.locator("mat-chip").filter({ hasText: assetId }).first()).toBeVisible({
      timeout: 5_000,
    });
  }

  async submit(): Promise<void> {
    await clickMarked(this.page.getByRole("button", { name: /^Create$/i }));
  }

  async waitForCreationSuccess(timeoutMs = 10_000): Promise<string> {
    const notification = snackBar(this.page);
    await expect(notification).toContainText(/contract definition created/i, {
      timeout: timeoutMs,
    });
    return ((await notification.textContent()) ?? "").replace(/\s+/g, " ").trim();
  }

  async expectContractDefinitionListed(
    contractDefinitionId: string,
    expectations: ContractDefinitionListExpectations = {},
    timeoutMs = 15_000,
  ): Promise<void> {
    await expect(async () => {
      const found = await this.findContractDefinition(contractDefinitionId, expectations);
      expect(
        found,
        `Contract definition ${contractDefinitionId} is not visible in the contract definitions list`,
      ).toBeTruthy();
    }).toPass({
      timeout: timeoutMs,
      intervals: FAST_UI_RETRY_INTERVALS,
    });
  }

  private async findContractDefinition(
    contractDefinitionId: string,
    expectations: ContractDefinitionListExpectations,
  ): Promise<boolean> {
    if ((await this.contractDefinitionCard(contractDefinitionId, expectations).count()) > 0) {
      return true;
    }

    while (await this.goToNextPage()) {
      if ((await this.contractDefinitionCard(contractDefinitionId, expectations).count()) > 0) {
        return true;
      }
    }

    return false;
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

  private contractDefinitionCard(
    contractDefinitionId: string,
    expectations: ContractDefinitionListExpectations,
  ) {
    let card = this.page.locator(".card mat-card").filter({ hasText: contractDefinitionId });

    if (expectations.policyId) {
      card = card.filter({ hasText: expectations.policyId });
    }

    if (expectations.assetId) {
      card = card.filter({ hasText: expectations.assetId });
    }

    return card.first();
  }

  private async trySelectPolicyOption(
    label: string | RegExp,
    policyId: string,
  ): Promise<boolean> {
    const policyOption = new RegExp(escapeRegExp(policyId));

    await clickMarked(materialSelect(this.page, label), { timeout: 5_000 });

    const overlayOptions = this.page.locator(".cdk-overlay-pane [role='option'], .cdk-overlay-pane mat-option");
    const option = overlayOptions.filter({ hasText: policyOption }).last();
    if ((await option.count().catch(() => 0)) > 0) {
      await option.scrollIntoViewIfNeeded().catch(() => {});
      await clickMarked(option, { timeout: 5_000, force: true });
      return true;
    }

    await this.page.keyboard.press("Escape").catch(() => {});
    return false;
  }
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
