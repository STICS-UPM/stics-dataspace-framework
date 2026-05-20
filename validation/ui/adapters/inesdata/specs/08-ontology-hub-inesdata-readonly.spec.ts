import { APIResponse, Page, Response } from "@playwright/test";

import { test, expect } from "../../../shared/fixtures/dataspace.fixture";

import { KeycloakLoginPage } from "../../../shared/components/auth/keycloak-login.page";
import { ConnectorShellPage } from "../components/shell/connector-shell.page";
import { collectBrowserDiagnostics } from "../../../shared/utils/browser-diagnostics";

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
  "Set UI_ONTOLOGY_HUB_INESDATA_DEMO=1 or run Level 6 with the INESData adapter to validate Ontology Hub read-only integration from the INESData UI.",
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

function isRecoverableIntegrationStatus(status: number): boolean {
  return [401, 403, 502, 503, 504].includes(status);
}

async function waitForSuccessfulIntegrationResponse(
  page: Page,
  predicate: (response: Response) => boolean,
  label: string,
  options: {
    timeoutMs?: number;
    recover?: () => Promise<void>;
  } = {},
): Promise<Response> {
  const timeoutMs = options.timeoutMs ?? 45_000;
  const deadline = Date.now() + timeoutMs;
  let lastResponse: Response | null = null;
  let recovered = false;

  while (Date.now() < deadline) {
    const response = await page
      .waitForResponse(predicate, {
        timeout: Math.min(10_000, Math.max(1000, deadline - Date.now())),
      })
      .catch(() => null);

    if (!response) {
      if (!recovered && options.recover) {
        recovered = true;
        await options.recover();
      }
      continue;
    }

    lastResponse = response;
    if (response.status() === 200) {
      return response;
    }

    if (isRecoverableIntegrationStatus(response.status()) && !recovered && options.recover) {
      recovered = true;
      await options.recover();
      continue;
    }

    if (!isRecoverableIntegrationStatus(response.status())) {
      return response;
    }
  }

  if (lastResponse) {
    return lastResponse;
  }
  throw new Error(`${label} did not emit a response before ${timeoutMs}ms.`);
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

    const vocabularyResponsePromise = waitForSuccessfulIntegrationResponse(
      page,
      (response) => response.url().includes("/connector-vocabularies/request"),
      "Shared vocabulary API",
      {
        recover: async () => {
          await page.reload({ waitUntil: "domcontentloaded" }).catch(() => {});
        },
      },
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

    const ontologyHubResponsePromise = waitForSuccessfulIntegrationResponse(
      page,
      (response) => response.url().includes("/dataset/api/v2/vocabulary/list"),
      "Ontology Hub vocabulary list",
      {
        recover: async () => {
          await page.reload({ waitUntil: "domcontentloaded" }).catch(() => {});
        },
      },
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

    report.fatalErrorResponses = report.errorResponses.filter(
      (errorResponse) => !isRecoverableIntegrationStatus(errorResponse.status),
    );
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
