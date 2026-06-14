import { expect, Page } from "@playwright/test";

import { waitForEventualConsistencyPoll } from "../../../shared/utils/waiting";
import { gotoEdcDashboardRoute } from "./edc-dashboard.page";

const SUCCESS_STATES = new Set(["COMPLETED", "STARTED"]);
const FAILURE_STATES = new Set(["TERMINATED", "DEPROVISIONED", "SUSPENDED", "ERROR"]);

function positiveIntegerFromEnv(name: string, fallback: number): number {
  const raw = process.env[name]?.trim();
  if (!raw) {
    return fallback;
  }
  const value = Number.parseInt(raw, 10);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

function topologyDefaultTransferTimeoutMs(): number {
  const topology = (process.env.UI_TOPOLOGY || process.env.PIONERA_TOPOLOGY || "")
    .trim()
    .toLowerCase();
  if (topology === "vm-distributed") {
    return 420_000;
  }
  if (topology === "vm-single") {
    return 300_000;
  }
  return 180_000;
}

export function resolveEdcTransferSuccessTimeoutMs(): number {
  const fallback = topologyDefaultTransferTimeoutMs();
  return positiveIntegerFromEnv(
    "UI_EDC_TRANSFER_SUCCESS_TIMEOUT_MS",
    positiveIntegerFromEnv("PIONERA_EDC_TRANSFER_SUCCESS_TIMEOUT_MS", fallback),
  );
}

export class EdcTransferHistoryPage {
  constructor(private readonly page: Page) {}

  async goto(baseUrl: string): Promise<void> {
    await gotoEdcDashboardRoute(this.page, baseUrl, "transfer-history", "Transfer History");
  }

  async expectReady(): Promise<void> {
    await expect(this.page).toHaveURL(/\/edc-dashboard\/transfer-history(?:\/)?(?:\?.*)?$/);
    await expect(this.page.locator("lib-transfer-history-table").first()).toBeVisible({
      timeout: 30_000,
    });
  }

  async waitForSuccessfulTransfer(
    assetId: string,
    timeoutMs = resolveEdcTransferSuccessTimeoutMs(),
  ): Promise<string> {
    const startedAt = Date.now();
    let lastState: string | undefined;

    while (Date.now() - startedAt < timeoutMs) {
      const state = await this.readStateForAsset(assetId);
      if (state) {
        lastState = state;
        if (FAILURE_STATES.has(state)) {
          throw new Error(`Transfer for asset ${assetId} reached failure state ${state}`);
        }
        if (SUCCESS_STATES.has(state)) {
          return state;
        }
      }

      await this.page.reload({ waitUntil: "domcontentloaded" });
      const remainingMs = timeoutMs - (Date.now() - startedAt);
      if (remainingMs <= 0) {
        break;
      }
      await waitForEventualConsistencyPoll(this.page, Math.min(remainingMs, 1_000));
    }

    throw new Error(
      `Transfer for asset ${assetId} did not reach a success state. Last state: ${lastState ?? "not found"}`,
    );
  }

  async readStateForAsset(assetId: string): Promise<string | undefined> {
    const row = this.page.locator("tbody tr").filter({ hasText: assetId }).first();
    if ((await row.count().catch(() => 0)) === 0) {
      return undefined;
    }
    const stateCell = row.locator("td").nth(2);
    const state = ((await stateCell.textContent()) ?? "").replace(/\s+/g, " ").trim();
    return state || undefined;
  }
}
