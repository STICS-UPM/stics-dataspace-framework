import { expect, Page } from "@playwright/test";

import { waitForEventualConsistencyPoll } from "../../utils/waiting";

export class MinioBucketBrowserPage {
  private lastBucketName?: string;

  constructor(private readonly page: Page) {}

  async expectReady(bucketName: string): Promise<void> {
    this.lastBucketName = bucketName;

    await this.waitForBucketAccessible(bucketName, 30_000);
    await this.openBucketFromListIfNeeded(bucketName);
    await expect
      .poll(
        async () =>
          (await this.isBucketRoute(bucketName)) ||
          (await this.isBucketDetailVisible(bucketName)) ||
          (await this.isBucketListed(bucketName)),
        {
          message: `MinIO bucket ${bucketName} was not reachable from the object browser`,
          timeout: 15_000,
        },
      )
      .toBeTruthy();
  }

  async assertNoBucketPermissionError(): Promise<void> {
    await expect(
      this.page.getByText(/You require additional permissions in order to view Objects in this bucket/i),
    ).not.toBeVisible({
      timeout: 2_000,
    });
  }

  async expectObjectVisible(objectName: string, timeoutMs = 15_000): Promise<void> {
    await expect(this.page.getByText(objectName, { exact: false }).first()).toBeVisible({
      timeout: timeoutMs,
    });
  }

  async waitForObjectVisible(objectName: string, timeoutMs = 90_000): Promise<void> {
    const startedAt = Date.now();

    while (Date.now() - startedAt < timeoutMs) {
      if (this.lastBucketName) {
        await this.openBucketFromListIfNeeded(this.lastBucketName);
      }

      if ((await this.page.getByText(objectName, { exact: false }).first().count().catch(() => 0)) > 0) {
        await this.expectObjectVisible(objectName, 15_000);
        return;
      }

      await this.page.reload({ waitUntil: "domcontentloaded" });
      await waitForEventualConsistencyPoll(this.page);
    }

    throw new Error(`MinIO object ${objectName} did not become visible within ${timeoutMs}ms`);
  }

  private async waitForBucketAccessible(bucketName: string, timeoutMs: number): Promise<void> {
    await expect
      .poll(
        async () => {
          if (await this.isBucketRoute(bucketName)) {
            return "route";
          }
          if (await this.isBucketDetailVisible(bucketName)) {
            return "detail";
          }
          if (await this.isBucketListed(bucketName)) {
            return "list";
          }
          return "";
        },
        {
          message: `MinIO bucket ${bucketName} did not become visible in the object browser`,
          timeout: timeoutMs,
        },
      )
      .not.toBe("");
  }

  private async openBucketFromListIfNeeded(bucketName: string): Promise<void> {
    if ((await this.isBucketRoute(bucketName)) || (await this.isBucketDetailVisible(bucketName))) {
      return;
    }

    const bucketCell = this.bucketListCell(bucketName);
    if (!(await bucketCell.isVisible().catch(() => false))) {
      return;
    }

    await bucketCell.click();
    await expect
      .poll(
        async () => (await this.isBucketRoute(bucketName)) || (await this.isBucketDetailVisible(bucketName)),
        {
          timeout: 5_000,
        },
      )
      .toBeTruthy()
      .catch(() => undefined);
  }

  private async isBucketRoute(bucketName: string): Promise<boolean> {
    return this.bucketRoutePattern(bucketName).test(this.page.url());
  }

  private async isBucketDetailVisible(bucketName: string): Promise<boolean> {
    const bucketLabelVisible = await this.page
      .getByText(bucketName, { exact: false })
      .first()
      .isVisible()
      .catch(() => false);
    if (!bucketLabelVisible) {
      return false;
    }

    const detailControls = [
      this.page.getByRole("button", { name: /upload/i }).first(),
      this.page.getByRole("button", { name: /create new path/i }).first(),
    ];

    for (const control of detailControls) {
      if ((await control.isVisible().catch(() => false))) {
        return true;
      }
    }

    return false;
  }

  private async isBucketListed(bucketName: string): Promise<boolean> {
    return this.bucketListCell(bucketName).isVisible().catch(() => false);
  }

  private bucketListCell(bucketName: string) {
    return this.page.getByRole("gridcell", { name: new RegExp(`^${this.escapeRegex(bucketName)}$`) }).first();
  }

  private bucketRoutePattern(bucketName: string): RegExp {
    return new RegExp(`/browser/${this.escapeRegex(bucketName)}(?:[/?#]|$)`);
  }

  private escapeRegex(value: string): string {
    return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }
}
