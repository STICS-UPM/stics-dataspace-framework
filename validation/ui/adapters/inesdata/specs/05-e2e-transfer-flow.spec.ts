import { test, expect, type Browser, type Page, type TestInfo } from "@playwright/test";
import fs from "fs";
import os from "os";
import path from "path";

import { KeycloakLoginPage } from "../../../shared/components/auth/keycloak-login.page";
import { ConnectorShellPage } from "../components/shell/connector-shell.page";
import { AssetCreatePage } from "../components/provider/asset-create.page";
import { CatalogPage } from "../components/consumer/catalog.page";
import { ContractOffersPage } from "../components/consumer/contract-offers.page";
import { ContractsPage } from "../components/consumer/contracts.page";
import { TransferHistoryPage } from "../components/consumer/transfer-history.page";
import {
  bootstrapProviderContractArtifacts,
  probeConsumerCatalogDatasetReadiness,
} from "../../../shared/utils/provider-bootstrap";
import { resolveDataspacePortalRuntime } from "../../../shared/utils/dataspace-runtime";
import { EVENTUAL_UI_RETRY_INTERVALS } from "../../../shared/utils/waiting";

type UploadFileHandle = {
  path: string;
  sizeBytes: number;
  cleanup: () => void;
};

type ChunkEvent = {
  url: string;
  status: number;
  bodySnippet?: string;
};

type RecordedSession = {
  label: string;
  context: Awaited<ReturnType<Browser["newContext"]>>;
  page: Page;
};

function getUploadFileSizeMb(): number {
  const raw = process.env.PORTAL_TEST_FILE_MB ?? "60";
  const value = Number(raw);
  return Number.isFinite(value) && value > 0 ? value : 60;
}

function createUploadFile(): UploadFileHandle {
  const filePath = path.join(os.tmpdir(), `playwright-transfer-${Date.now()}.bin`);
  const sizeMb = getUploadFileSizeMb();
  fs.writeFileSync(filePath, Buffer.alloc(sizeMb * 1024 * 1024, "A"));
  return {
    path: filePath,
    sizeBytes: fs.statSync(filePath).size,
    cleanup: () => {
      if (fs.existsSync(filePath)) {
        fs.unlinkSync(filePath);
      }
    },
  };
}

async function captureStep(testInfo: TestInfo, page: Page, name: string): Promise<string> {
  const filePath = testInfo.outputPath(`${name}.png`);
  await page.screenshot({ path: filePath, fullPage: true });
  await testInfo.attach(name, {
    path: filePath,
    contentType: "image/png",
  });
  return filePath;
}

async function attachJson(testInfo: TestInfo, name: string, payload: unknown): Promise<string> {
  const filePath = testInfo.outputPath(`${name}.json`);
  fs.writeFileSync(filePath, JSON.stringify(payload, null, 2), "utf8");
  await testInfo.attach(name, {
    path: filePath,
    contentType: "application/json",
  });
  return filePath;
}

async function createRecordedSession(
  browser: Browser,
  testInfo: TestInfo,
  label: string,
): Promise<RecordedSession> {
  const videoDir = testInfo.outputPath(`${label}-video`);
  fs.mkdirSync(videoDir, { recursive: true });

  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    recordVideo: {
      dir: videoDir,
      size: { width: 1440, height: 900 },
    },
  });

  return {
    label,
    context,
    page: await context.newPage(),
  };
}

async function closeRecordedSession(testInfo: TestInfo, session?: RecordedSession): Promise<void> {
  if (!session) {
    return;
  }

  const video = session.page.video();
  await session.context.close().catch(() => undefined);

  if (video) {
    const videoPath = await video.path().catch(() => undefined);
    if (videoPath && fs.existsSync(videoPath)) {
      await testInfo.attach(`${session.label}-video`, {
        path: videoPath,
        contentType: "video/webm",
      });
    }
  }
}

test("05 e2e transfer flow: provider UI bootstrap + consumer negotiation and transfer", async ({
  browser,
  request,
}, testInfo) => {
  const runtime = resolveDataspacePortalRuntime();
  const suffix = `${Date.now()}`;
  const assetId = `qa-ui-transfer-${suffix}`;
  const upload = createUploadFile();
  const chunkEvents: ChunkEvent[] = [];
  const providerFolder = `playwright-e2e/${assetId}`;
  const report: Record<string, unknown> = {
    startedAt: new Date().toISOString(),
    providerConnector: runtime.provider.connectorName,
    consumerConnector: runtime.consumer.connectorName,
    assetId,
    uploadFilePath: upload.path,
    uploadFileSizeBytes: upload.sizeBytes,
    providerFolder,
    providerBootstrap: null,
    providerSetup: {
      chunkEvents,
    },
    negotiation: {},
    transfer: {},
    storageVerification: {
      status: "skipped",
      reason: "not configured in this suite yet",
    },
  };

  let providerSession: RecordedSession | undefined;
  let consumerSession: RecordedSession | undefined;

  try {
    providerSession = await createRecordedSession(browser, testInfo, "provider-session");
    const providerPage = providerSession.page;
    const providerLoginPage = new KeycloakLoginPage(providerPage, {
      portalUser: runtime.provider.username,
      portalPassword: runtime.provider.password,
      skipLogin: false,
    });
    const providerShellPage = new ConnectorShellPage(providerPage);
    const assetCreatePage = new AssetCreatePage(providerPage);

    providerPage.on("response", async (response) => {
      const url = response.url();
      if (!url.includes("/s3assets/upload-chunk")) {
        return;
      }

      const event: ChunkEvent = { url, status: response.status() };
      if (response.status() >= 400) {
        event.bodySnippet = (await response.text().catch(() => "")).slice(0, 300);
      }
      chunkEvents.push(event);
    });

    await providerLoginPage.open(runtime.provider.portalBaseUrl);
    await providerLoginPage.loginIfNeeded();
    await providerShellPage.expectReady();
    await captureStep(testInfo, providerPage, "provider-01-after-login");

    await assetCreatePage.goto(runtime.provider.portalBaseUrl);
    await assetCreatePage.expectReady();
    await assetCreatePage.fillRequiredFields(assetId, providerFolder);
    await assetCreatePage.uploadFile(upload.path);
    await captureStep(testInfo, providerPage, "provider-02-form-complete");

    await assetCreatePage.submit();
    const firstAttemptMessage = await assetCreatePage.waitForSnackBarText(120_000);
    let secondAttemptMessage: string | undefined;
    if (await assetCreatePage.isCreateButtonVisible()) {
      await assetCreatePage.submit();
      secondAttemptMessage = await assetCreatePage.waitForSnackBarText(60_000);
    }

    report.providerSetup = {
      ...(report.providerSetup as object),
      firstAttemptMessage,
      secondAttemptMessage: secondAttemptMessage ?? null,
      maxRetriesDetected:
        `${firstAttemptMessage ?? ""} ${secondAttemptMessage ?? ""}`.toLowerCase().includes("maximum retries"),
    };
    const providerUploadSucceeded = `${firstAttemptMessage ?? ""} ${secondAttemptMessage ?? ""}`
      .toLowerCase()
      .includes("asset created successfully");
    const blockingChunkErrors = chunkEvents.filter(
      (event) => event.status >= 400 && !(providerUploadSucceeded && event.status === 401),
    );

    expect(firstAttemptMessage, "No notification was detected after creating the asset").toBeTruthy();
    expect(chunkEvents.length, "No upload-chunk responses were captured").toBeGreaterThan(0);
    expect(
      blockingChunkErrors,
      `Unexpected upload-chunk errors after retry recovery: ${JSON.stringify(blockingChunkErrors)}`,
    ).toHaveLength(0);
    expect(
      providerUploadSucceeded,
      "The success message 'Asset created successfully' was not detected",
    ).toBeTruthy();

    await captureStep(testInfo, providerPage, "provider-03-created");

    report.providerBootstrap = await bootstrapProviderContractArtifacts(request, runtime, assetId, suffix);
    await attachJson(testInfo, "provider-bootstrap-report", report.providerBootstrap);
    await attachJson(
      testInfo,
      "consumer-catalog-api-readiness",
      await probeConsumerCatalogDatasetReadiness(request, runtime, assetId),
    );

    consumerSession = await createRecordedSession(browser, testInfo, "consumer-session");
    const consumerPage = consumerSession.page;
    const consumerLoginPage = new KeycloakLoginPage(consumerPage, {
      portalUser: runtime.consumer.username,
      portalPassword: runtime.consumer.password,
      skipLogin: false,
    });
    const consumerShellPage = new ConnectorShellPage(consumerPage);
    const catalogPage = new CatalogPage(consumerPage);
    const contractOffersPage = new ContractOffersPage(consumerPage);
    const contractsPage = new ContractsPage(consumerPage);
    const transferHistoryPage = new TransferHistoryPage(consumerPage);

    await consumerLoginPage.open(runtime.consumer.portalBaseUrl);
    await consumerLoginPage.loginIfNeeded();
    await consumerShellPage.expectReady();
    await captureStep(testInfo, consumerPage, "consumer-01-after-login");

    await expect(async () => {
      await catalogPage.goto(runtime.consumer.portalBaseUrl);
      await consumerShellPage.assertNoGateway403("Catalog page");
      await consumerShellPage.assertNoServerErrorBanner("Catalog page");
      await catalogPage.expectReady();

      let opened = await catalogPage.openDetailsForAsset(assetId);
      while (!opened && (await catalogPage.goToNextPage())) {
        opened = await catalogPage.openDetailsForAsset(assetId);
      }

      expect(opened, `Asset ${assetId} is not visible in the consumer catalog yet`).toBeTruthy();
    }).toPass({
      timeout: 90_000,
      intervals: EVENTUAL_UI_RETRY_INTERVALS,
    });

    const attachConsumerJson = async (name: string, payload: unknown): Promise<void> => {
      await attachJson(testInfo, name, payload);
    };

    await catalogPage.expectDetailsVisible({
      assetId,
      attachJson: attachConsumerJson,
      context: "e2e-consumer-catalog-detail",
    });
    await contractOffersPage.expectReady({
      assetId,
      attachJson: attachConsumerJson,
      context: "e2e-consumer-contract-offers",
    });
    await captureStep(testInfo, consumerPage, "consumer-02-catalog-detail");
    await contractOffersPage.openContractOffersTab();
    await captureStep(testInfo, consumerPage, "consumer-03-contract-offers");

    await contractOffersPage.negotiateFirstOffer();
    const negotiationMessage = await contractOffersPage.waitForNegotiationComplete(45_000);
    report.negotiation = {
      notification: negotiationMessage,
    };
    await captureStep(testInfo, consumerPage, "consumer-04-negotiation-complete");

    await expect(async () => {
      await contractsPage.goto(runtime.consumer.portalBaseUrl);
      await contractsPage.expectReady();
      expect(
        await contractsPage.hasContractForAsset(assetId),
        `Contract for asset ${assetId} is not visible yet`,
      ).toBeTruthy();
    }).toPass({
      timeout: 90_000,
      intervals: EVENTUAL_UI_RETRY_INTERVALS,
    });

    await captureStep(testInfo, consumerPage, "consumer-05-contracts");
    const transferInitiatedMessage = await contractsPage.startInesDataStoreTransfer(assetId);
    report.transfer = {
      initiatedMessage: transferInitiatedMessage,
    };
    await captureStep(testInfo, consumerPage, "consumer-06-transfer-started");

    await transferHistoryPage.goto(runtime.consumer.portalBaseUrl);
    await transferHistoryPage.expectReady();
    const finalState = await transferHistoryPage.waitForSuccessfulTransfer(assetId, 90_000);
    report.transfer = {
      ...(report.transfer as object),
      finalState,
    };
    await captureStep(testInfo, consumerPage, "consumer-07-transfer-history");
  } finally {
    await attachJson(testInfo, "e2e-transfer-report", {
      ...report,
      finishedAt: new Date().toISOString(),
    });
    upload.cleanup();
    await closeRecordedSession(testInfo, consumerSession);
    await closeRecordedSession(testInfo, providerSession);
  }
});
