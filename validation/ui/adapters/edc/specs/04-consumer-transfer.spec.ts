import { KeycloakLoginPage } from "../../../components/auth/keycloak-login.page";
import {
  bootstrapProviderNegotiationArtifacts,
  bootstrapConsumerNegotiation,
  bootstrapConsumerTransfer,
  fetchConsumerCatalogResponse,
} from "../../../shared/utils/provider-bootstrap";
import { test, expect } from "../../../shared/fixtures/dataspace.fixture";
import { EdcCatalogPage } from "../components/edc-catalog.page";
import { EdcContractsPage } from "../components/edc-contracts.page";
import { EdcDashboardPage } from "../components/edc-dashboard.page";
import { EdcTransferHistoryPage } from "../components/edc-transfer-history.page";

type TransferReport = {
  startedAt: string;
  providerConnector: string;
  consumerConnector: string;
  assetId: string;
  transferObjectName: string;
  selectedTransferType?: string;
  finalTransferState?: string;
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

test("04 edc transfer: consumer starts a transfer and sees it in history", async ({
  page,
  request,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  const suffix = `${Date.now()}`;
  const assetId = `qa-ui-edc-transfer-${suffix}`;
  const objectName = `playwright-edc-${suffix}.json`;
  const report: TransferReport = {
    startedAt: new Date().toISOString(),
    providerConnector: dataspaceRuntime.provider.connectorName,
    consumerConnector: dataspaceRuntime.consumer.connectorName,
    assetId,
    transferObjectName: objectName,
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
  const transferHistoryPage = new EdcTransferHistoryPage(page);

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
    await attachJson("edc-transfer-bootstrap", report.providerBootstrap);

    await loginPage.open(dataspaceRuntime.consumer.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await dashboardPage.expectShellReady();
    await captureStep(page, "01-edc-transfer-after-login");

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
    await captureStep(page, "02-edc-transfer-catalog");

    report.consumerNegotiation = await bootstrapConsumerNegotiation(
      request,
      dataspaceRuntime,
      assetId,
      dataspaceRuntime.provider.protocolBaseUrl,
      dataspaceRuntime.provider.connectorName,
    );
    await dashboardPage.navigateToSection("Contracts", "/edc-dashboard/contracts");
    await captureStep(page, "03-edc-transfer-contracts-after-negotiation");

    await contractsPage.expectReady();
    await contractsPage.waitForContractVisible(assetId);
    const transferBootstrap = await bootstrapConsumerTransfer(
      request,
      dataspaceRuntime,
      assetId,
      report.consumerNegotiation.agreementId,
      dataspaceRuntime.provider.protocolBaseUrl,
    );
    report.selectedTransferType = transferBootstrap.transferType;
    await captureStep(page, "04-edc-transfer-started");

    await transferHistoryPage.goto(dataspaceRuntime.consumer.portalBaseUrl);
    await dashboardPage.expectNoServerErrorBanner("EDC transfer history");
    await transferHistoryPage.expectReady();
    report.finalTransferState = await transferHistoryPage.waitForSuccessfulTransfer(assetId, 120_000);
    await captureStep(page, "05-edc-transfer-history");

    expect(report.selectedTransferType, "No transfer type was selected").toBeTruthy();
    expect(report.finalTransferState, "No final EDC transfer state was detected").toBeTruthy();
    expect(
      report.errorResponses,
      `EDC dashboard proxy returned errors during transfer: ${JSON.stringify(report.errorResponses)}`,
    ).toHaveLength(0);
  } finally {
    await attachJson("edc-transfer-report", {
      ...report,
      finishedAt: new Date().toISOString(),
    });
  }
});
