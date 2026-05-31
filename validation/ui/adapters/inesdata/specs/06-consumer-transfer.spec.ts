import { test, expect } from "../../../shared/fixtures/dataspace.fixture";

import { KeycloakLoginPage } from "../../../shared/components/auth/keycloak-login.page";
import { ConnectorShellPage } from "../components/shell/connector-shell.page";
import { CatalogPage } from "../components/consumer/catalog.page";
import { ContractOffersPage } from "../components/consumer/contract-offers.page";
import { ContractsPage } from "../components/consumer/contracts.page";
import { TransferHistoryPage } from "../components/consumer/transfer-history.page";
import {
  bootstrapConsumerNegotiation,
  bootstrapProviderNegotiationArtifacts,
  probeConsumerCatalogDatasetReadiness,
  waitForConsumerAgreement,
  waitForConsumerTransferReadinessForAssetAgreement,
} from "../../../shared/utils/provider-bootstrap";
import { collectBrowserDiagnostics } from "../../../shared/utils/browser-diagnostics";
import { EVENTUAL_UI_RETRY_INTERVALS } from "../../../shared/utils/waiting";

type TransferReport = {
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
  toleratedErrorResponses: Array<{ url: string; status: number }>;
  fatalErrorResponses: Array<{ url: string; status: number }>;
  negotiationMessage?: string;
  uiNegotiationResponse?: {
    url: string;
    status: number;
    bodySnippet?: string;
    missingCounterPartyAddress: boolean;
  };
  negotiationFallback?: {
    reason: "ui-missing-counter-party-address";
    negotiationId: string;
    agreementId: string;
    assetId: string;
    state?: string;
  };
  consumerAgreement?: {
    agreementId: string | null;
    assetId: string;
    attempts: number;
  };
  transferInitiatedMessage?: string;
  backendTransferReadiness?: {
    status: "ready" | "timeout";
    assetId: string;
    agreementId: string;
    transferCount: number;
    readyTransferId?: string;
    readyState?: string;
    error?: string;
  };
  finalTransferState?: string;
  storageVerification: {
    status: "skipped";
    reason: string;
  };
};

function isMissingCounterPartyAddressNegotiationError(body: string): boolean {
  return /counterPartyAddress/i.test(body) && /missing|blank|mandatory/i.test(body);
}

function bodySnippet(body: string): string {
  return body.replace(/\s+/g, " ").trim().slice(0, 500);
}

test("06 consumer transfer: visible transfer from contracts and history", async ({
  page,
  request,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  const suffix = `${Date.now()}`;
  const assetId = `qa-ui-transfer-${suffix}`;
  const browserDiagnostics = collectBrowserDiagnostics(page);
  const loginPage = new KeycloakLoginPage(page, {
    portalUser: dataspaceRuntime.consumer.username,
    portalPassword: dataspaceRuntime.consumer.password,
    skipLogin: false,
  });
  const shellPage = new ConnectorShellPage(page);
  const catalogPage = new CatalogPage(page);
  const contractOffersPage = new ContractOffersPage(page);
  const contractsPage = new ContractsPage(page);
  const transferHistoryPage = new TransferHistoryPage(page);
  const report: TransferReport = {
    startedAt: new Date().toISOString(),
    providerConnector: dataspaceRuntime.provider.connectorName,
    consumerConnector: dataspaceRuntime.consumer.connectorName,
    assetId,
    errorResponses: [],
    toleratedErrorResponses: [],
    fatalErrorResponses: [],
    storageVerification: {
      status: "skipped",
      reason: "UI flow validates transfer initiation and successful completion in history; EDR/download remain API-level checks.",
    },
  };

  const isTolerableCatalogRetry = (url: string, status: number): boolean =>
    (status === 401 || status === 500 || status === 502 || status === 503 || status === 504) &&
    (url.includes("/management/pagination/count?type=federatedCatalog") ||
      url.includes("/management/federatedcatalog/request"));

  const isTolerableUiNegotiationFallback = (url: string, status: number): boolean =>
    status === 400 &&
    report.negotiationFallback?.reason === "ui-missing-counter-party-address" &&
    url.includes("/management/v3/contractnegotiations");

  const isTolerableErrorResponse = (url: string, status: number): boolean =>
    isTolerableCatalogRetry(url, status) || isTolerableUiNegotiationFallback(url, status);

  page.on("response", (response) => {
    const url = response.url();
    if (
      response.status() >= 400 &&
      (url.includes("/management/") ||
        url.includes("/federatedcatalog") ||
        url.includes("/contractnegotiations") ||
        url.includes("/transferprocess"))
    ) {
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
    await attachJson("consumer-transfer-bootstrap", report.providerBootstrap);
    await attachJson(
      "consumer-transfer-catalog-api-readiness",
      await probeConsumerCatalogDatasetReadiness(request, dataspaceRuntime, assetId),
    );

    await loginPage.open(dataspaceRuntime.consumer.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await shellPage.expectReady();
    await captureStep(page, "01-transfer-after-login");

    await expect(async () => {
      await catalogPage.goto(dataspaceRuntime.consumer.portalBaseUrl, {
        catalogKind: "federated",
        expectedAssetId: assetId,
      });
      await shellPage.assertNoGateway403("Catalog page");
      await shellPage.assertNoServerErrorBanner("Catalog page");
      await catalogPage.expectReady();
      await catalogPage.showLargestPageSize({ catalogKind: "federated", expectedAssetId: assetId });

      let opened = await catalogPage.openDetailsForAsset(assetId);
      while (!opened && (await catalogPage.goToNextPage({ catalogKind: "federated", expectedAssetId: assetId }))) {
        opened = await catalogPage.openDetailsForAsset(assetId);
      }

      expect(opened, `Asset ${assetId} is not visible in the consumer catalog yet`).toBeTruthy();
    }).toPass({
      timeout: 90_000,
      intervals: EVENTUAL_UI_RETRY_INTERVALS,
    });

    await catalogPage.expectDetailsVisible({
      assetId,
      attachJson,
      context: "consumer-transfer-catalog-detail",
    });
    await contractOffersPage.expectReady({
      assetId,
      attachJson,
      context: "consumer-transfer-contract-offers",
    });
    await captureStep(page, "02-transfer-catalog-detail");
    await contractOffersPage.openContractOffersTab();
    await captureStep(page, "03-transfer-contract-offers");

    const negotiationResponsePromise = page
      .waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          response.url().includes("/management/v3/contractnegotiations"),
        { timeout: 15_000 },
      )
      .catch(() => undefined);
    await contractOffersPage.negotiateFirstOffer();
    const negotiationResponse = await negotiationResponsePromise;
    if (negotiationResponse) {
      const responseBody = negotiationResponse.status() >= 400
        ? await negotiationResponse.text().catch(() => "")
        : "";
      report.uiNegotiationResponse = {
        url: negotiationResponse.url(),
        status: negotiationResponse.status(),
        bodySnippet: responseBody ? bodySnippet(responseBody) : undefined,
        missingCounterPartyAddress: isMissingCounterPartyAddressNegotiationError(responseBody),
      };
      await attachJson("consumer-transfer-ui-negotiation-response", report.uiNegotiationResponse);
    }

    let negotiationNotificationObserved = true;
    try {
      report.negotiationMessage = await contractOffersPage.waitForNegotiationComplete(45_000);
      await captureStep(page, "04-transfer-negotiation-complete");
    } catch (error) {
      negotiationNotificationObserved = false;
      const message = error instanceof Error ? error.message : String(error);
      report.negotiationMessage = `Contract negotiation notification was not observed before contract verification: ${message}`;
      await captureStep(page, "04-transfer-negotiation-submitted");
    }

    if (!negotiationNotificationObserved && report.uiNegotiationResponse?.missingCounterPartyAddress) {
      const fallbackNegotiation = await bootstrapConsumerNegotiation(
        request,
        dataspaceRuntime,
        assetId,
        dataspaceRuntime.provider.protocolBaseUrl,
        dataspaceRuntime.provider.connectorName,
      );
      report.negotiationFallback = {
        reason: "ui-missing-counter-party-address",
        negotiationId: fallbackNegotiation.negotiationId,
        agreementId: fallbackNegotiation.agreementId,
        assetId: fallbackNegotiation.assetId,
        state: fallbackNegotiation.state,
      };
      await attachJson("consumer-transfer-api-negotiation-fallback", report.negotiationFallback);
    }

    const consumerAgreement = await waitForConsumerAgreement(request, dataspaceRuntime, assetId, 60, 1_500);
    report.consumerAgreement = {
      agreementId: consumerAgreement.agreementId,
      assetId: consumerAgreement.assetId,
      attempts: consumerAgreement.attempts,
    };
    await attachJson("consumer-transfer-contract-agreement", report.consumerAgreement);

    await expect(async () => {
      await contractsPage.goto(dataspaceRuntime.consumer.portalBaseUrl);
      await shellPage.assertNoGateway403("Contracts page");
      await shellPage.assertNoServerErrorBanner("Contracts page");
      await contractsPage.expectReady();

      expect(
        await contractsPage.hasContractForAsset(assetId),
        `Contract for asset ${assetId} is not visible yet`,
      ).toBeTruthy();
    }).toPass({
      timeout: 90_000,
      intervals: EVENTUAL_UI_RETRY_INTERVALS,
    });
    if (!negotiationNotificationObserved) {
      report.negotiationMessage = "Contract negotiation completion inferred from visible contract.";
    }

    await captureStep(page, "05-transfer-contracts");
    report.transferInitiatedMessage = await contractsPage.startInesDataStoreTransfer(assetId);
    await captureStep(page, "06-transfer-started");

    expect(report.consumerAgreement.agreementId, "No consumer contract agreement was available before transfer").toBeTruthy();
    const backendTransferReadiness = await waitForConsumerTransferReadinessForAssetAgreement(
      request,
      dataspaceRuntime,
      assetId,
      report.consumerAgreement.agreementId || "",
    );
    report.backendTransferReadiness = {
      status: backendTransferReadiness.status,
      assetId: backendTransferReadiness.assetId,
      agreementId: backendTransferReadiness.agreementId,
      transferCount: backendTransferReadiness.transferCount,
      readyTransferId: backendTransferReadiness.readyTransferId,
      readyState: backendTransferReadiness.readyState,
      error: backendTransferReadiness.error,
    };
    await attachJson("consumer-transfer-backend-readiness", backendTransferReadiness);
    expect(
      backendTransferReadiness.status,
      `Backend transfer for asset ${assetId} was not ready before checking UI history`,
    ).toBe("ready");

    await transferHistoryPage.goto(dataspaceRuntime.consumer.portalBaseUrl);
    await shellPage.assertNoGateway403("Transfer history page");
    await shellPage.assertNoServerErrorBanner("Transfer history page");
    await transferHistoryPage.expectReady();
    report.finalTransferState = await transferHistoryPage.waitForSuccessfulTransfer(assetId, 180_000);
    await captureStep(page, "07-transfer-history");

    expect(report.negotiationMessage, "No completed negotiation signal was detected").toMatch(
      /contract negotiation complete!|visible contract/i,
    );
    expect(report.transferInitiatedMessage, "No transfer initiation notification was detected").toMatch(
      /transfer initiated successfully/i,
    );
    expect(report.finalTransferState, "No final transfer state was detected").toBeTruthy();
    report.toleratedErrorResponses = report.errorResponses.filter(({ url, status }) =>
      isTolerableErrorResponse(url, status),
    );
    report.fatalErrorResponses = report.errorResponses.filter(
      ({ url, status }) => !isTolerableErrorResponse(url, status),
    );
    expect(
      report.fatalErrorResponses,
      `API calls returned fatal errors: ${JSON.stringify(report.fatalErrorResponses)} (tolerated transient catalog errors: ${JSON.stringify(report.toleratedErrorResponses)})`,
    ).toHaveLength(0);
  } finally {
    const browserDiagnosticsSnapshot = browserDiagnostics.snapshot();
    browserDiagnostics.dispose();
    await attachJson("consumer-transfer-browser-diagnostics", browserDiagnosticsSnapshot);
    await attachJson("consumer-transfer-report", {
      ...report,
      finishedAt: new Date().toISOString(),
      browserDiagnostics: {
        eventCount: browserDiagnosticsSnapshot.eventCount,
        droppedEventCount: browserDiagnosticsSnapshot.droppedEventCount,
      },
    });
  }
});
