import { KeycloakLoginPage } from "../../../shared/components/auth/keycloak-login.page";
import { test, expect } from "../../../shared/fixtures/dataspace.fixture";
import {
  bootstrapConsumerNegotiation,
  bootstrapProviderNegotiationArtifacts,
  fetchConsumerCatalogResponse,
  probeConsumerCatalogDatasetReadiness,
  waitForConsumerAgreement,
} from "../../../shared/utils/provider-bootstrap";
import { EdcCatalogPage } from "../components/edc-catalog.page";
import { EdcContractsPage } from "../components/edc-contracts.page";
import { EdcDashboardPage } from "../components/edc-dashboard.page";
import {
  semanticVirtualizationAssetOptions,
  semanticVirtualizationDataUrl,
} from "../utils/edc-component-fixtures";

type SemanticVirtualizationEdcReport = {
  startedAt: string;
  providerConnector: string;
  consumerConnector: string;
  assetId: string;
  semanticDataUrl: string;
  linkedCases: string[];
  providerBootstrap?: {
    assetId: string;
    policyId: string;
    contractDefinitionId: string;
  };
  consumerNegotiation?: {
    negotiationId: string;
    agreementId: string;
    assetId: string;
  };
  consumerAgreement?: {
    agreementId: string | null;
    assetId: string;
    attempts: number;
  };
  errorResponses: Array<{ url: string; status: number }>;
};

test.skip(
  process.env.UI_SEMANTIC_VIRTUALIZATION_HTTPDATA_DEMO !== "1",
  "Set UI_SEMANTIC_VIRTUALIZATION_HTTPDATA_DEMO=1 to validate Semantic Virtualization through the EDC dashboard.",
);

test("07 edc semantic virtualization HttpData: visible discovery and negotiation", async ({
  page,
  request,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  test.setTimeout(300_000);

  const suffix = `${Date.now()}`;
  const assetId = `qa-ui-edc-sv-httpdata-${suffix}`;
  const semanticDataUrl = semanticVirtualizationDataUrl(dataspaceRuntime.dataspace);
  const report: SemanticVirtualizationEdcReport = {
    startedAt: new Date().toISOString(),
    providerConnector: dataspaceRuntime.provider.connectorName,
    consumerConnector: dataspaceRuntime.consumer.connectorName,
    assetId,
    semanticDataUrl,
    linkedCases: ["INT-VS-DS-01", "INT-VS-DS-02", "PT5-VS-02", "PT5-VS-11", "SV-GTFS-BENCH-03"],
    errorResponses: [],
  };

  const loginPage = new KeycloakLoginPage(page, {
    portalUser: dataspaceRuntime.consumer.username,
    portalPassword: dataspaceRuntime.consumer.password,
    skipLogin: false,
  });
  const dashboardPage = new EdcDashboardPage(page);
  const catalogPage = new EdcCatalogPage(page);
  const contractsPage = new EdcContractsPage(page);

  page.on("response", (response) => {
    const url = response.url();
    if (response.status() >= 400 && url.includes("/edc-dashboard-api/")) {
      report.errorResponses.push({ url, status: response.status() });
    }
  });

  try {
    report.providerBootstrap = await bootstrapProviderNegotiationArtifacts(
      request,
      dataspaceRuntime,
      assetId,
      suffix,
      semanticVirtualizationAssetOptions({ suffix, semanticDataUrl }),
    );
    await attachJson("edc-sv-httpdata-bootstrap", report.providerBootstrap);
    const readiness = await probeConsumerCatalogDatasetReadiness(request, dataspaceRuntime, assetId);
    await attachJson("edc-sv-httpdata-catalog-api-readiness", readiness);
    expect(
      readiness.status,
      `Semantic Virtualization asset ${assetId} was not ready in the catalog API: ${readiness.error || "unknown error"}`,
    ).toBe("ready");

    const catalogResponse = await fetchConsumerCatalogResponse(
      request,
      dataspaceRuntime,
      dataspaceRuntime.provider.protocolBaseUrl,
      dataspaceRuntime.provider.connectorName,
    );

    await loginPage.open(dataspaceRuntime.consumer.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await dashboardPage.expectShellReady();
    await captureStep(page, "01-edc-sv-httpdata-after-login");

    await catalogPage.goto(dataspaceRuntime.consumer.portalBaseUrl);
    await dashboardPage.expectNoServerErrorBanner("EDC Semantic Virtualization catalog");
    await catalogPage.expectReady();
    await catalogPage.waitForAssetVisible(
      dataspaceRuntime.provider.protocolBaseUrl,
      assetId,
      120_000,
      dataspaceRuntime.provider.connectorName,
      catalogResponse,
    );
    await captureStep(page, "02-edc-sv-httpdata-catalog");

    report.consumerNegotiation = await bootstrapConsumerNegotiation(
      request,
      dataspaceRuntime,
      assetId,
      dataspaceRuntime.provider.protocolBaseUrl,
      dataspaceRuntime.provider.connectorName,
    );
    report.consumerAgreement = await waitForConsumerAgreement(request, dataspaceRuntime, assetId, 40, 1_500);
    await dashboardPage.navigateToSection("Contracts", "/edc-dashboard/contracts");
    await contractsPage.expectReady();
    await contractsPage.waitForContractVisible(assetId, 120_000);
    await captureStep(page, "03-edc-sv-httpdata-contract");

    expect(report.consumerAgreement.agreementId, "No consumer agreement was found").toBeTruthy();
    expect(
      report.errorResponses,
      `EDC dashboard proxy returned errors during Semantic Virtualization validation: ${JSON.stringify(
        report.errorResponses,
      )}`,
    ).toHaveLength(0);
  } finally {
    await attachJson("edc-sv-httpdata-report", {
      ...report,
      finishedAt: new Date().toISOString(),
    });
  }
});
