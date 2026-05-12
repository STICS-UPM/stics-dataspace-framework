import { expect, Page } from "@playwright/test";

import { waitForEventualConsistencyPoll } from "../../shared/utils/waiting";

export class MinioBucketBrowserPage {
  constructor(private readonly page: Page) {}

  async expectReady(bucketName: string): Promise<void> {
    const escaped = bucketName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    await expect(this.page).toHaveURL(new RegExp(`/browser/${escaped}`), {
      timeout: 30_000,
    });
    await expect(this.page.getByText(bucketName, { exact: false }).first()).toBeVisible({
      timeout: 30_000,
    });
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
      if ((await this.page.getByText(objectName, { exact: false }).first().count().catch(() => 0)) > 0) {
        await this.expectObjectVisible(objectName, 15_000);
        return;
      }

      await this.page.reload({ waitUntil: "domcontentloaded" });
      await waitForEventualConsistencyPoll(this.page);
    }

    throw new Error(`MinIO object ${objectName} did not become visible within ${timeoutMs}ms`);
  }
}
