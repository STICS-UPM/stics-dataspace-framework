import { expect, Page } from "@playwright/test";

import type { ConnectorPortalRuntime } from "../../../shared/utils/dataspace-runtime";
import { checkMarked, clickMarked, fillMarked, selectOptionMarked } from "../../../shared/utils/live-marker";
import { waitForEventualConsistencyPoll, waitForUiTransition } from "../../../shared/utils/waiting";
import { gotoEdcDashboardRoute } from "./edc-dashboard.page";

const PUSH_TRANSFER_PATTERN = /push/i;

export class EdcContractsPage {
  constructor(private readonly page: Page) {}

  async goto(baseUrl: string): Promise<void> {
    await gotoEdcDashboardRoute(this.page, baseUrl, "contracts", "Contracts");
  }

  async expectReady(): Promise<void> {
    await expect(this.page).toHaveURL(/\/edc-dashboard\/contracts(?:\/)?(?:\?.*)?$/);
    await expect(this.page.locator("lib-consumer-provider-switch").first()).toBeVisible({
      timeout: 30_000,
    });
  }

  async waitForContractVisible(assetId: string, timeoutMs = 90_000): Promise<void> {
    const startedAt = Date.now();

    while (Date.now() - startedAt < timeoutMs) {
      if ((await this.contractCard(assetId).count().catch(() => 0)) > 0) {
        await expect(this.contractCard(assetId)).toBeVisible({ timeout: 15_000 });
        return;
      }
      await this.page.reload({ waitUntil: "domcontentloaded" });
      await waitForEventualConsistencyPoll(this.page);
    }

    throw new Error(`Contract for asset ${assetId} did not appear within ${timeoutMs}ms`);
  }

  async startTransferForAsset(
    assetId: string,
    consumerRuntime: ConnectorPortalRuntime,
    objectName: string,
  ): Promise<string> {
    const card = this.contractCard(assetId);
    await expect(card, `Contract card for ${assetId} is not visible`).toBeVisible({
      timeout: 30_000,
    });

    await clickMarked(card.getByRole("button", { name: /transfer/i }).first());
    const dialog = this.openDialog();
    await expect(dialog.getByRole("button", { name: /start transfer/i })).toBeVisible({
      timeout: 30_000,
    });

    const usesObjectStorageDestination =
      Boolean(consumerRuntime.transferDestination) &&
      consumerRuntime.transferDestinationType.toLowerCase() !== "httpdata";
    const selectedTransferType = await this.selectPreferredTransferType(
      dialog,
      usesObjectStorageDestination,
    );
    if (PUSH_TRANSFER_PATTERN.test(selectedTransferType)) {
      await this.fillPushDestination(dialog, consumerRuntime, objectName);
    }

    const responsePromise = this.page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url().includes("/management/v3/transferprocesses"),
      { timeout: 30_000 },
    );

    await clickMarked(dialog.getByRole("button", { name: /start transfer/i }));
    const response = await responsePromise;
    expect(response.ok(), `Transfer request returned HTTP ${response.status()}`).toBeTruthy();

    await expect(dialog.locator("ul.steps, div[role='alert'], .loading").first()).toBeVisible({
      timeout: 30_000,
    });
    await this.closeOpenDialogIfPresent();

    return selectedTransferType;
  }

  private async selectPreferredTransferType(
    dialog: ReturnType<Page["locator"]>,
    preferS3Push: boolean,
  ): Promise<string> {
    const select = dialog.locator('select[name="transferType"]').first();
    await expect(select).toBeVisible({ timeout: 30_000 });

    const options = await select.locator("option").allTextContents();
    const normalizedOptions = options.map((entry) => entry.trim()).filter(Boolean);
    const chosen =
      (preferS3Push
        ? normalizedOptions.find((entry) => /amazons3-push/i.test(entry))
        : undefined) ||
      normalizedOptions.find((entry) => PUSH_TRANSFER_PATTERN.test(entry)) ||
      normalizedOptions[0];

    if (!chosen) {
      throw new Error("No transfer type is available in the transfer dialog");
    }

    await selectOptionMarked(select, { label: chosen });
    await waitForUiTransition(this.page);
    return chosen;
  }

  private async fillPushDestination(
    dialog: ReturnType<Page["locator"]>,
    consumerRuntime: ConnectorPortalRuntime,
    objectName: string,
  ): Promise<void> {
    const destination = consumerRuntime.transferDestination;
    if (!destination) {
      throw new Error("Consumer runtime does not expose an S3 transfer destination");
    }

    await expect(dialog.locator('input[name="bucketName"]').first()).toBeVisible({
      timeout: 30_000,
    });

    await fillMarked(dialog.locator('input[name="region"]'), destination.region);
    await fillMarked(dialog.locator('input[name="bucketName"]'), destination.bucketName);
    await fillMarked(dialog.locator('input[name="objectName"]'), objectName);
    await fillMarked(dialog.locator('input[name="endpointOverride"]'), destination.endpointOverride);

    const plainCredentialsToggle = dialog.locator('input[name="plain-credentials-switch"]').first();
    if ((await plainCredentialsToggle.count().catch(() => 0)) > 0 && !(await plainCredentialsToggle.isChecked())) {
      await checkMarked(plainCredentialsToggle);
    }

    const accessKeyInput = dialog.locator('input[name="accessKeyId"]').first();
    const secretKeyInput = dialog.locator('input[name="secretAccessKey"]').first();
    await expect(accessKeyInput).toBeVisible({ timeout: 15_000 });
    await expect(secretKeyInput).toBeVisible({ timeout: 15_000 });
    await fillMarked(accessKeyInput, destination.accessKeyId);
    await fillMarked(secretKeyInput, destination.secretAccessKey);
  }

  private contractCard(assetId: string) {
    return this.page.locator("lib-contract-agreement-card").filter({ hasText: assetId }).first();
  }

  private openDialog() {
    return this.page.locator("dialog[open]#dashboard-dialog").first();
  }

  private async closeOpenDialogIfPresent(): Promise<void> {
    const dialog = this.openDialog();
    if ((await dialog.count().catch(() => 0)) === 0) {
      return;
    }

    const closeButton = dialog.locator("form[method='dialog'] button").first();
    if ((await closeButton.count().catch(() => 0)) > 0) {
      await clickMarked(closeButton);
      await expect(dialog).not.toBeVisible({ timeout: 15_000 });
    }
  }
}
