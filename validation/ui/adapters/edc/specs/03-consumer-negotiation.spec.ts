import { KeycloakLoginPage } from "../../../components/auth/keycloak-login.page";
import {
  bootstrapProviderNegotiationArtifacts,
  bootstrapConsumerNegotiation,
  fetchConsumerCatalogResponse,
} from "../../../shared/utils/provider-bootstrap";
import { test, expect } from "../../../shared/fixtures/dataspace.fixture";
import { EdcCatalogPage } from "../components/edc-catalog.page";
import { EdcContractsPage } from "../components/edc-contracts.page";
import { EdcDashboardPage } from "../components/edc-dashboard.page";

type NegotiationReport = {
  startedAt: string;
  providerConnector: string;
  consumerConnector: string;
  assetId: string;
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
  errorResponses: Array<{ url: string; status: number }>;
};

test("03 edc negotiation: consumer negotiates a contract from catalog", async ({
  page,
  request,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  const suffix = `${Date.now()}`;
  const assetId = `qa-ui-edc-negotiation-${suffix}`;
  const report: NegotiationReport = {
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
    );
    const catalogResponse = await fetchConsumerCatalogResponse(
      request,
      dataspaceRuntime,
      dataspaceRuntime.provider.protocolBaseUrl,
      dataspaceRuntime.provider.connectorName,
    );
    await attachJson("edc-negotiation-bootstrap", report.providerBootstrap);

    await loginPage.open(dataspaceRuntime.consumer.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await dashboardPage.expectShellReady();
    await captureStep(page, "01-edc-negotiation-after-login");

    await catalogPage.goto(dataspaceRuntime.consumer.portalBaseUrl);
    await dashboardPage.expectNoServerErrorBanner("EDC catalog");
    await catalogPage.expectReady();
    await catalogPage.waitForAssetVisible(
      dataspaceRuntime.provider.protocolBaseUrl,
      assetId,
      90_000,
      dataspaceRuntime.provider.connectorName,
      catalogResponse,
    );
    await captureStep(page, "02-edc-negotiation-catalog");

    report.consumerNegotiation = await bootstrapConsumerNegotiation(
      request,
      dataspaceRuntime,
      assetId,
      dataspaceRuntime.provider.protocolBaseUrl,
      dataspaceRuntime.provider.connectorName,
    );
    await dashboardPage.navigateToSection("Contracts", "/edc-dashboard/contracts");
    await captureStep(page, "03-edc-negotiation-contracts");

    await dashboardPage.expectNoServerErrorBanner("EDC contracts");
    await contractsPage.expectReady();
    await contractsPage.waitForContractVisible(assetId, 90_000);

    expect(
      report.errorResponses,
      `EDC dashboard proxy returned errors during negotiation: ${JSON.stringify(report.errorResponses)}`,
    ).toHaveLength(0);
  } finally {
    await attachJson("edc-negotiation-report", {
      ...report,
      finishedAt: new Date().toISOString(),
    });
  }
});
