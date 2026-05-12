import { test, expect } from "../shared/fixtures/minio-console.fixture";

import type { MinioBucketTarget } from "../shared/utils/minio-console-runtime";
import { MinioConsoleLoginPage } from "../components/ops/minio-console-login.page";
import { MinioBucketBrowserPage } from "../components/ops/minio-bucket-browser.page";

async function validateBucketVisibility(args: {
  page: Parameters<Parameters<typeof test>[1]>[0]["page"];
  captureStep: Parameters<Parameters<typeof test>[1]>[0]["captureStep"];
  attachJson: Parameters<Parameters<typeof test>[1]>[0]["attachJson"];
  target: MinioBucketTarget;
}) {
  const { page, captureStep, attachJson, target } = args;
  const loginPage = new MinioConsoleLoginPage(page);
  const bucketPage = new MinioBucketBrowserPage(page);
  const report = {
    startedAt: new Date().toISOString(),
    role: target.role,
    connectorName: target.connectorName,
    bucketName: target.bucketName,
    bucketBrowserUrl: target.bucketBrowserUrl,
    expectedObject: target.expectedObject ?? null,
  };

  try {
    await loginPage.open(target.bucketBrowserUrl);
    await loginPage.loginIfNeeded(target.credentials);
    await bucketPage.expectReady(target.bucketName);
    await bucketPage.assertNoBucketPermissionError();

    if (target.expectedObject) {
      await bucketPage.expectObjectVisible(target.expectedObject);
    }

    await captureStep(page, `${target.role}-bucket-browser`);
  } finally {
    await attachJson(`${target.role}-bucket-browser-report`, {
      ...report,
      finishedAt: new Date().toISOString(),
    });
  }
}

test("MinIO browser: provider bucket visible by direct URL", async ({
  page,
  minioConsoleRuntime,
  captureStep,
  attachJson,
}) => {
  const target = minioConsoleRuntime.targets.find((item) => item.role === "provider");
  expect(target, "Provider bucket target is not configured").toBeTruthy();
  await validateBucketVisibility({
    page,
    captureStep,
    attachJson,
    target: target!,
  });
});

test("MinIO browser: consumer bucket visible by direct URL", async ({
  page,
  minioConsoleRuntime,
  captureStep,
  attachJson,
}) => {
  const target = minioConsoleRuntime.targets.find((item) => item.role === "consumer");
  expect(target, "Consumer bucket target is not configured").toBeTruthy();
  await validateBucketVisibility({
    page,
    captureStep,
    attachJson,
    target: target!,
  });
});
