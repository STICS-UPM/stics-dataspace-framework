import { test, expect } from "../shared/fixtures/auth.fixture";
import { AssetCreatePage } from "../components/provider/asset-create.page";

type ChunkEvent = {
  url: string;
  status: number;
  bodySnippet?: string;
};

type UploadFailureCategory =
  | "payload_too_large"
  | "access_denied"
  | "server_error"
  | "client_error"
  | "unknown";

type ProviderFlowReport = {
  startedAt: string;
  baseUrl: string;
  assetId: string;
  filePath: string;
  expectedFileSizeBytes: number;
  expectedObjectKey: string;
  firstAttemptMessage?: string;
  secondAttemptMessage?: string;
  chunkEvents: ChunkEvent[];
  maxRetriesDetected: boolean;
  firstChunkErrorStatus?: number;
  uploadFailureCategory?: UploadFailureCategory;
  diagnosticHint?: string;
};

function classifyUploadFailure(status: number | undefined): {
  category: UploadFailureCategory;
  diagnosticHint?: string;
} {
  if (status === 413) {
    return {
      category: "payload_too_large",
      diagnosticHint:
        "The upload endpoint returned HTTP 413. This usually points to a proxy/ingress request-size limit before the connector can process the chunk.",
    };
  }

  if (status === 403) {
    return {
      category: "access_denied",
      diagnosticHint:
        "The upload endpoint returned HTTP 403. This usually points to missing MinIO/S3 permissions for the connector user or service account.",
    };
  }

  if (status && status >= 500) {
    return {
      category: "server_error",
      diagnosticHint:
        "The upload endpoint returned HTTP 5xx. This usually means the connector or a downstream dependency rejected the upload after the request reached the backend.",
    };
  }

  if (status && status >= 400) {
    return {
      category: "client_error",
      diagnosticHint:
        "The upload endpoint returned HTTP 4xx. The request was rejected before the upload flow completed.",
    };
  }

  return {
    category: "unknown",
  };
}

test("03 provider setup: asset creation with file upload", async ({
  page,
  portalBaseUrl,
  portalObjectPrefix,
  uniqueSuffix,
  createUploadFile,
  ensureLoggedIn,
  captureStep,
  attachJson,
}) => {
  const upload = await createUploadFile();
  const assetId = `qa-ui-asset-${uniqueSuffix}`;
  const assetCreatePage = new AssetCreatePage(page);
  const report: ProviderFlowReport = {
    startedAt: new Date().toISOString(),
    baseUrl: portalBaseUrl,
    assetId,
    filePath: upload.path,
    expectedFileSizeBytes: upload.sizeBytes,
    expectedObjectKey: `${portalObjectPrefix}/${assetId}/${upload.path.split("/").pop()}`,
    chunkEvents: [],
    maxRetriesDetected: false,
  };

  page.on("response", async (response) => {
    const url = response.url();
    if (!url.includes("/s3assets/upload-chunk")) {
      return;
    }

    const event: ChunkEvent = {
      url,
      status: response.status(),
    };
    if (response.status() >= 400) {
      try {
        event.bodySnippet = (await response.text()).slice(0, 300);
      } catch {
        event.bodySnippet = "<unreadable response body>";
      }
    }
    report.chunkEvents.push(event);
  });

  try {
    await ensureLoggedIn();
    await captureStep(page, "01-provider-after-login");

    await assetCreatePage.goto(portalBaseUrl);
    await assetCreatePage.expectReady();
    await assetCreatePage.fillRequiredFields(assetId, `${portalObjectPrefix}/${assetId}`);
    await assetCreatePage.uploadFile(upload.path);
    await captureStep(page, "02-provider-form-complete");

    await assetCreatePage.submit();
    report.firstAttemptMessage = await assetCreatePage.waitForSnackBarText(120_000);

    if (await assetCreatePage.isCreateButtonVisible()) {
      await assetCreatePage.submit();
      report.secondAttemptMessage = await assetCreatePage.waitForSnackBarText(60_000);
    }

    await captureStep(page, "03-provider-created");

    const firstMessage = (report.firstAttemptMessage ?? "").toLowerCase();
    const secondMessage = (report.secondAttemptMessage ?? "").toLowerCase();
    report.maxRetriesDetected =
      firstMessage.includes("maximum retries") || secondMessage.includes("maximum retries");

    const uploadSucceeded =
      firstMessage.includes("asset created successfully") ||
      secondMessage.includes("asset created successfully");
    const firstChunkError = report.chunkEvents.find((event) => event.status >= 400);

    report.firstChunkErrorStatus = firstChunkError?.status;
    if (firstChunkError) {
      const classification = classifyUploadFailure(firstChunkError.status);
      report.uploadFailureCategory = classification.category;
      report.diagnosticHint = classification.diagnosticHint;
    }
    const blockingChunkErrors = report.chunkEvents.filter(
      (event) => event.status >= 400 && !(uploadSucceeded && event.status === 401),
    );

    expect(report.firstAttemptMessage, "No notification was detected after creating the asset").toBeTruthy();
    expect(report.chunkEvents.length, "No upload-chunk responses were captured").toBeGreaterThan(0);
    expect(
      blockingChunkErrors,
      `Unexpected upload-chunk errors after retry recovery: ${JSON.stringify(blockingChunkErrors)}`,
    ).toHaveLength(0);
    expect(report.maxRetriesDetected, "The UI reported 'Maximum retries reached'").toBeFalsy();
    expect(uploadSucceeded, "The success message 'Asset created successfully' was not detected").toBeTruthy();
  } finally {
    await attachJson("provider-setup-report", report);
    upload.cleanup();
  }
});
