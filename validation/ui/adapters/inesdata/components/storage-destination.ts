import { Page } from "@playwright/test";

import { clickMarked } from "../../../shared/utils/live-marker";
import { materialSelect } from "../../../shared/utils/selectors";

const DEFAULT_LOCAL_STORE_LABEL = "LocalStore";
const LEGACY_LOCAL_STORE_LABEL = "InesDataStore";
const PIONERA_LOCAL_STORE_LABEL = "PIONERA Store";
const PIONERA_COMPACT_LOCAL_STORE_LABEL = "PIONERAStore";

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function localStoreLabels(): string[] {
  const configured =
    process.env.UI_INESDATA_LOCAL_STORE_LABEL ||
    process.env.INESDATA_LOCAL_STORE_LABEL ||
    DEFAULT_LOCAL_STORE_LABEL;
  const labels = [
    configured,
    PIONERA_LOCAL_STORE_LABEL,
    PIONERA_COMPACT_LOCAL_STORE_LABEL,
    DEFAULT_LOCAL_STORE_LABEL,
    LEGACY_LOCAL_STORE_LABEL,
  ]
    .map((value) => value.trim())
    .filter(Boolean);
  return [...new Set(labels)];
}

export async function selectLocalStoreDestination(page: Page): Promise<void> {
  await clickMarked(materialSelect(page, "Destination"));

  for (const label of localStoreLabels()) {
    const option = page
      .locator(".cdk-overlay-pane mat-option, .cdk-overlay-pane [role='option'], mat-option")
      .filter({ hasText: new RegExp(`^\\s*${escapeRegExp(label)}\\s*$`, "i") })
      .first();
    const visible = await option.waitFor({ state: "visible", timeout: 1500 }).then(
      () => true,
      () => false,
    );
    if (visible) {
      await clickMarked(option);
      return;
    }
  }

  throw new Error(
    `Could not find local storage destination option. Tried: ${localStoreLabels().join(", ")}`,
  );
}
