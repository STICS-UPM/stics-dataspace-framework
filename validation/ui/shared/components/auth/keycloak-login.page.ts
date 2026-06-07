import { expect, Page } from "@playwright/test";

import { clickMarked, fillMarked } from "../../utils/live-marker";

type KeycloakLoginConfig = {
  portalUser: string;
  portalPassword: string;
  skipLogin: boolean;
};

const TRANSIENT_GATEWAY_STATUSES = new Set([502, 503, 504]);
const TRANSIENT_GATEWAY_MAX_ATTEMPTS = 6;
const TRANSIENT_GATEWAY_RETRY_DELAY_MS = 3000;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export class KeycloakLoginPage {
  private lastOpenedUrl?: string;

  constructor(
    private readonly page: Page,
    private readonly config: KeycloakLoginConfig,
  ) {}

  async open(baseUrl: string): Promise<void> {
    this.lastOpenedUrl = baseUrl;
    let lastError: unknown;
    for (let attempt = 1; attempt <= TRANSIENT_GATEWAY_MAX_ATTEMPTS; attempt += 1) {
      try {
        const response = await this.page.goto(baseUrl, { waitUntil: "domcontentloaded", timeout: 60_000 });
        await this.page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => undefined);
        const transientReason = await this.transientGatewayReason(response?.status());
        if (!transientReason) {
          return;
        }
        lastError = new Error(transientReason);
      } catch (error) {
        lastError = error;
      }

      if (attempt < TRANSIENT_GATEWAY_MAX_ATTEMPTS) {
        await sleep(TRANSIENT_GATEWAY_RETRY_DELAY_MS * attempt);
      }
    }

    throw new Error(
      `Portal login endpoint did not become available after ${TRANSIENT_GATEWAY_MAX_ATTEMPTS} attempts: ${
        lastError instanceof Error ? lastError.message : String(lastError)
      }`,
    );
  }

  async loginIfNeeded(): Promise<void> {
    if (this.config.skipLogin) {
      return;
    }

    await this.waitForGatewayRecovery();

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

    await this.waitForGatewayRecovery();

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

  private async waitForGatewayRecovery(): Promise<void> {
    let lastReason = "";
    for (let attempt = 1; attempt <= TRANSIENT_GATEWAY_MAX_ATTEMPTS; attempt += 1) {
      const reason = await this.transientGatewayReason();
      if (!reason) {
        return;
      }
      lastReason = reason;
      if (attempt < TRANSIENT_GATEWAY_MAX_ATTEMPTS) {
        await sleep(TRANSIENT_GATEWAY_RETRY_DELAY_MS * attempt);
        await this.page.reload({ waitUntil: "domcontentloaded", timeout: 60_000 }).catch(() => undefined);
        await this.page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => undefined);
      }
    }

    throw new Error(
      `Portal login page stayed behind a transient gateway error after ${TRANSIENT_GATEWAY_MAX_ATTEMPTS} attempts: ${lastReason}`,
    );
  }

  private async transientGatewayReason(status?: number): Promise<string | null> {
    if (status && TRANSIENT_GATEWAY_STATUSES.has(status)) {
      return `HTTP ${status}`;
    }

    const bodyText = await this.page.locator("body").textContent({ timeout: 1000 }).catch(() => "");
    if (/\b(502|503|504)\b/i.test(bodyText || "") || /Bad Gateway|Service Temporarily Unavailable|Gateway Time-?out/i.test(bodyText || "")) {
      return (bodyText || "transient gateway error").replace(/\s+/g, " ").trim().slice(0, 160);
    }

    return null;
  }

  private async redirectThroughDashboardProxyLogin(currentUrl: string): Promise<void> {
    const { origin, prefix, returnTo } = this.dashboardProxyLoginTarget(currentUrl);
    const loginUrl = new URL(`${prefix}/edc-dashboard-api/auth/login`, origin);
    loginUrl.searchParams.set("returnTo", returnTo);
    await this.page.goto(loginUrl.toString(), { waitUntil: "networkidle" });
  }

  private dashboardProxyLoginTarget(currentUrl: string): { origin: string; prefix: string; returnTo: string } {
    const currentLocation = this.parseUrl(currentUrl);
    const openedLocation = this.parseUrl(this.lastOpenedUrl);
    const candidates = [openedLocation, currentLocation].filter((candidate): candidate is URL => candidate !== null);

    let selectedLocation = currentLocation ?? openedLocation;
    let selectedPrefix = "";
    for (const candidate of candidates) {
      const prefix = this.dashboardPrefix(candidate.pathname);
      if (prefix.length >= selectedPrefix.length) {
        selectedPrefix = prefix;
        selectedLocation = candidate;
      }
    }

    if (!selectedLocation) {
      throw new Error(`Cannot derive EDC dashboard login URL from '${currentUrl}'`);
    }

    const returnToPath = `${selectedPrefix}/edc-dashboard/`;
    return {
      origin: selectedLocation.origin,
      prefix: selectedPrefix,
      returnTo: `${returnToPath}${selectedLocation.search}${selectedLocation.hash}`,
    };
  }

  private parseUrl(value?: string): URL | null {
    if (!value) {
      return null;
    }
    try {
      return new URL(value);
    } catch {
      return null;
    }
  }

  private dashboardPrefix(pathname: string): string {
    const match = pathname.match(/^(.*)\/edc-dashboard(?:\/|$)/i);
    if (!match) {
      return "";
    }
    return match[1].replace(/\/+$/, "");
  }
}
