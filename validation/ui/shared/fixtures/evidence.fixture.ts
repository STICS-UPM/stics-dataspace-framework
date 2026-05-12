import { Page, TestInfo } from "@playwright/test";
import fs from "fs";

import { test as runtimeTest, expect } from "./runtime.fixture";

type EvidenceFixtures = {
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

export const test = runtimeTest.extend<EvidenceFixtures>({
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

export { expect } from "./runtime.fixture";
