import { KeycloakLoginPage } from "../../../shared/components/auth/keycloak-login.page";
import { test, expect } from "../../../shared/fixtures/dataspace.fixture";
import {
  bootstrapProviderNegotiationArtifacts,
  fetchConsumerCatalogResponse,
  probeConsumerCatalogDatasetReadiness,
} from "../../../shared/utils/provider-bootstrap";
import { EdcCatalogPage } from "../components/edc-catalog.page";
import { EdcDashboardPage } from "../components/edc-dashboard.page";

type CatalogReport = {
  startedAt: string;
  providerConnector: string;
  consumerConnector: string;
  assetId: string;
  providerBootstrap?: {
    assetId: string;
    policyId: string;
    contractDefinitionId: string;
  };
  errorResponses: Array<{ url: string; status: number }>;
};

test("04 edc consumer catalog: listing without access errors", async ({
  page,
  request,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  const suffix = `${Date.now()}`;
  const assetId = `qa-ui-edc-catalog-${suffix}`;
  const report: CatalogReport = {
    startedAt: new Date().toISOString(),
    providerConnector: dataspaceRuntime.provider.connectorName,
    consumerConnector: dataspaceRuntime.consumer.connectorName,
    assetId,
    errorResponses: [],
  };

  const loginPage = new KeycloakLoginPage(page, {
    portalUser: dataspaceRuntime.consumer.username,
    portalPassword: dataspaceRuntime.consumer.password,
    skipLogin: false,
  });
  const dashboardPage = new EdcDashboardPage(page);
  const catalogPage = new EdcCatalogPage(page);

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
    );
    await attachJson("edc-consumer-catalog-bootstrap", report.providerBootstrap);
    await attachJson(
      "edc-consumer-catalog-api-readiness",
      await probeConsumerCatalogDatasetReadiness(request, dataspaceRuntime, assetId),
    );
    const catalogResponse = await fetchConsumerCatalogResponse(
      request,
      dataspaceRuntime,
      dataspaceRuntime.provider.protocolBaseUrl,
      dataspaceRuntime.provider.connectorName,
    );

    await loginPage.open(dataspaceRuntime.consumer.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await dashboardPage.expectShellReady();
    await captureStep(page, "01-edc-catalog-after-login");

    await catalogPage.goto(dataspaceRuntime.consumer.portalBaseUrl);
    await dashboardPage.expectNoServerErrorBanner("EDC consumer catalog");
    await catalogPage.expectReady();
    await catalogPage.waitForAssetVisible(
      dataspaceRuntime.provider.protocolBaseUrl,
      assetId,
      120_000,
      dataspaceRuntime.provider.connectorName,
      catalogResponse,
    );
    await captureStep(page, "02-edc-catalog-list");

    expect(
      report.errorResponses,
      `EDC dashboard proxy returned errors during catalog validation: ${JSON.stringify(report.errorResponses)}`,
    ).toHaveLength(0);
  } finally {
    await attachJson("edc-consumer-catalog-report", {
      ...report,
      finishedAt: new Date().toISOString(),
    });
  }
});
