import { expect, Page } from "@playwright/test";

import { clickMarked } from "../../../shared/utils/live-marker";
import { errorBanner } from "../../../shared/utils/selectors";
import { waitForUiTransition } from "../../../shared/utils/waiting";

export type EdcPageProbe = {
  description: string;
  selector?: string;
  text?: RegExp;
};

type DashboardAuthState = {
  authMode?: string;
  authenticated?: boolean;
  loginPath?: string;
  logoutPath?: string;
  user?: {
    username?: string;
    name?: string;
    email?: string;
  } | null;
};

const pageMarkerTimeoutMs = 30_000;
const pageMarkerPollIntervalMs = 500;

export class EdcDashboardPage {
  constructor(private readonly page: Page) {}

  async expectShellReady(): Promise<void> {
    await expect(
      this.page.locator("text=EDC Dashboard").first(),
      "The EDC dashboard shell did not load",
    ).toBeVisible({
      timeout: 60_000,
    });
    await expect(
      this.page.getByText(/sign in to the edc dashboard/i),
      "The EDC dashboard remained in the interactive login screen",
    ).not.toBeVisible({
      timeout: 5_000,
    });
  }

  async expectAuthenticatedSession(): Promise<void> {
    const authState = await this.waitForAuthenticatedSession();
    expect(
      authState.authMode,
      "The dashboard proxy did not expose the expected authentication mode",
    ).toBe("oidc-bff");
    expect(
      authState.authenticated,
      "The dashboard proxy did not report an authenticated browser session",
    ).toBe(true);
  }

  async waitForAuthenticatedSession(): Promise<DashboardAuthState> {
    await this.page.waitForFunction(async () => {
      try {
        const response = await fetch("/edc-dashboard-api/auth/me", {
          method: "GET",
          credentials: "include",
          cache: "no-store",
        });
        if (!response.ok) {
          return false;
        }
        const state = await response.json();
        return state?.authMode === "oidc-bff" && state?.authenticated === true;
      } catch {
        return false;
      }
    }, undefined, {
      timeout: 60_000,
    });

    return await this.page.evaluate(async () => {
      const response = await fetch("/edc-dashboard-api/auth/me", {
        method: "GET",
        credentials: "include",
        cache: "no-store",
      });
      return (await response.json()) as DashboardAuthState;
    });
  }

  async expectNoServerErrorBanner(context: string): Promise<void> {
    await expect(
      errorBanner(this.page).first(),
      `${context} shows a server error banner`,
    ).not.toBeVisible({ timeout: 2_000 });
  }

  async navigateToSection(sectionName: string, expectedPath: string): Promise<void> {
    let navButton = this.page
      .locator("a, button")
      .filter({ hasText: new RegExp(`^\\s*${escapeRegExp(sectionName)}\\s*$`, "i") })
      .first();

    if ((await navButton.count().catch(() => 0)) === 0) {
      const menuToggle = this.page
        .locator("button")
        .filter({ has: this.page.locator("span.material-symbols-rounded", { hasText: /menu/i }) })
        .first();

      if ((await menuToggle.count().catch(() => 0)) > 0) {
        await clickMarked(menuToggle);
        await waitForUiTransition(this.page);
      }

      navButton = this.page
        .locator("a, button")
        .filter({ hasText: new RegExp(`^\\s*${escapeRegExp(sectionName)}\\s*$`, "i") })
        .first();
    }

    if ((await navButton.count().catch(() => 0)) > 0) {
      await expect(navButton, `Navigation item '${sectionName}' is not visible`).toBeVisible({
        timeout: 30_000,
      });

      await clickMarked(navButton);
      await waitForUiTransition(this.page);
    } else {
      await this.page.goto(new URL(expectedPath, this.page.url()).toString(), {
        waitUntil: "domcontentloaded",
      });
    }

    await expect(this.page).toHaveURL(new RegExp(`${escapeRegExp(expectedPath)}(?:\\?.*)?$`), {
      timeout: 30_000,
    });
  }

  async expectPageMarkers(probes: EdcPageProbe[], context: string): Promise<void> {
    const deadline = Date.now() + pageMarkerTimeoutMs;
    const probeDescriptions = probes.map((probe) => probe.description).join(", ");
    let lastAttachedProbe: string | undefined;

    while (Date.now() < deadline) {
      for (const probe of probes) {
        const locator = probe.selector
          ? this.page.locator(probe.selector).first()
          : this.page.getByText(probe.text ?? /.^/).first();

        if ((await locator.count().catch(() => 0)) === 0) {
          continue;
        }

        lastAttachedProbe = probe.description;

        if (await locator.isVisible().catch(() => false)) {
          return;
        }
      }

      await this.page.waitForTimeout(pageMarkerPollIntervalMs);
    }

    const attachedDetail = lastAttachedProbe ? ` Last attached probe: ${lastAttachedProbe}.` : "";
    throw new Error(
      `${context} did not render any expected probe within ${pageMarkerTimeoutMs}ms at ${this.page.url()}. ` +
        `Expected probes: ${probeDescriptions}.${attachedDetail}`,
    );
  }
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
