import { expect, Page, Response } from "@playwright/test";

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
const transientGatewayStatuses = new Set([502, 503, 504]);
const transientGatewayTextPattern =
  /\b(?:502|503|504)\b|Bad Gateway|Service Temporarily Unavailable|Gateway Time-?out/i;

function numericEnv(name: string, defaultValue: number): number {
  const parsed = Number.parseInt(process.env[name] || "", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : defaultValue;
}

function dashboardUrl(baseUrl: string, path: string): string {
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  if (path.startsWith("/")) {
    return dashboardAbsolutePathUrl(baseUrl, path);
  }
  return `${baseUrl.replace(/\/$/, "")}/${path.replace(/^\/+/, "")}`;
}

function dashboardAbsolutePathUrl(baseUrl: string, path: string): string {
  try {
    const base = new URL(baseUrl);
    const marker = "/edc-dashboard";
    const markerIndex = base.pathname.indexOf(marker);
    if (markerIndex >= 0 && path.startsWith(marker)) {
      const publicPrefix = base.pathname.slice(0, markerIndex).replace(/\/$/, "");
      base.pathname = `${publicPrefix}${path}`.replace(/\/{2,}/g, "/");
      base.search = "";
      base.hash = "";
      return base.toString();
    }
  } catch {
    // Fall back to browser URL resolution below.
  }
  return new URL(path, baseUrl).toString();
}

export function edcDashboardApiPath(currentUrl: string, apiPath: string): string {
  const suffix = apiPath.startsWith("/") ? apiPath : `/${apiPath}`;
  try {
    const pathname = new URL(currentUrl).pathname;
    const match = pathname.match(/^(.*)\/edc-dashboard(?:\/|$)/i);
    const publicPrefix = (match?.[1] || "").replace(/\/$/, "");
    return `${publicPrefix}/edc-dashboard-api${suffix}`.replace(/\/{2,}/g, "/");
  } catch {
    return `/edc-dashboard-api${suffix}`;
  }
}

async function pageShowsTransientGateway(page: Page): Promise<boolean> {
  const bodyText = await page.locator("body").textContent({ timeout: 1_000 }).catch(() => "");
  return transientGatewayTextPattern.test(bodyText || "");
}

function responseShowsTransientGateway(response: Response | null): boolean {
  return Boolean(response && transientGatewayStatuses.has(response.status()));
}

export async function gotoEdcDashboardRoute(
  page: Page,
  baseUrl: string,
  path: string,
  context = path,
): Promise<void> {
  const url = dashboardUrl(baseUrl, path);
  const timeoutMs = numericEnv("UI_EDC_DASHBOARD_ROUTE_READY_TIMEOUT_MS", 90_000);
  const retryIntervalMs = numericEnv("UI_EDC_DASHBOARD_ROUTE_RETRY_INTERVAL_MS", 2_000);
  const deadline = Date.now() + timeoutMs;
  let lastStatus: number | undefined;
  let lastBodyWasGateway = false;

  do {
    const response = await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60_000 }).catch((error) => {
      lastStatus = undefined;
      throw error;
    });
    lastStatus = response?.status();
    lastBodyWasGateway = await pageShowsTransientGateway(page);

    if (!responseShowsTransientGateway(response) && !lastBodyWasGateway) {
      return;
    }

    if (Date.now() < deadline) {
      await page.waitForTimeout(retryIntervalMs);
    }
  } while (Date.now() < deadline);

  throw new Error(
    `EDC dashboard route '${context}' stayed unavailable after ${timeoutMs}ms at ${url}. ` +
      `Last HTTP status: ${lastStatus ?? "unknown"}. ` +
      `Gateway body detected: ${lastBodyWasGateway ? "yes" : "no"}.`,
  );
}

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
    const baseHref = await this.page
      .locator("base")
      .first()
      .getAttribute("href", { timeout: 1_000 })
      .catch(() => null);
    const authMePath = edcDashboardApiPath(baseHref || this.page.url(), "/auth/me");
    await this.page.waitForFunction(async (path) => {
      try {
        const response = await fetch(path as string, {
          method: "GET",
          credentials: "include",
          cache: "no-store",
        });
        if (!response.ok) {
          return false;
        }
        const contentType = response.headers.get("content-type") || "";
        if (!contentType.toLowerCase().includes("application/json")) {
          return false;
        }
        const state = await response.json();
        return state?.authMode === "oidc-bff" && state?.authenticated === true;
      } catch {
        return false;
      }
    }, authMePath, {
      timeout: 60_000,
    });

    return await this.page.evaluate(async (path) => {
      const response = await fetch(path as string, {
        method: "GET",
        credentials: "include",
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error(`EDC dashboard auth state request failed with HTTP ${response.status}`);
      }
      const contentType = response.headers.get("content-type") || "";
      if (!contentType.toLowerCase().includes("application/json")) {
        const body = await response.text();
        throw new Error(
          `EDC dashboard auth state returned '${contentType || "unknown"}' instead of JSON: ${body.slice(0, 120)}`,
        );
      }
      return (await response.json()) as DashboardAuthState;
    }, authMePath);
  }

  async expectNoServerErrorBanner(context: string): Promise<void> {
    await expect(
      errorBanner(this.page).first(),
      `${context} shows a server error banner`,
    ).not.toBeVisible({ timeout: 2_000 });
  }

  async navigateToSection(sectionName: string, expectedPath: string): Promise<void> {
    const sectionPattern = navigationItemTextPattern(sectionName);
    let navButton = this.page
      .locator("a, button")
      .filter({ hasText: sectionPattern })
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
        .filter({ hasText: sectionPattern })
        .first();
    }

    if ((await navButton.count().catch(() => 0)) > 0) {
      await expect(navButton, `Navigation item '${sectionName}' is not visible`).toBeVisible({
        timeout: 30_000,
      });

      await clickMarked(navButton);
      await waitForUiTransition(this.page);
    } else {
      await gotoEdcDashboardRoute(this.page, new URL(".", this.page.url()).toString(), expectedPath, sectionName);
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

function navigationItemTextPattern(sectionName: string): RegExp {
  return new RegExp(`^\\s*(?:[a-z0-9_]+\\s+)?${escapeRegExp(sectionName)}\\s*$`);
}
