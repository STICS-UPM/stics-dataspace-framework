import { test as base } from "@playwright/test";
import fs from "fs";
import os from "os";
import path from "path";

import {
  ConnectorPortalRuntime,
  resolveConnectorPortalRuntime,
  resolveDataspacePortalRuntime,
} from "../utils/dataspace-runtime";

function requiredEnv(name: string): string {
  const value = process.env[name];
  if (!value || value.trim().length === 0) {
    throw new Error(`Missing required env var: ${name}`);
  }
  return value;
}

function asBool(value: string | undefined, fallback = false): boolean {
  if (!value) {
    return fallback;
  }
  const normalized = value.trim().toLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes";
}

function getFileSizeMb(): number {
  const raw = process.env.PORTAL_TEST_FILE_MB ?? "60";
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? n : 60;
}

function resolvePortalRuntime(): ConnectorPortalRuntime {
  const explicitPortalUrl = process.env.PORTAL_BASE_URL?.trim();
  if (explicitPortalUrl) {
    const adapter = process.env.UI_ADAPTER?.trim().toLowerCase() || "custom";
    return {
      adapter,
      connectorName: process.env.UI_PORTAL_CONNECTOR?.trim() || "custom",
      portalBaseUrl: explicitPortalUrl.replace(/\/$/, ""),
      managementBaseUrl: process.env.PORTAL_MANAGEMENT_BASE_URL?.trim() || "",
      protocolBaseUrl: process.env.PORTAL_PROTOCOL_BASE_URL?.trim() || "",
      transferStartPath:
        process.env.PORTAL_TRANSFER_START_PATH?.trim() ||
        (adapter === "edc" ? "transferprocesses" : "inesdatatransferprocesses"),
      transferDestinationType:
        process.env.PORTAL_TRANSFER_DESTINATION_TYPE?.trim() ||
        (adapter === "edc" ? "HttpData" : "InesDataStore"),
      username: process.env.PORTAL_USER ?? "",
      password: process.env.PORTAL_PASSWORD ?? "",
    };
  }

  const explicitConnector = process.env.UI_PORTAL_CONNECTOR?.trim();
  if (explicitConnector) {
    return resolveConnectorPortalRuntime(explicitConnector);
  }

  const role = (process.env.UI_PORTAL_ROLE ?? "provider").trim().toLowerCase();
  const dataspaceRuntime = resolveDataspacePortalRuntime();
  if (role === "consumer") {
    return dataspaceRuntime.consumer;
  }
  if (role === "provider") {
    return dataspaceRuntime.provider;
  }

  throw new Error("UI_PORTAL_ROLE must be either 'provider' or 'consumer'");
}

export type UploadFileHandle = {
  path: string;
  sizeBytes: number;
  cleanup: () => void;
};

type RuntimeFixtures = {
  portalBaseUrl: string;
  portalUser: string;
  portalPassword: string;
  portalSkipLogin: boolean;
  portalObjectPrefix: string;
  uniqueSuffix: string;
  createUploadFile: () => Promise<UploadFileHandle>;
};

export const test = base.extend<RuntimeFixtures>({
  portalBaseUrl: async ({}, use) => {
    await use(resolvePortalRuntime().portalBaseUrl);
  },

  portalUser: async ({}, use) => {
    await use(resolvePortalRuntime().username);
  },

  portalPassword: async ({}, use) => {
    await use(resolvePortalRuntime().password);
  },

  portalSkipLogin: async ({}, use) => {
    await use(asBool(process.env.PORTAL_SKIP_LOGIN, false));
  },

  portalObjectPrefix: async ({}, use) => {
    await use(process.env.PORTAL_TEST_OBJECT_PREFIX ?? "playwright-e2e");
  },

  uniqueSuffix: async ({}, use) => {
    await use(`${Date.now()}`);
  },

  createUploadFile: async ({}, use) => {
    await use(async () => {
      const filePath = path.join(os.tmpdir(), `playwright-asset-${Date.now()}.bin`);
      const fileSizeMb = getFileSizeMb();
      const content = Buffer.alloc(fileSizeMb * 1024 * 1024, "A");
      fs.writeFileSync(filePath, content);
      return {
        path: filePath,
        sizeBytes: fs.statSync(filePath).size,
        cleanup: () => {
          if (fs.existsSync(filePath)) {
            fs.unlinkSync(filePath);
          }
        },
      };
    });
  },
});

export { expect } from "@playwright/test";
