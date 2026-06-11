import { test as base, expect, Page, TestInfo } from "@playwright/test";
import fs from "fs";

import { DataspacePortalRuntime, resolveDataspacePortalRuntime } from "../utils/dataspace-runtime";
import { installEdcDashboardRouteBridge } from "../utils/edc-dashboard-route-bridge";
import { installIngressPortForwardRouteBridge } from "../utils/ingress-port-forward-route-bridge";
import { installTransientNavigationRetry } from "../utils/navigation-retry";

type DataspaceFixtures = {
  dataspaceRuntime: DataspacePortalRuntime;
  captureStep: (page: Page, name: string, options?: { fullPage?: boolean }) => Promise<string>;
  attachJson: (name: string, payload: unknown) => Promise<void>;
};

async function writeJsonArtifact(testInfo: TestInfo, name: string, payload: unknown): Promise<string> {
  const filePath = testInfo.outputPath(`${name}.json`);
  fs.writeFileSync(filePath, JSON.stringify(payload, null, 2), "utf8");
  await testInfo.attach(name, {
    path: filePath,
    contentType: "application/json",
  });
  return filePath;
}

export const test = base.extend<DataspaceFixtures>({
  page: async ({ page }, use) => {
    const disposeNavigationRetry = installTransientNavigationRetry(page);
    try {
      await use(page);
    } finally {
      disposeNavigationRetry();
    }
  },

  dataspaceRuntime: async ({ page }, use) => {
    const runtime = resolveDataspacePortalRuntime();
    const disposeIngressPortForwardRouteBridge = await installIngressPortForwardRouteBridge(page, runtime);
    const disposeRouteBridge = await installEdcDashboardRouteBridge(page, runtime);
    try {
      await use(runtime);
    } finally {
      await disposeRouteBridge();
      await disposeIngressPortForwardRouteBridge();
    }
  },

  captureStep: async ({}, use, testInfo) => {
    await use(async (page, name, options) => {
      const fullPage = options?.fullPage ?? true;
      const filePath = testInfo.outputPath(`${name}.png`);
      await page.screenshot({ path: filePath, fullPage });
      await testInfo.attach(name, {
        path: filePath,
        contentType: "image/png",
      });
      return filePath;
    });
  },

  attachJson: async ({}, use, testInfo) => {
    await use(async (name, payload) => {
      await writeJsonArtifact(testInfo, name, payload);
    });
  },
});

export { expect } from "@playwright/test";
