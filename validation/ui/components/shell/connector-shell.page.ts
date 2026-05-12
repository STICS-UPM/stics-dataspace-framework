import { expect, Page } from "@playwright/test";

import { clickMarked } from "../../shared/utils/live-marker";
import { errorBanner } from "../../shared/utils/selectors";
import { waitForUiTransition } from "../../shared/utils/waiting";

export class ConnectorShellPage {
  constructor(private readonly page: Page) {}

  async expectReady(): Promise<void> {
    await expect(this.page.getByText(/^\s*log\s*out\s*$/i).first()).toBeVisible({
      timeout: 60_000,
    });
  }

  async navigateToSection(sectionRegex: RegExp, fallbackHashUrl: string): Promise<void> {
    const navTarget = this.page.locator("a, button").filter({ hasText: sectionRegex }).first();

    if ((await navTarget.count()) > 0) {
      await clickMarked(navTarget);
      await waitForUiTransition(this.page);
      return;
    }

    await this.page.goto(fallbackHashUrl, { waitUntil: "domcontentloaded" });
  }

  async assertNoGateway403(context: string): Promise<void> {
    expect(
      await this.page.locator("h1").filter({ hasText: /403 Forbidden/i }).count(),
      `${context} loaded a gateway 403 page`,
    ).toBe(0);
  }

  async assertNoServerErrorBanner(context: string): Promise<void> {
    await expect(
      errorBanner(this.page).first(),
      `${context} shows a server error banner`,
    ).not.toBeVisible({ timeout: 2_000 });
  }
}
