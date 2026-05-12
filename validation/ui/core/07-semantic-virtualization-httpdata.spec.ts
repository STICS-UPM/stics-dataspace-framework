import { test, expect } from "../shared/fixtures/dataspace.fixture";

import { KeycloakLoginPage } from "../components/auth/keycloak-login.page";
import { ConnectorShellPage } from "../components/shell/connector-shell.page";
import { CatalogPage } from "../components/consumer/catalog.page";
import { ContractOffersPage } from "../components/consumer/contract-offers.page";
import { collectBrowserDiagnostics } from "../shared/utils/browser-diagnostics";
import {
  bootstrapProviderNegotiationArtifacts,
  cleanupProviderValidationArtifacts,
  probeConsumerCatalogDatasetReadiness,
} from "../shared/utils/provider-bootstrap";
import { EVENTUAL_UI_RETRY_INTERVALS } from "../shared/utils/waiting";

type SemanticVirtualizationUiReport = {
  startedAt: string;
  providerConnector: string;
  consumerConnector: string;
  assetId: string;
  semanticDataUrl: string;
  sourceObjectName: string;
  linkedCases: string[];
  providerBootstrap?: {
    assetId: string;
    policyId: string;
    contractDefinitionId: string;
  };
  errorResponses: Array<{ url: string; status: number }>;
  toleratedErrorResponses: Array<{ url: string; status: number }>;
  fatalErrorResponses: Array<{ url: string; status: number }>;
  negotiationMessage?: string;
};

const DEFAULT_QUERY_PATH =
  "/?query=SELECT%20*%20WHERE%20%7B%20%3Fs%20%3Fp%20%3Fo%20.%20%7D%20LIMIT%201";

test.skip(
  process.env.UI_SEMANTIC_VIRTUALIZATION_HTTPDATA_DEMO !== "1",
  "Opt-in demo: set UI_SEMANTIC_VIRTUALIZATION_HTTPDATA_DEMO=1 to validate the Semantic Virtualization HttpData asset from the INESData UI.",
);

function normalizePath(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return DEFAULT_QUERY_PATH;
  }
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}

function semanticVirtualizationDataUrl(dataspace: string): string {
  const explicit = (process.env.UI_SEMANTIC_VIRTUALIZATION_DATA_URL || "").trim();
  if (explicit) {
    return explicit;
  }

  const namespace = (process.env.UI_COMPONENTS_NAMESPACE || process.env.COMPONENTS_NAMESPACE || "components").trim();
  const queryPath = normalizePath(
    process.env.UI_SEMANTIC_VIRTUALIZATION_QUERY_PATH ||
      process.env.SEMANTIC_VIRTUALIZATION_QUERY_PATH ||
      DEFAULT_QUERY_PATH,
  );
  return `http://${dataspace}-semantic-virtualization.${namespace}.svc.cluster.local:8000${queryPath}`;
}

function semanticVirtualizationCatalogCleanupEnabled(): boolean {
  return process.env.UI_SEMANTIC_VIRTUALIZATION_CATALOG_CLEANUP === "1";
}

test("07 semantic virtualization HttpData: visible discovery and negotiation from INESData UI", async ({
  page,
  request,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  test.skip(dataspaceRuntime.adapter !== "inesdata", "This demo validates the INESData connector UI path.");

  const suffix = `${Date.now()}`;
  const assetId = `qa-ui-sv-httpdata-${suffix}`;
  const sourceObjectName = "gtfs_bench_official_mini_materialized.ttl";
  const semanticDataUrl = semanticVirtualizationDataUrl(dataspaceRuntime.dataspace);
  const browserDiagnostics = collectBrowserDiagnostics(page);
  const loginPage = new KeycloakLoginPage(page, {
    portalUser: dataspaceRuntime.consumer.username,
    portalPassword: dataspaceRuntime.consumer.password,
    skipLogin: false,
  });
  const shellPage = new ConnectorShellPage(page);
  const catalogPage = new CatalogPage(page);
  const contractOffersPage = new ContractOffersPage(page);
  const report: SemanticVirtualizationUiReport = {
    startedAt: new Date().toISOString(),
    providerConnector: dataspaceRuntime.provider.connectorName,
    consumerConnector: dataspaceRuntime.consumer.connectorName,
    assetId,
    semanticDataUrl,
    sourceObjectName,
    linkedCases: ["INT-VS-DS-01", "INT-VS-DS-02", "PT5-VS-02", "PT5-VS-11", "SV-GTFS-BENCH-03", "SV-GTFS-BENCH-04"],
    errorResponses: [],
    toleratedErrorResponses: [],
    fatalErrorResponses: [],
  };

  const isTolerableCatalogRetry = (url: string, status: number): boolean =>
    (status === 401 || status === 503) &&
    (url.includes("/management/pagination/count?type=federatedCatalog") ||
      url.includes("/management/federatedcatalog/request"));

  page.on("response", (response) => {
    const url = response.url();
    if (
      response.status() >= 400 &&
      (url.includes("/management/") ||
        url.includes("/federatedcatalog") ||
        url.includes("/contractnegotiations"))
    ) {
      report.errorResponses.push({ url, status: response.status() });
    }
  });

  try {
    if (semanticVirtualizationCatalogCleanupEnabled()) {
      await attachJson(
        "sv-httpdata-ui-catalog-cleanup",
        await cleanupProviderValidationArtifacts(request, dataspaceRuntime, {
          contractdefinitions: ["contract-ui-", "qa-ui-contract-definition-"],
          policydefinitions: ["policy-ui-", "qa-ui-policy-", "qa-ui-contract-policy-"],
          assets: [
            "asset-e2e-",
            "qa-ui-asset-",
            "qa-ui-catalog-",
            "qa-ui-negotiation-",
            "qa-ui-sv-httpdata-",
            "qa-ui-transfer-",
          ],
        }),
      );
    }

    report.providerBootstrap = await bootstrapProviderNegotiationArtifacts(
      request,
      dataspaceRuntime,
      assetId,
      suffix,
      {
        sourceObjectName,
        name: `GTFS-Bench official mini RDF via Semantic Virtualization ${suffix}`,
        version: "official-mini-v1",
        shortDescription: "Official-derived GTFS-Bench RDF output exposed as HttpData for UI demo validation",
        description:
          "Semantic Virtualization RDF/Turtle output derived from the official GTFS-Bench mini fixture and exposed through INESData as a contractual HttpData asset.",
        assetType: "semantic-virtualization-gtfs-bench-rdf-output",
        keywords: [
          "validation",
          "semantic-virtualization",
          "HttpData",
          "GTFS-Madrid-Bench",
          "gtfs-bench",
          "official-derived",
          "mobility",
          "rdf",
          "A5.2",
          "SV-GTFS-BENCH-04",
        ],
        properties: {
          "daimo:sourceDataset": "GTFS-Bench-official-mini",
          "daimo:sourceRepository": "https://github.com/oeg-upm/gtfs-bench",
          "daimo:domain": "mobility",
          "daimo:task": "semantic-virtualization-gtfs-bench-official-materialization",
        },
        dataAddress: {
          type: "HttpData",
          baseUrl: semanticDataUrl,
          name: sourceObjectName,
        },
      },
    );
    await attachJson("sv-httpdata-ui-bootstrap", report.providerBootstrap);
    await attachJson(
      "sv-httpdata-ui-catalog-api-readiness",
      await probeConsumerCatalogDatasetReadiness(request, dataspaceRuntime, assetId),
    );

    await loginPage.open(dataspaceRuntime.consumer.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await shellPage.expectReady();
    await captureStep(page, "01-sv-httpdata-after-login");

    await expect(async () => {
      await catalogPage.goto(dataspaceRuntime.consumer.portalBaseUrl);
      await shellPage.assertNoGateway403("Semantic Virtualization catalog page");
      await shellPage.assertNoServerErrorBanner("Semantic Virtualization catalog page");
      await catalogPage.expectReady();
      await catalogPage.showLargestPageSize();
      await expect(page.getByText(assetId, { exact: true })).toBeVisible({ timeout: 20_000 });

      let opened = await catalogPage.openDetailsForAsset(assetId);
      while (!opened && (await catalogPage.goToNextPage())) {
        opened = await catalogPage.openDetailsForAsset(assetId);
      }

      expect(
        opened,
        `Semantic Virtualization HttpData asset ${assetId} is not visible in the consumer catalog yet`,
      ).toBeTruthy();
    }).toPass({
      timeout: 90_000,
      intervals: EVENTUAL_UI_RETRY_INTERVALS,
    });

    await captureStep(page, "02-sv-httpdata-catalog-detail");
    await catalogPage.expectDetailsVisible({
      assetId,
      attachJson,
      context: "sv-httpdata-catalog-detail",
    });
    await contractOffersPage.expectReady({
      assetId,
      attachJson,
      context: "sv-httpdata-contract-offers",
    });
    await contractOffersPage.openContractOffersTab();
    await captureStep(page, "03-sv-httpdata-contract-offers");

    await contractOffersPage.negotiateFirstOffer();
    report.negotiationMessage = await contractOffersPage.waitForNegotiationComplete(45_000);
    await captureStep(page, "04-sv-httpdata-negotiation-complete");

    expect(report.negotiationMessage, "No completed negotiation notification was detected").toMatch(
      /contract negotiation complete!/i,
    );
    report.toleratedErrorResponses = report.errorResponses.filter(({ url, status }) =>
      isTolerableCatalogRetry(url, status),
    );
    report.fatalErrorResponses = report.errorResponses.filter(
      ({ url, status }) => !isTolerableCatalogRetry(url, status),
    );
    expect(
      report.fatalErrorResponses,
      `API calls returned fatal errors: ${JSON.stringify(report.fatalErrorResponses)} (tolerated transient catalog errors: ${JSON.stringify(report.toleratedErrorResponses)})`,
    ).toHaveLength(0);
  } finally {
    const browserDiagnosticsSnapshot = browserDiagnostics.snapshot();
    browserDiagnostics.dispose();
    await attachJson("sv-httpdata-ui-browser-diagnostics", browserDiagnosticsSnapshot);
    await attachJson("sv-httpdata-ui-report", {
      ...report,
      finishedAt: new Date().toISOString(),
      browserDiagnostics: {
        eventCount: browserDiagnosticsSnapshot.eventCount,
        droppedEventCount: browserDiagnosticsSnapshot.droppedEventCount,
      },
    });
  }
});
