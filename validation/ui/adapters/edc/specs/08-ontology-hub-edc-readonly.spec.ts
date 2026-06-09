import type { APIResponse, Response } from "@playwright/test";

import { KeycloakLoginPage } from "../../../shared/components/auth/keycloak-login.page";
import { test, expect } from "../../../shared/fixtures/dataspace.fixture";
import { EdcDashboardPage } from "../components/edc-dashboard.page";
import { EdcOntologyHubPage } from "../components/edc-ml-components.page";

type OntologyHubEdcReport = {
  startedAt: string;
  connector: string;
  portalBaseUrl: string;
  linkedCases: string[];
  runtimeConfig?: {
    ontologyUrl?: string;
  };
  ontologyHubApi?: {
    url: string;
    status: number;
    itemCount?: number;
  };
  errorResponses: Array<{ url: string; status: number }>;
};

test.skip(
  process.env.UI_ONTOLOGY_HUB_EDC_DEMO !== "1" && process.env.UI_ONTOLOGY_HUB_INESDATA_DEMO !== "1",
  "Set UI_ONTOLOGY_HUB_EDC_DEMO=1 to validate Ontology Hub read-only integration from the EDC dashboard.",
);

function dashboardConfigUrl(portalBaseUrl: string): string {
  return `${portalBaseUrl.replace(/\/$/, "")}/config/app-config.json`;
}

function isOntologyHubUrl(url: string): boolean {
  return url.includes("/dataset/api/v2/vocabulary/list") || url.includes("ontology-hub");
}

async function responseJsonArrayLength(response: APIResponse | Response): Promise<number | undefined> {
  try {
    const payload = await response.json();
    return Array.isArray(payload) ? payload.length : undefined;
  } catch {
    return undefined;
  }
}

test("08 edc ontology hub: read-only dashboard integration surfaces ontology endpoint", async ({
  page,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  const loginPage = new KeycloakLoginPage(page, {
    portalUser: dataspaceRuntime.consumer.username,
    portalPassword: dataspaceRuntime.consumer.password,
    skipLogin: false,
  });
  const dashboardPage = new EdcDashboardPage(page);
  const ontologyPage = new EdcOntologyHubPage(page);
  const report: OntologyHubEdcReport = {
    startedAt: new Date().toISOString(),
    connector: dataspaceRuntime.consumer.connectorName,
    portalBaseUrl: dataspaceRuntime.consumer.portalBaseUrl,
    linkedCases: ["PT5-OH-16", "INT-OH-DS-03", "DS-UI-OH-EDC-01"],
    errorResponses: [],
  };

  page.on("response", (response) => {
    const url = response.url();
    if (response.status() >= 400 && isOntologyHubUrl(url)) {
      report.errorResponses.push({ url, status: response.status() });
    }
  });

  try {
    await loginPage.open(dataspaceRuntime.consumer.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await dashboardPage.expectShellReady();
    await captureStep(page, "01-edc-ontology-hub-after-login");

    const configResponse = await page.context().request.get(
      dashboardConfigUrl(dataspaceRuntime.consumer.portalBaseUrl),
    );
    expect(configResponse.ok(), "The authenticated EDC dashboard runtime config is not available").toBeTruthy();
    const config = await configResponse.json();
    const runtime = config.runtime ?? config;
    report.runtimeConfig = {
      ontologyUrl: runtime.ontologyUrl,
    };
    await attachJson("edc-ontology-hub-runtime-config", report.runtimeConfig);
    expect(report.runtimeConfig.ontologyUrl, "EDC dashboard does not expose an Ontology Hub URL").toBeTruthy();

    const ontologyHubResponsePromise = page.waitForResponse(
      (response) => response.url().includes("/dataset/api/v2/vocabulary/list"),
      { timeout: 60_000 },
    );
    await ontologyPage.goto(dataspaceRuntime.consumer.portalBaseUrl);
    await dashboardPage.expectNoServerErrorBanner("EDC Ontology Hub page");
    await ontologyPage.expectReady();
    const ontologyHubResponse = await ontologyHubResponsePromise;
    report.ontologyHubApi = {
      url: ontologyHubResponse.url(),
      status: ontologyHubResponse.status(),
      itemCount: await responseJsonArrayLength(ontologyHubResponse),
    };
    expect(
      ontologyHubResponse.status(),
      `Ontology Hub vocabulary list returned HTTP ${ontologyHubResponse.status()} at ${ontologyHubResponse.url()}`,
    ).toBe(200);
    await captureStep(page, "02-edc-ontology-hub-ontologies");

    expect(
      report.errorResponses,
      `Ontology Hub/EDC integration returned errors: ${JSON.stringify(report.errorResponses)}`,
    ).toHaveLength(0);
  } finally {
    await attachJson("edc-ontology-hub-report", {
      ...report,
      finishedAt: new Date().toISOString(),
    });
  }
});
