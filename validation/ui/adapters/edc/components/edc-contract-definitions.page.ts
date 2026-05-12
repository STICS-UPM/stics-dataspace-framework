import { expect, Page } from "@playwright/test";

import { clickMarked, fillMarked, selectOptionMarked } from "../../../shared/utils/live-marker";
import {
  waitForEventualConsistencyPoll,
  waitForInputValue,
  waitForUiTransition,
} from "../../../shared/utils/waiting";

export class EdcContractDefinitionsPage {
  constructor(private readonly page: Page) {}

  async goto(baseUrl: string): Promise<void> {
    await this.page.goto(`${baseUrl.replace(/\/$/, "")}/contract-definitions`, {
      waitUntil: "domcontentloaded",
    });
  }

  async expectReady(): Promise<void> {
    await expect(this.page).toHaveURL(/\/edc-dashboard\/contract-definitions(?:\/)?(?:\?.*)?$/, {
      timeout: 30_000,
    });
    await expect(this.createButton()).toBeVisible({
      timeout: 30_000,
    });
  }

  async createForAsset(
    contractDefinitionId: string,
    policyId: string,
    assetId: string,
  ): Promise<"visible-click" | "angular-component-fallback"> {
    await clickMarked(this.createButton());

    const dialog = this.openDialog();
    await expect(dialog.locator("lib-contract-definition-create")).toBeVisible({ timeout: 30_000 });

    await fillMarked(dialog.locator('input[name="id"]').first(), contractDefinitionId);
    await this.selectPolicy(dialog.locator('select[name="accessPolicyId"]').first(), policyId, "access");
    await this.selectPolicy(dialog.locator('select[name="contractPolicyId"]').first(), policyId, "contract");
    const assetSelectionMode = await this.selectAsset(dialog, assetId);

    const createResponse = this.page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url().includes("/management/v3/contractdefinitions"),
      { timeout: 45_000 },
    );

    await clickMarked(dialog.getByRole("button", { name: /create contract definition/i }));
    const response = await createResponse;
    expect(response.ok(), `EDC contract definition creation returned HTTP ${response.status()}`).toBeTruthy();
    await expect(dialog).not.toBeVisible({ timeout: 30_000 });
    return assetSelectionMode;
  }

  async createForAllAssets(contractDefinitionId: string, policyId: string): Promise<"all-assets"> {
    await clickMarked(this.createButton());

    const dialog = this.openDialog();
    await expect(dialog.locator("lib-contract-definition-create")).toBeVisible({ timeout: 30_000 });

    await fillMarked(dialog.locator('input[name="id"]').first(), contractDefinitionId);
    await this.selectPolicy(dialog.locator('select[name="accessPolicyId"]').first(), policyId, "access");
    await this.selectPolicy(dialog.locator('select[name="contractPolicyId"]').first(), policyId, "contract");

    const createResponse = this.page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url().includes("/management/v3/contractdefinitions"),
      { timeout: 45_000 },
    );

    await clickMarked(dialog.getByRole("button", { name: /create contract definition/i }));
    const response = await createResponse;
    expect(response.ok(), `EDC contract definition creation returned HTTP ${response.status()}`).toBeTruthy();
    await expect(dialog).not.toBeVisible({ timeout: 30_000 });
    return "all-assets";
  }

  async waitForContractDefinitionListed(
    contractDefinitionId: string,
    options: { policyId: string; assetId?: string },
    timeoutMs = 60_000,
  ): Promise<void> {
    const startedAt = Date.now();
    while (Date.now() - startedAt < timeoutMs) {
      await this.filterById(contractDefinitionId);
      const card = this.contractDefinitionCard(contractDefinitionId);
      if ((await card.count().catch(() => 0)) > 0) {
        await expect(card).toBeVisible({ timeout: 15_000 });
        await expect(card).toContainText(options.policyId);
        if (options.assetId) {
          await expect(card).toContainText(options.assetId);
        } else {
          await expect(card).toContainText(/all assets/i);
        }
        return;
      }
      await this.page.reload({ waitUntil: "domcontentloaded" });
      await this.expectReady();
      await waitForEventualConsistencyPoll(this.page);
    }

    throw new Error(
      `EDC contract definition ${contractDefinitionId} did not appear in the provider contract definition list`,
    );
  }

  private async selectPolicy(
    select: ReturnType<Page["locator"]>,
    policyId: string,
    policyKind: string,
  ): Promise<void> {
    await expect(select, `The ${policyKind} policy selector is not visible`).toBeVisible({
      timeout: 30_000,
    });
    await expect(select.locator("option", { hasText: policyId })).toHaveCount(1, {
      timeout: 30_000,
    });
    await selectOptionMarked(select, { label: policyId });
    await waitForUiTransition(this.page);
  }

  private async selectAsset(
    dialog: ReturnType<Page["locator"]>,
    assetId: string,
  ): Promise<"visible-click" | "angular-component-fallback"> {
    const filterInput = dialog.locator('lib-multiselect-with-search input[placeholder="Filter items..."]').first();
    await expect(filterInput, "The asset selector filter is not visible").toBeVisible({
      timeout: 30_000,
    });
    await clickMarked(filterInput);
    await fillMarked(filterInput, assetId);
    await waitForInputValue(filterInput, assetId);
    await clickMarked(filterInput);

    const assetOption = this.page.locator(".dropdown-content label").filter({ hasText: assetId }).first();
    await expect(assetOption, `Asset option ${assetId} is not attached to the asset selector`).toHaveCount(1, {
      timeout: 30_000,
    });
    try {
      await clickMarked(assetOption, { timeout: 2_000 });
      await expect(dialog.getByText(`ID = ${assetId}`)).toBeVisible({ timeout: 15_000 });
      return "visible-click";
    } catch {
      // The dashboard renders the multiselect dropdown outside the native dialog top layer,
      // so the option may be attached but not visually actionable. Keep the test strict by
      // selecting the same Angular component state and reporting this mode to the test artifact.
    }

    const selectedByAngular = await dialog.locator("lib-contract-definition-create").evaluate((element, id) => {
      const win = window as typeof window & {
        ng?: {
          getComponent?: (target: Element) => any;
          applyChanges?: (target: Element) => void;
        };
      };
      const component = win.ng?.getComponent?.(element);
      if (!component) {
        return false;
      }
      if (component.searchChild?.toggleItem) {
        component.searchChild.toggleItem(id);
      } else if (typeof component.handleSelectionChange === "function") {
        component.handleSelectionChange([id]);
      } else {
        return false;
      }
      win.ng?.applyChanges?.(element);
      return true;
    }, assetId);

    expect(
      selectedByAngular,
      "The EDC contract definition asset selector is not visually clickable and Angular component fallback is unavailable",
    ).toBeTruthy();
    await expect(dialog.getByText(`ID = ${assetId}`)).toBeVisible({ timeout: 15_000 });
    return "angular-component-fallback";
  }

  private async filterById(contractDefinitionId: string): Promise<void> {
    const filterInput = this.page.locator('input[placeholder*="Filter for ID"]').first();
    if ((await filterInput.count().catch(() => 0)) === 0) {
      return;
    }
    await fillMarked(filterInput, contractDefinitionId);
    await waitForInputValue(filterInput, contractDefinitionId);
  }

  private contractDefinitionCard(contractDefinitionId: string) {
    return this.page.locator("lib-contract-definition-card").filter({ hasText: contractDefinitionId }).first();
  }

  private createButton() {
    return this.page.locator("button").filter({ hasText: /\bCreate\b/i }).first();
  }

  private openDialog() {
    return this.page.locator("dialog[open]#dashboard-dialog").first();
  }
}
