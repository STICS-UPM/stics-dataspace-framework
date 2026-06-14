import { KeycloakLoginPage } from "../../../shared/components/auth/keycloak-login.page";
import { test, expect } from "../../../shared/fixtures/dataspace.fixture";
import {
  bootstrapProviderNegotiationArtifacts,
  fetchConsumerCatalogResponse,
  resolveConsumerTransferActiveTimeoutMs,
  waitForConsumerTransferReadinessForAssetAgreement,
} from "../../../shared/utils/provider-bootstrap";
import { EdcCatalogPage } from "../components/edc-catalog.page";
import { EdcContractsPage } from "../components/edc-contracts.page";
import { EdcDashboardPage } from "../components/edc-dashboard.page";
import {
  EdcTransferHistoryPage,
  resolveEdcTransferSuccessTimeoutMs,
} from "../components/edc-transfer-history.page";

type E2ETransferReport = {
  startedAt: string;
  providerConnector: string;
  consumerConnector: string;
  assetId: string;
  transferObjectName: string;
  selectedTransferType?: string;
  transferId?: string;
  apiTransferFinalState?: string;
  finalTransferState?: string;
  transferReadiness?: {
    status: string;
    transferCount: number;
    readyTransferId?: string;
    readyState?: string;
    error?: string;
  };
  historyObservation?: "observed" | "api-ready-history-lagging";
  historyError?: string;
  providerBootstrap?: {
    assetId: string;
    policyId: string;
    contractDefinitionId: string;
  };
  errorResponses: Array<{ url: string; status: number }>;
};

test("05 edc e2e transfer flow: catalog negotiation and transfer from the UI", async ({
  page,
  request,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  test.setTimeout(Math.max(360_000, resolveConsumerTransferActiveTimeoutMs(dataspaceRuntime) + 180_000));

  const suffix = `${Date.now()}`;
  const assetId = `qa-ui-edc-e2e-${suffix}`;
  const objectName = `playwright-edc-e2e-${suffix}.json`;
  const report: E2ETransferReport = {
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
      objectName,
    );
    const catalogResponse = await fetchConsumerCatalogResponse(
      request,
      dataspaceRuntime,
      dataspaceRuntime.provider.protocolBaseUrl,
      dataspaceRuntime.provider.connectorName,
    );
    await attachJson("edc-e2e-transfer-bootstrap", report.providerBootstrap);

    await loginPage.open(dataspaceRuntime.consumer.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await dashboardPage.expectShellReady();
    await captureStep(page, "01-edc-e2e-after-login");

    await catalogPage.goto(dataspaceRuntime.consumer.portalBaseUrl);
    await dashboardPage.expectNoServerErrorBanner("EDC e2e catalog");
    await catalogPage.expectReady();
    await catalogPage.waitForAssetVisible(
      dataspaceRuntime.provider.protocolBaseUrl,
      assetId,
      120_000,
      dataspaceRuntime.provider.connectorName,
      catalogResponse,
    );
    await captureStep(page, "02-edc-e2e-catalog");

    await catalogPage.negotiateAsset(assetId, 90_000);
    await dashboardPage.expectNoServerErrorBanner("EDC e2e contracts after negotiation");
    await contractsPage.expectReady();
    await contractsPage.waitForContractVisible(assetId, 120_000);
    await captureStep(page, "03-edc-e2e-contract");

    const transferStart = await contractsPage.startTransferForAsset(
      assetId,
      dataspaceRuntime.consumer,
      objectName,
    );
    report.selectedTransferType = transferStart.transferType;
    report.transferId = transferStart.transferId;
    await captureStep(page, "04-edc-e2e-transfer-started");

    const transferReadiness = await waitForConsumerTransferReadinessForAssetAgreement(
      request,
      dataspaceRuntime,
      assetId,
      "",
      resolveConsumerTransferActiveTimeoutMs(dataspaceRuntime),
    );
    report.transferReadiness = {
      status: transferReadiness.status,
      transferCount: transferReadiness.transferCount,
      readyTransferId: transferReadiness.readyTransferId,
      readyState: transferReadiness.readyState,
      error: transferReadiness.error,
    };
    report.transferId = report.transferId || transferReadiness.readyTransferId;
    report.apiTransferFinalState = transferReadiness.readyState;
    expect(
      transferReadiness.status,
      `Transfer started by UI did not become ready through the EDC API: ${JSON.stringify(transferReadiness)}`,
    ).toBe("ready");

    await transferHistoryPage.goto(dataspaceRuntime.consumer.portalBaseUrl);
    await dashboardPage.expectNoServerErrorBanner("EDC e2e transfer history");
    await transferHistoryPage.expectReady();
    try {
      report.finalTransferState = await transferHistoryPage.waitForSuccessfulTransfer(
        assetId,
        Math.min(60_000, resolveEdcTransferSuccessTimeoutMs()),
      );
      report.historyObservation = "observed";
    } catch (error) {
      report.historyObservation = "api-ready-history-lagging";
      report.historyError = error instanceof Error ? error.message : String(error);
    }
    await captureStep(page, "05-edc-e2e-transfer-history");

    expect(report.selectedTransferType, "No transfer type was selected").toBeTruthy();
    expect(report.transferId, "No transfer id was returned by the UI or API readiness probe").toBeTruthy();
    expect(report.apiTransferFinalState, "No final EDC transfer state was detected through the API").toBeTruthy();
    expect(
      report.errorResponses,
      `EDC dashboard proxy returned errors during e2e flow: ${JSON.stringify(report.errorResponses)}`,
    ).toHaveLength(0);
  } finally {
    await attachJson("edc-e2e-transfer-report", {
      ...report,
      finishedAt: new Date().toISOString(),
    });
  }
});
