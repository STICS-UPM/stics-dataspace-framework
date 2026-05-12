import { expect, Page } from "@playwright/test";

import { clickMarked, fillMarked } from "../../shared/utils/live-marker";

type KeycloakLoginConfig = {
  portalUser: string;
  portalPassword: string;
  skipLogin: boolean;
};

export class KeycloakLoginPage {
  constructor(
    private readonly page: Page,
    private readonly config: KeycloakLoginConfig,
  ) {}

  async open(baseUrl: string): Promise<void> {
    await this.page.goto(baseUrl, { waitUntil: "networkidle" });
  }

  async loginIfNeeded(): Promise<void> {
    if (this.config.skipLogin) {
      return;
    }

    if ((await this.logoutControl().count()) > 0) {
      return;
    }

    const signInButton = this.page
      .locator("a, button")
      .filter({ hasText: /sign in|login/i })
      .first();

    if ((await signInButton.count()) > 0) {
      await Promise.all([
        this.page.waitForLoadState("networkidle"),
        clickMarked(signInButton),
      ]);
    }

    const loginInputs = await this.resolveLoginInputs();
    if (!loginInputs) {
      throw new Error("Could not find Keycloak login inputs on the page");
    }

    if (!this.config.portalUser || !this.config.portalPassword) {
      throw new Error("Missing PORTAL_USER or PORTAL_PASSWORD for Keycloak login");
    }

    await fillMarked(loginInputs.usernameInput, this.config.portalUser);
    await fillMarked(loginInputs.passwordInput, this.config.portalPassword);

    const submitButton = this.page
      .locator("#kc-login, button[type='submit'], input[type='submit']")
      .first();

    await Promise.all([
      this.page.waitForLoadState("networkidle"),
      clickMarked(submitButton),
    ]);
  }

  async expectLoggedIn(): Promise<void> {
    await expect(this.logoutControl()).toBeVisible({
      timeout: 60_000,
    });
  }

  private logoutControl(): ReturnType<Page["getByText"]> {
    return this.page.getByText(/^\s*log\s*out\s*$/i).first();
  }

  private async resolveLoginInputs(): Promise<{
    usernameInput: ReturnType<Page["locator"]>;
    passwordInput: ReturnType<Page["locator"]>;
  } | null> {
    const usernameInput = this.page
      .locator("#username, input[name='username'], input[autocomplete='username']")
      .first();
    const passwordInput = this.page
      .locator("#password, input[name='password'], input[type='password']")
      .first();

    if ((await usernameInput.count()) > 0 && (await passwordInput.count()) > 0) {
      return { usernameInput, passwordInput };
    }

    const currentUrl = this.page.url();
    if (/\/edc-dashboard\/?/i.test(currentUrl)) {
      await this.redirectThroughDashboardProxyLogin(currentUrl);
      if ((await usernameInput.count()) > 0 && (await passwordInput.count()) > 0) {
        return { usernameInput, passwordInput };
      }
    }

    return null;
  }

  private async redirectThroughDashboardProxyLogin(currentUrl: string): Promise<void> {
    const currentLocation = new URL(currentUrl);
    const loginUrl = new URL("/edc-dashboard-api/auth/login", currentLocation.origin);
    const returnTo = `${currentLocation.pathname}${currentLocation.search}${currentLocation.hash}` || "/edc-dashboard/";
    loginUrl.searchParams.set("returnTo", returnTo);
    await this.page.goto(loginUrl.toString(), { waitUntil: "networkidle" });
  }
}
