import type { Page, Response } from "@playwright/test";

import { test, expect } from "../../../shared/fixtures/dataspace.fixture";

import { KeycloakLoginPage } from "../../../shared/components/auth/keycloak-login.page";
import { ConnectorShellPage } from "../components/shell/connector-shell.page";
import { collectBrowserDiagnostics } from "../../../shared/utils/browser-diagnostics";
import { clickMarked, fillMarked } from "../../../shared/utils/live-marker";

type VocabularyRecord = {
  "@id"?: string;
  id?: string;
  name?: string;
  category?: string;
  connectorId?: string;
  jsonSchema?: string;
};

type AIModelDaimoVocabularyReport = {
  startedAt: string;
  connector: string;
  portalBaseUrl: string;
  vocabularyId: string;
  vocabularyName: string;
  linkedCases: string[];
  createResponse?: {
    url: string;
    status: number;
  };
  sharedVocabularyResponse?: {
    url: string;
    status: number;
    itemCount?: number;
  };
  runtimeConfig?: {
    participantId?: string;
  };
  persistedVocabulary?: VocabularyRecord;
  assetCreateVocabularyCheck?: {
    url: string;
    assetType: "machineLearning";
    vocabularyName: string;
    status: "passed";
  };
  errorResponses: Array<{ url: string; status: number }>;
  fatalErrorResponses: Array<{ url: string; status: number }>;
};

const AI_MODEL_HUB_DEMO_ENV = "UI_AI_MODEL_HUB_HTTPDATA_DEMO";

const DAIMO_SCHEMA = {
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://pionera.validation/schemas/daimo-a52-model.schema.json",
  title: "DAIMO model metadata schema",
  description:
    "Controlled DAIMO vocabulary slice used by A5.2 validation to describe machine-learning assets in INESData.",
  type: "object",
  properties: {
    "daimo:asset_kind": {
      type: "string",
      enum: ["model", "dataset", "benchmark"],
    },
    "daimo:task": {
      type: "string",
      examples: ["text-classification", "sentiment-analysis"],
    },
    "daimo:framework": {
      type: "string",
    },
    "daimo:inference_path": {
      type: "string",
      pattern: "^/",
    },
    "daimo:input_schema": {
      type: "object",
    },
    "daimo:input_example": {
      type: "object",
    },
    "daimo:benchmark_dataset": {
      type: "string",
    },
  },
  required: ["daimo:asset_kind", "daimo:task", "daimo:inference_path"],
  additionalProperties: true,
};

test.skip(
  process.env[AI_MODEL_HUB_DEMO_ENV] !== "1",
  `Set ${AI_MODEL_HUB_DEMO_ENV}=1 or run Level 6 with the INESData adapter to validate the DAIMO machine-learning vocabulary from the INESData UI.`,
);

function vocabulariesUrl(portalBaseUrl: string): string {
  return `${portalBaseUrl.replace(/\/$/, "")}/vocabularies`;
}

function createVocabularyUrl(portalBaseUrl: string): string {
  return `${vocabulariesUrl(portalBaseUrl)}/create`;
}

function assetCreateUrl(portalBaseUrl: string): string {
  return `${portalBaseUrl.replace(/\/$/, "")}/assets/create`;
}

function runtimeConfigUrl(portalBaseUrl: string): string {
  return `${portalBaseUrl.replace(/\/$/, "")}/assets/config/app.config.json`;
}

function isVocabularyIntegrationUrl(url: string): boolean {
  return url.includes("/connector-vocabularies/") || url.includes("/management/vocabularies");
}

function vocabularyIdentifier(vocabulary: VocabularyRecord): string {
  return String(vocabulary["@id"] || vocabulary.id || "");
}

function formField(page: Page, label: RegExp) {
  return page
    .locator("mat-form-field")
    .filter({ has: page.locator("mat-label", { hasText: label }) })
    .first();
}

function formControl(page: Page, label: RegExp) {
  return formField(page, label).locator("input, textarea").first();
}

async function selectMaterialOption(
  page: Page,
  label: RegExp,
  optionText: RegExp,
  selectedText: RegExp,
): Promise<void> {
  const field = formField(page, label);
  await expect(field).toBeVisible({ timeout: 15_000 });

  const combobox = field.getByRole("combobox").first();
  const matSelect = field.locator("mat-select").first();
  const overlayOptions = page.locator(".cdk-overlay-pane [role='option'], .cdk-overlay-pane mat-option");
  let lastFieldText = ((await field.textContent().catch(() => "")) ?? "").replace(/\s+/g, " ").trim();

  for (let attempt = 1; attempt <= 3; attempt += 1) {
    const trigger = (await combobox.count().catch(() => 0)) > 0 ? combobox : matSelect;
    await clickMarked(trigger, { timeout: 5_000, force: true });

    const option = overlayOptions.filter({ hasText: optionText }).last();
    await expect(option).toBeVisible({ timeout: 10_000 });
    await option.scrollIntoViewIfNeeded().catch(() => undefined);
    await clickMarked(option, { timeout: 5_000, force: true });
    await page.keyboard.press("Escape").catch(() => undefined);

    try {
      await expect(field).toContainText(selectedText, { timeout: 5_000 });
      return;
    } catch {
      lastFieldText = ((await field.textContent().catch(() => "")) ?? "").replace(/\s+/g, " ").trim();
      await page.waitForTimeout(500);
    }
  }

  throw new Error(
    `Material select ${label} did not keep option ${optionText}; last visible field text was '${lastFieldText}'.`,
  );
}

async function parseVocabularyList(response: Response): Promise<VocabularyRecord[]> {
  try {
    const payload = await response.json();
    return Array.isArray(payload) ? payload : [];
  } catch {
    return [];
  }
}

function parseJsonSchema(value: unknown): Record<string, unknown> | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" ? parsed : undefined;
  } catch {
    return undefined;
  }
}

test("14 AI Model Hub DAIMO Vocabulary: machine-learning schema is created from INESData UI", async ({
  page,
  request,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  test.skip(dataspaceRuntime.adapter !== "inesdata", "This demo validates the INESData connector UI path.");

  const suffix = `${Date.now()}`;
  const vocabularyId = `qa-ui-amh-daimo-vocabulary-${suffix}`;
  const vocabularyName = `AI Model Hub DAIMO vocabulary ${suffix}`;
  const schemaText = JSON.stringify(DAIMO_SCHEMA, null, 2);
  const browserDiagnostics = collectBrowserDiagnostics(page);
  const loginPage = new KeycloakLoginPage(page, {
    portalUser: dataspaceRuntime.provider.username,
    portalPassword: dataspaceRuntime.provider.password,
    skipLogin: false,
  });
  const shellPage = new ConnectorShellPage(page);
  const report: AIModelDaimoVocabularyReport = {
    startedAt: new Date().toISOString(),
    connector: dataspaceRuntime.provider.connectorName,
    portalBaseUrl: dataspaceRuntime.provider.portalBaseUrl,
    vocabularyId,
    vocabularyName,
    linkedCases: ["PT5-MH-02", "PT5-MH-06", "PT5-MH-17", "AMH-DAIMO-VOCAB-01", "DS-UI-AMH-DAIMO-01"],
    errorResponses: [],
    fatalErrorResponses: [],
  };

  page.on("response", (response) => {
    const url = response.url();
    if (response.status() >= 400 && isVocabularyIntegrationUrl(url)) {
      report.errorResponses.push({ url, status: response.status() });
    }
  });

  try {
    const configResponse = await request.get(runtimeConfigUrl(dataspaceRuntime.provider.portalBaseUrl));
    expect(configResponse.ok(), "The connector UI runtime config is not available").toBeTruthy();
    const config = await configResponse.json();
    const runtimeConfig = config.runtime ?? config;
    const participantId = String(runtimeConfig.participantId || dataspaceRuntime.provider.connectorName);
    report.runtimeConfig = { participantId };
    await attachJson("ai-model-daimo-vocabulary-runtime-config", report.runtimeConfig);

    await loginPage.open(dataspaceRuntime.provider.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await shellPage.expectReady();
    await captureStep(page, "01-ai-model-daimo-vocabulary-after-login");

    await shellPage.navigateToSection(/^\s*Vocabularies\s*$/i, vocabulariesUrl(dataspaceRuntime.provider.portalBaseUrl));
    await shellPage.assertNoGateway403("Vocabularies page");
    await shellPage.assertNoServerErrorBanner("Vocabularies page");
    await expect(page.getByText(/Create vocabulary/i).first()).toBeVisible({ timeout: 20_000 });
    await captureStep(page, "02-ai-model-daimo-vocabulary-list");

    await page.goto(createVocabularyUrl(dataspaceRuntime.provider.portalBaseUrl), { waitUntil: "domcontentloaded" });
    await expect(page.getByText(/Create a vocabulary/i).first()).toBeVisible({ timeout: 20_000 });

    await fillMarked(formControl(page, /^ID$/i), vocabularyId);
    await fillMarked(formControl(page, /^Name$/i), vocabularyName);
    await selectMaterialOption(page, /Asset category/i, /Machine learning/i, /Machine learning/i);
    await fillMarked(formControl(page, /Schema \(JSON\)/i), schemaText);
    await captureStep(page, "03-ai-model-daimo-vocabulary-filled");

    const createResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url().includes("/management/vocabularies"),
      { timeout: 45_000 },
    );
    const sharedVocabularyResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url().includes("/connector-vocabularies/request") &&
        response.status() === 200,
      { timeout: 60_000 },
    );

    await clickMarked(page.locator("button").filter({ hasText: /Create/i }).last());

    const createResponse = await createResponsePromise;
    report.createResponse = {
      url: createResponse.url(),
      status: createResponse.status(),
    };
    expect(
      [200, 201, 204],
      `Vocabulary create returned HTTP ${createResponse.status()} at ${createResponse.url()}`,
    ).toContain(createResponse.status());

    await expect(page).toHaveURL(/\/vocabularies\/?$/i, { timeout: 30_000 });
    const sharedVocabularyResponse = await sharedVocabularyResponsePromise;
    const vocabularyRecords = await parseVocabularyList(sharedVocabularyResponse);
    const persistedVocabulary = vocabularyRecords.find(
      (vocabulary) => vocabularyIdentifier(vocabulary) === vocabularyId,
    );
    report.sharedVocabularyResponse = {
      url: sharedVocabularyResponse.url(),
      status: sharedVocabularyResponse.status(),
      itemCount: vocabularyRecords.length,
    };
    report.persistedVocabulary = persistedVocabulary;

    expect(persistedVocabulary, `Vocabulary ${vocabularyId} is not visible in the shared vocabulary list`).toBeTruthy();
    expect.soft(persistedVocabulary?.name).toBe(vocabularyName);
    expect.soft(persistedVocabulary?.category).toBe("machineLearning");
    expect.soft(persistedVocabulary?.connectorId).toBe(participantId);
    const persistedSchema = parseJsonSchema(persistedVocabulary?.jsonSchema);
    expect.soft(persistedSchema?.title).toBe(DAIMO_SCHEMA.title);
    expect
      .soft((persistedSchema?.properties as Record<string, unknown> | undefined)?.["daimo:inference_path"])
      .toBeTruthy();

    const vocabularyCard = page.locator("mat-card").filter({ hasText: vocabularyName }).first();
    await expect(vocabularyCard).toBeVisible({ timeout: 30_000 });
    await clickMarked(vocabularyCard.getByRole("button", { name: /View json schema/i }).first());
    const schemaDialog = page.locator("mat-dialog-container, mat-mdc-dialog-container").filter({ hasText: vocabularyName }).first();
    await expect(schemaDialog).toBeVisible({ timeout: 10_000 });
    await expect(schemaDialog.getByText(/JSON Schema/i).first()).toBeVisible({ timeout: 10_000 });
    await captureStep(page, "04-ai-model-daimo-vocabulary-schema");
    await page.keyboard.press("Escape");

    await page.goto(assetCreateUrl(dataspaceRuntime.provider.portalBaseUrl), { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => undefined);
    await expect(page.getByText(/Create an asset/i).first()).toBeVisible({ timeout: 20_000 });
    await selectMaterialOption(page, /Asset type/i, /Machine learning/i, /Machine learning/i);
    await expect(page.getByRole("tab", { name: /Detailed information/i })).toBeVisible({ timeout: 20_000 });
    await clickMarked(page.getByRole("tab", { name: /Detailed information/i }), { force: true });
    await expect(page.getByRole("tab", { name: /Machine learning information/i })).toBeVisible({ timeout: 20_000 });
    await clickMarked(page.getByRole("tab", { name: /Machine learning information/i }), { force: true });
    await clickMarked(formField(page, /^Vocabularies$/i).locator("mat-select").first(), { force: true });
    await expect(page.getByRole("option", { name: vocabularyName }).first()).toBeVisible({ timeout: 20_000 });
    await clickMarked(page.getByRole("option", { name: vocabularyName }).first(), { force: true });
    await page.keyboard.press("Escape");
    await expect(formField(page, /^Vocabularies$/i)).toContainText(vocabularyName, { timeout: 20_000 });
    report.assetCreateVocabularyCheck = {
      url: page.url(),
      assetType: "machineLearning",
      vocabularyName,
      status: "passed",
    };
    await attachJson("ai-model-daimo-vocabulary-asset-create-check", report.assetCreateVocabularyCheck);
    await captureStep(page, "05-ai-model-daimo-vocabulary-asset-create");

    report.fatalErrorResponses = report.errorResponses;
    expect(
      report.fatalErrorResponses,
      `Vocabulary API calls returned fatal errors: ${JSON.stringify(report.fatalErrorResponses)}`,
    ).toHaveLength(0);
  } finally {
    const browserDiagnosticsSnapshot = browserDiagnostics.snapshot();
    browserDiagnostics.dispose();
    await attachJson("ai-model-daimo-vocabulary-browser-diagnostics", browserDiagnosticsSnapshot);
    await attachJson("ai-model-daimo-vocabulary-report", {
      ...report,
      finishedAt: new Date().toISOString(),
      browserDiagnostics: {
        eventCount: browserDiagnosticsSnapshot.eventCount,
        droppedEventCount: browserDiagnosticsSnapshot.droppedEventCount,
      },
    });
  }
});
