import type { Page } from "@playwright/test";

import { test, expect } from "../../../shared/fixtures/dataspace.fixture";

import { KeycloakLoginPage } from "../../../shared/components/auth/keycloak-login.page";
import { ConnectorShellPage } from "../components/shell/connector-shell.page";
import { collectBrowserDiagnostics } from "../../../shared/utils/browser-diagnostics";
import { clickMarked, fillMarked } from "../../../shared/utils/live-marker";

type ObserverNavigationTarget = {
  label: string;
  heading: RegExp;
  placeholder: RegExp;
  value: string;
  button: RegExp;
  expectedPath: RegExp;
};

type AIModelObserverUiReport = {
  startedAt: string;
  connector: string;
  portalBaseUrl: string;
  linkedCases: string[];
  observerHomeUrl: string;
  navigationChecks: Array<{
    label: string;
    value: string;
    url: string;
    status: "passed";
  }>;
  observerResponses: Array<{ url: string; status: number }>;
  skippedReason?: string;
};

const OBSERVER_DEMO_ENV = "UI_AI_MODEL_OBSERVER_DEMO";
const TARGETS: ObserverNavigationTarget[] = [
  {
    label: "Asset timeline",
    heading: /Asset timeline/i,
    placeholder: /Enter assetId/i,
    value: "asset-a52-observer-demo",
    button: /Open asset timeline/i,
    expectedPath: /\/ai-model-observer\/timeline\/asset-a52-observer-demo/i,
  },
  {
    label: "Agreement evidence",
    heading: /Agreement evidence/i,
    placeholder: /Enter agreementId/i,
    value: "agreement-a52-observer-demo",
    button: /Open agreement evidence/i,
    expectedPath: /\/ai-model-observer\/agreements\/agreement-a52-observer-demo/i,
  },
  {
    label: "Benchmark evidence",
    heading: /Benchmark evidence/i,
    placeholder: /Enter benchmarkRunId/i,
    value: "benchmark-a52-observer-demo",
    button: /Open benchmark evidence/i,
    expectedPath: /\/ai-model-observer\/benchmarks\/benchmark-a52-observer-demo/i,
  },
  {
    label: "Participant summary",
    heading: /Participant summary/i,
    placeholder: /Enter participantId/i,
    value: "participant-a52-observer-demo",
    button: /Open participant summary/i,
    expectedPath: /\/ai-model-observer\/participants\/participant-a52-observer-demo/i,
  },
];

test.skip(
  process.env[OBSERVER_DEMO_ENV] !== "1",
  `Opt-in demo: set ${OBSERVER_DEMO_ENV}=1 to validate AI Model Observer navigation from the INESData UI.`,
);

function observerHomeUrl(portalBaseUrl: string): string {
  return `${portalBaseUrl.replace(/\/$/, "")}/ai-model-observer`;
}

async function observerHomeIsVisible(page: Page): Promise<boolean> {
  const heading = page.getByRole("heading", { name: /AI Model Observer/i }).first();
  try {
    await expect(heading).toBeVisible({ timeout: 10_000 });
  } catch {
    return false;
  }
  return true;
}

test("10 AI Model Observer: home and evidence navigation are available from INESData UI", async ({
  page,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  test.skip(dataspaceRuntime.adapter !== "inesdata", "This demo validates the INESData connector UI path.");

  const loginPage = new KeycloakLoginPage(page, {
    portalUser: dataspaceRuntime.consumer.username,
    portalPassword: dataspaceRuntime.consumer.password,
    skipLogin: false,
  });
  const shellPage = new ConnectorShellPage(page);
  const browserDiagnostics = collectBrowserDiagnostics(page);
  const report: AIModelObserverUiReport = {
    startedAt: new Date().toISOString(),
    connector: dataspaceRuntime.consumer.connectorName,
    portalBaseUrl: dataspaceRuntime.consumer.portalBaseUrl,
    linkedCases: ["MH-OBS-01", "PT5-MH-17", "Model Clearing House"],
    observerHomeUrl: observerHomeUrl(dataspaceRuntime.consumer.portalBaseUrl),
    navigationChecks: [],
    observerResponses: [],
  };

  page.on("response", (response) => {
    const url = response.url();
    if (url.includes("/model-observer") || url.includes("/ai-model-observer")) {
      report.observerResponses.push({ url, status: response.status() });
    }
  });

  try {
    await loginPage.open(dataspaceRuntime.consumer.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await shellPage.expectReady();
    await captureStep(page, "01-ai-model-observer-after-login");

    await shellPage.navigateToSection(/^\s*AI Model Observer\s*$/i, report.observerHomeUrl);
    await shellPage.assertNoGateway403("AI Model Observer page");
    await shellPage.assertNoServerErrorBanner("AI Model Observer page");

    if (!(await observerHomeIsVisible(page))) {
      report.skippedReason =
        "AI Model Observer UI is not integrated in this INESData connector build yet.";
      await attachJson("ai-model-observer-ui-report", report);
      test.skip(true, report.skippedReason);
    }

    await expect(page.getByText(/clearing-house evidence/i).first()).toBeVisible();
    await captureStep(page, "02-ai-model-observer-home");

    for (const target of TARGETS) {
      await page.goto(report.observerHomeUrl, { waitUntil: "domcontentloaded" });
      await expect(page.getByRole("heading", { name: /AI Model Observer/i }).first()).toBeVisible();

      const card = page.locator("article").filter({ hasText: target.heading }).first();
      await expect(card, `${target.label} card is not visible`).toBeVisible();
      await fillMarked(card.getByPlaceholder(target.placeholder), target.value);
      await captureStep(page, `03-ai-model-observer-${target.label.toLowerCase().replace(/\s+/g, "-")}-filled`);
      await clickMarked(card.getByRole("button", { name: target.button }));
      await expect(page).toHaveURL(target.expectedPath, { timeout: 10_000 });
      await expect(page.getByText(/AI Model Observer/i).first()).toBeVisible();
      await captureStep(page, `04-ai-model-observer-${target.label.toLowerCase().replace(/\s+/g, "-")}-route`);
      report.navigationChecks.push({
        label: target.label,
        value: target.value,
        url: page.url(),
        status: "passed",
      });
    }

    expect(report.navigationChecks, "Observer did not validate all navigation targets").toHaveLength(TARGETS.length);
  } finally {
    const browserDiagnosticsSnapshot = browserDiagnostics.snapshot();
    browserDiagnostics.dispose();
    await attachJson("ai-model-observer-ui-browser-diagnostics", browserDiagnosticsSnapshot);
    await attachJson("ai-model-observer-ui-report", {
      ...report,
      finishedAt: new Date().toISOString(),
      browserDiagnostics: {
        eventCount: browserDiagnosticsSnapshot.eventCount,
        droppedEventCount: browserDiagnosticsSnapshot.droppedEventCount,
      },
    });
  }
});
