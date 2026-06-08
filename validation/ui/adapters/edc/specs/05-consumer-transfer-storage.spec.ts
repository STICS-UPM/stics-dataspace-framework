import { KeycloakLoginPage } from "../../../shared/components/auth/keycloak-login.page";
import { MinioBucketBrowserPage } from "../../../shared/components/ops/minio-bucket-browser.page";
import { MinioConsoleLoginPage } from "../../../shared/components/ops/minio-console-login.page";
import {
  bootstrapProviderNegotiationArtifacts,
  bootstrapConsumerNegotiation,
  bootstrapConsumerTransfer,
  fetchConsumerCatalogResponse,
} from "../../../shared/utils/provider-bootstrap";
import { resolveMinioConsoleRuntime } from "../../../shared/utils/minio-console-runtime";
import { waitForMinioObjectStat } from "../../../shared/utils/minio-object-api";
import { test, expect } from "../../../shared/fixtures/dataspace.fixture";
import { EdcCatalogPage } from "../components/edc-catalog.page";
import { EdcContractsPage } from "../components/edc-contracts.page";
import { EdcDashboardPage } from "../components/edc-dashboard.page";

type TransferStorageReport = {
  startedAt: string;
  providerConnector: string;
  consumerConnector: string;
  assetId: string;
  transferObjectName: string;
  finalTransferState?: string;
  selectedTransferType?: string;
  storageValidation?: string;
  consumerBucketName?: string;
  consumerBucketBrowserUrl?: string;
  consumerBucketApiUrl?: string;
  consumerObjectStat?: {
    objectName: string;
    bucketName: string;
    status: number;
    size?: number;
    etag?: string;
    lastModified?: string;
  };
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

test("05 edc transfer storage: validates object storage only for push transfers", async ({
  page,
  request,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  const suffix = `${Date.now()}`;
  const assetId = `qa-ui-edc-storage-${suffix}`;
  const objectName = `playwright-edc-storage-${suffix}.json`;
  const report: TransferStorageReport = {
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
  const minioLoginPage = new MinioConsoleLoginPage(page);
  const bucketBrowserPage = new MinioBucketBrowserPage(page);

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
    await attachJson("edc-transfer-storage-bootstrap", report.providerBootstrap);

    await loginPage.open(dataspaceRuntime.consumer.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await dashboardPage.expectShellReady();
    await captureStep(page, "01-edc-transfer-storage-after-login");

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
    await captureStep(page, "02-edc-transfer-storage-catalog");

    report.consumerNegotiation = await bootstrapConsumerNegotiation(
      request,
      dataspaceRuntime,
      assetId,
      dataspaceRuntime.provider.protocolBaseUrl,
      dataspaceRuntime.provider.connectorName,
    );
    await dashboardPage.navigateToSection("Contracts", "/edc-dashboard/contracts");
    await captureStep(page, "03-edc-transfer-storage-contracts");

    await contractsPage.expectReady();
    await contractsPage.waitForContractVisible(assetId);
    const transferBootstrap = await bootstrapConsumerTransfer(
      request,
      dataspaceRuntime,
      assetId,
      report.consumerNegotiation.agreementId,
      dataspaceRuntime.provider.protocolBaseUrl,
      objectName,
    );
    report.selectedTransferType = transferBootstrap.transferType;
    report.finalTransferState = transferBootstrap.finalState;
    await captureStep(page, "04-edc-transfer-storage-api-state");

    const validatesObjectStorage =
      /push/i.test(report.selectedTransferType || "") &&
      dataspaceRuntime.consumer.transferDestinationType !== "HttpData";

    if (validatesObjectStorage) {
      const minioRuntime = resolveMinioConsoleRuntime({
        consumerExpectedObject: objectName,
      });
      const consumerTarget = minioRuntime.targets.find((item) => item.role === "consumer");
      expect(consumerTarget, "Consumer MinIO target is not configured").toBeTruthy();
      report.consumerBucketName = consumerTarget!.bucketName;
      report.consumerBucketBrowserUrl = consumerTarget!.bucketBrowserUrl;
      report.consumerBucketApiUrl = consumerTarget!.bucketApiUrl;

      report.consumerObjectStat = await waitForMinioObjectStat(consumerTarget!, objectName, 90_000);
      report.storageValidation = "consumer-minio-object-observed-through-s3-api";

      await minioLoginPage.open(consumerTarget!.bucketBrowserUrl);
      await minioLoginPage.loginIfNeeded(consumerTarget!.credentials);
      await bucketBrowserPage.expectReady(consumerTarget!.bucketName);
      await bucketBrowserPage.assertNoBucketPermissionError();
      await captureStep(page, "05-edc-transfer-storage-minio");
    } else {
      report.storageValidation = "not-applicable-for-httpdata-pull";
      await captureStep(page, "05-edc-transfer-storage-not-applicable");
    }

    expect(report.selectedTransferType, "No transfer type was selected").toBeTruthy();
    expect(report.finalTransferState, "No final EDC transfer state was detected").toBeTruthy();
    expect(
      report.errorResponses,
      `EDC dashboard proxy returned errors during transfer/storage validation: ${JSON.stringify(report.errorResponses)}`,
    ).toHaveLength(0);
  } finally {
    await attachJson("edc-transfer-storage-report", {
      ...report,
      finishedAt: new Date().toISOString(),
    });
  }
});
