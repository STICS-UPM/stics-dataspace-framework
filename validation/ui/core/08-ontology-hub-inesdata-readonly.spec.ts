import { APIResponse, Response } from "@playwright/test";

import { test, expect } from "../shared/fixtures/dataspace.fixture";

import { KeycloakLoginPage } from "../components/auth/keycloak-login.page";
import { ConnectorShellPage } from "../components/shell/connector-shell.page";
import { collectBrowserDiagnostics } from "../shared/utils/browser-diagnostics";

type OntologyHubInesdataReport = {
  startedAt: string;
  connector: string;
  portalBaseUrl: string;
  linkedCases: string[];
  runtimeConfig?: {
    ontologyUrl?: string;
    sharedVocabularyBaseUrl?: string;
    sharedVocabularyRequestPath?: string;
  };
  vocabularyApi?: {
    url: string;
    status: number;
    itemCount?: number;
  };
  ontologyHubApi?: {
    url: string;
    status: number;
    itemCount?: number;
  };
  errorResponses: Array<{ url: string; status: number }>;
  fatalErrorResponses: Array<{ url: string; status: number }>;
};

test.skip(
  process.env.UI_ONTOLOGY_HUB_INESDATA_DEMO !== "1",
  "Opt-in demo: set UI_ONTOLOGY_HUB_INESDATA_DEMO=1 to validate Ontology Hub read-only integration from the INESData UI.",
);

async function responseJsonArrayLength(response: APIResponse | Response): Promise<number | undefined> {
  try {
    const payload = await response.json();
    return Array.isArray(payload) ? payload.length : undefined;
  } catch {
    return undefined;
  }
}

function runtimeConfigUrl(portalBaseUrl: string): string {
  return `${portalBaseUrl.replace(/\/$/, "")}/assets/config/app.config.json`;
}

function isOntologyHubIntegrationUrl(url: string): boolean {
  return (
    url.includes("/connector-vocabularies/") ||
    url.includes("/dataset/api/v2/vocabulary/list") ||
    url.includes("ontology-hub")
  );
}

test("08 ontology hub: read-only INESData UI integration surfaces vocabularies and ontologies", async ({
  page,
  request,
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
  const report: OntologyHubInesdataReport = {
    startedAt: new Date().toISOString(),
    connector: dataspaceRuntime.consumer.connectorName,
    portalBaseUrl: dataspaceRuntime.consumer.portalBaseUrl,
    linkedCases: ["PT5-OH-16", "INT-OH-DS-03", "DS-UI-OH-01"],
    errorResponses: [],
    fatalErrorResponses: [],
  };

  page.on("response", (response) => {
    const url = response.url();
    if (response.status() >= 400 && isOntologyHubIntegrationUrl(url)) {
      report.errorResponses.push({ url, status: response.status() });
    }
  });

  try {
    const configResponse = await request.get(runtimeConfigUrl(dataspaceRuntime.consumer.portalBaseUrl));
    expect(configResponse.ok(), "The connector UI runtime config is not available").toBeTruthy();
    const config = await configResponse.json();
    const runtime = config.runtime ?? config;
    report.runtimeConfig = {
      ontologyUrl: runtime.ontologyUrl,
      sharedVocabularyBaseUrl: runtime.service?.vocabulary?.baseUrl,
      sharedVocabularyRequestPath: runtime.service?.vocabulary?.getAllShared,
    };
    await attachJson("ontology-hub-inesdata-runtime-config", report.runtimeConfig);
    expect(report.runtimeConfig.ontologyUrl, "INESData UI does not expose an Ontology Hub URL").toContain(
      "ontology-hub",
    );

    await loginPage.open(dataspaceRuntime.consumer.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await shellPage.expectReady();
    await captureStep(page, "01-ontology-hub-inesdata-after-login");

    const vocabularyResponsePromise = page.waitForResponse(
      (response) => response.url().includes("/connector-vocabularies/request"),
      { timeout: 45_000 },
    );
    await shellPage.navigateToSection(
      /^\s*Vocabularies\s*$/i,
      `${dataspaceRuntime.consumer.portalBaseUrl.replace(/\/$/, "")}/vocabularies`,
    );
    await shellPage.assertNoGateway403("Vocabularies page");
    await shellPage.assertNoServerErrorBanner("Vocabularies page");
    await expect(page.getByText(/Create vocabulary/i).first()).toBeVisible();
    const vocabularyResponse = await vocabularyResponsePromise;
    report.vocabularyApi = {
      url: vocabularyResponse.url(),
      status: vocabularyResponse.status(),
      itemCount: await responseJsonArrayLength(vocabularyResponse),
    };
    expect(
      vocabularyResponse.status(),
      `Shared vocabulary API returned HTTP ${vocabularyResponse.status()} at ${vocabularyResponse.url()}`,
    ).toBe(200);
    await captureStep(page, "02-ontology-hub-inesdata-vocabularies");

    const ontologyHubResponsePromise = page.waitForResponse(
      (response) => response.url().includes("/dataset/api/v2/vocabulary/list"),
      { timeout: 45_000 },
    );
    await shellPage.navigateToSection(
      /^\s*Ontologies\s*$/i,
      `${dataspaceRuntime.consumer.portalBaseUrl.replace(/\/$/, "")}/ontologies`,
    );
    await shellPage.assertNoGateway403("Ontologies page");
    await shellPage.assertNoServerErrorBanner("Ontologies page");
    await expect(page.getByRole("link", { name: /Create ontology/i }).first()).toBeVisible();
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
    await captureStep(page, "03-ontology-hub-inesdata-ontologies");

    report.fatalErrorResponses = report.errorResponses;
    expect(
      report.fatalErrorResponses,
      `Ontology Hub/INESData read-only integration returned fatal errors: ${JSON.stringify(report.fatalErrorResponses)}`,
    ).toHaveLength(0);
  } finally {
    const browserDiagnosticsSnapshot = browserDiagnostics.snapshot();
    browserDiagnostics.dispose();
    await attachJson("ontology-hub-inesdata-browser-diagnostics", browserDiagnosticsSnapshot);
    await attachJson("ontology-hub-inesdata-report", {
      ...report,
      finishedAt: new Date().toISOString(),
      browserDiagnostics: {
        eventCount: browserDiagnosticsSnapshot.eventCount,
        droppedEventCount: browserDiagnosticsSnapshot.droppedEventCount,
      },
    });
  }
});
