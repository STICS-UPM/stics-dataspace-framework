import { test, expect } from "../shared/fixtures/dataspace.fixture";
import fs from "fs";
import os from "os";
import path from "path";

import { KeycloakLoginPage } from "../components/auth/keycloak-login.page";
import { ConnectorShellPage } from "../components/shell/connector-shell.page";
import { AssetCreatePage } from "../components/provider/asset-create.page";
import { PolicyCreatePage } from "../components/provider/policy-create.page";
import { ContractDefinitionCreatePage } from "../components/provider/contract-definition-create.page";

test.setTimeout(180_000);

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

type UploadFileHandle = {
  path: string;
  cleanup: () => void;
};

type ProviderContractDefinitionReport = {
  startedAt: string;
  baseUrl: string;
  assetId: string;
  policyId: string;
  contractDefinitionId: string;
  filePath: string;
  assetMessage?: string;
  policyMessage?: string;
  contractDefinitionMessage?: string;
  chunkEvents: ChunkEvent[];
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

function createSmallUploadFile(): UploadFileHandle {
  const filePath = path.join(os.tmpdir(), `playwright-contract-definition-${Date.now()}.bin`);
  fs.writeFileSync(filePath, Buffer.alloc(1024 * 1024, "A"));
  return {
    path: filePath,
    cleanup: () => {
      if (fs.existsSync(filePath)) {
        fs.unlinkSync(filePath);
      }
    },
  };
}

test("03c provider setup: contract definition creation from the UI", async ({
  page,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  const suffix = `${Date.now()}`;
  const portalBaseUrl = dataspaceRuntime.provider.portalBaseUrl;
  const portalObjectPrefix = process.env.PORTAL_TEST_OBJECT_PREFIX ?? "playwright-e2e";
  const assetId = `qa-ui-contract-asset-${suffix}`;
  const policyId = `qa-ui-contract-policy-${suffix}`;
  const contractDefinitionId = `qa-ui-contract-definition-${suffix}`;
  const participantId = `participant-${suffix}`;
  const upload = createSmallUploadFile();
  const loginPage = new KeycloakLoginPage(page, {
    portalUser: dataspaceRuntime.provider.username,
    portalPassword: dataspaceRuntime.provider.password,
    skipLogin: false,
  });
  const shellPage = new ConnectorShellPage(page);
  const assetCreatePage = new AssetCreatePage(page);
  const policyCreatePage = new PolicyCreatePage(page);
  const contractDefinitionCreatePage = new ContractDefinitionCreatePage(page);
  const report: ProviderContractDefinitionReport = {
    startedAt: new Date().toISOString(),
    baseUrl: portalBaseUrl,
    assetId,
    policyId,
    contractDefinitionId,
    filePath: upload.path,
    chunkEvents: [],
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
    await loginPage.open(portalBaseUrl);
    await loginPage.loginIfNeeded();
    await shellPage.expectReady();
    await captureStep(page, "01-contract-definition-after-login");

    await assetCreatePage.goto(portalBaseUrl);
    await assetCreatePage.expectReady();
    await assetCreatePage.fillRequiredFields(assetId, `${portalObjectPrefix}/${assetId}`);
    await assetCreatePage.uploadFile(upload.path);
    await captureStep(page, "02-contract-definition-asset-form");

    await assetCreatePage.submit();
    report.assetMessage = await assetCreatePage.waitForSnackBarText(120_000);
    if (await assetCreatePage.isCreateButtonVisible()) {
      await assetCreatePage.submit();
      report.assetMessage = await assetCreatePage.waitForSnackBarText(60_000) ?? report.assetMessage;
    }
    await captureStep(page, "03-contract-definition-asset-created");

    const firstChunkError = report.chunkEvents.find((event) => event.status >= 400);
    report.firstChunkErrorStatus = firstChunkError?.status;
    if (firstChunkError) {
      const classification = classifyUploadFailure(firstChunkError.status);
      report.uploadFailureCategory = classification.category;
      report.diagnosticHint = classification.diagnosticHint;
    }

    expect(report.assetMessage, "The prerequisite asset was not created successfully").toMatch(
      /asset created successfully/i,
    );

    await policyCreatePage.goto(portalBaseUrl);
    await policyCreatePage.expectReady();
    await policyCreatePage.fillPolicyId(policyId);
    await policyCreatePage.addParticipantIdConstraint(participantId);
    await captureStep(page, "04-contract-definition-policy-form");

    await policyCreatePage.submit();
    report.policyMessage = await policyCreatePage.waitForCreationSuccess();
    await policyCreatePage.expectPolicyListed(policyId);
    await captureStep(page, "05-contract-definition-policy-created");

    await contractDefinitionCreatePage.goto(portalBaseUrl);
    await contractDefinitionCreatePage.expectReady();
    await contractDefinitionCreatePage.selectMatchingPolicies(policyId);
    await contractDefinitionCreatePage.fillContractDefinitionId(contractDefinitionId);
    await contractDefinitionCreatePage.addAsset(assetId);
    await captureStep(page, "06-contract-definition-form-complete");

    await contractDefinitionCreatePage.submit();
    report.contractDefinitionMessage = await contractDefinitionCreatePage.waitForCreationSuccess();
    await contractDefinitionCreatePage.expectContractDefinitionListed(contractDefinitionId, {
      policyId,
      assetId,
    });
    await captureStep(page, "07-contract-definition-created");

    expect(report.policyMessage, "The prerequisite policy was not created successfully").toMatch(
      /successfully created/i,
    );
    expect(
      report.contractDefinitionMessage,
      "No contract definition creation notification was detected",
    ).toMatch(/contract definition created/i);
  } finally {
    await attachJson("provider-contract-definition-report", report);
    upload.cleanup();
  }
});
