import { Locator, Page } from "@playwright/test";

import { clickMarked, fillMarked } from "../../shared/utils/live-marker";
import { waitForUiTransition } from "../../shared/utils/waiting";

type MinioConsoleCredentials = {
  username: string;
  password: string;
};

export class MinioConsoleLoginPage {
  constructor(private readonly page: Page) {}

  async open(bucketBrowserUrl: string): Promise<void> {
    await this.page.goto(bucketBrowserUrl, {
      waitUntil: "domcontentloaded",
    });
  }

  async loginIfNeeded(credentials: MinioConsoleCredentials): Promise<void> {
    const usernameInput = await this.firstExistingLocator([
      this.page
        .locator(
          "#accessKey, input[name='accessKey'], input[placeholder*='Access Key' i], input[autocomplete='username']",
        )
        .first(),
      this.page.getByLabel(/username|access key/i).first(),
      this.page.getByRole("textbox", { name: /username|access key/i }).first(),
      this.page
        .locator("input[name='username' i], input[placeholder*='Username' i], input[aria-label*='Username' i]")
        .first(),
    ]);
    const passwordInput = await this.firstExistingLocator([
      this.page
        .locator(
          "#secretKey, input[name='secretKey'], input[placeholder*='Secret Key' i], input[aria-label*='Secret Key' i]",
        )
        .first(),
      this.page.getByLabel(/password|secret key/i).first(),
      this.page
        .locator("input[type='password'], input[name='password' i], input[placeholder*='Password' i], input[aria-label*='Password' i]")
        .first(),
    ]);

    if (!usernameInput || !passwordInput) {
      return;
    }

    await fillMarked(usernameInput, credentials.username);
    await fillMarked(passwordInput, credentials.password);

    const submitButton = this.page
      .locator("button[type='submit'], input[type='submit'], button")
      .filter({ hasText: /login|sign in|signin/i })
      .first();

    await clickMarked(submitButton);
    await waitForUiTransition(this.page, 3_000);
    await this.page.waitForTimeout(500);
  }

  private async firstExistingLocator(candidates: Locator[]): Promise<Locator | null> {
    const deadline = Date.now() + 10_000;
    while (Date.now() < deadline) {
      for (const candidate of candidates) {
        if ((await candidate.count().catch(() => 0)) > 0) {
          return candidate;
        }
      }
      await this.page.waitForTimeout(250);
    }
    return null;
  }
}
