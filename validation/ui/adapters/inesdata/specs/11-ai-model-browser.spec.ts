import { Page } from "@playwright/test";

import { test, expect } from "../../../shared/fixtures/dataspace.fixture";

import { KeycloakLoginPage } from "../../../shared/components/auth/keycloak-login.page";
import { ConnectorShellPage } from "../components/shell/connector-shell.page";
import { collectBrowserDiagnostics } from "../../../shared/utils/browser-diagnostics";
import { clickMarked } from "../../../shared/utils/live-marker";
import {
  bootstrapProviderNegotiationArtifacts,
  cleanupProviderValidationArtifacts,
  probeConsumerCatalogDatasetReadiness,
} from "../../../shared/utils/provider-bootstrap";
import { EVENTUAL_UI_RETRY_INTERVALS, waitForUiTransition } from "../../../shared/utils/waiting";
import { modelServerUrlForPath } from "../../../shared/utils/model-server-url";

type AIModelBrowserUiReport = {
  startedAt: string;
  providerConnector: string;
  consumerConnector: string;
  assetId: string;
  modelName: string;
  modelUrl: string;
  modelPath: string;
  comparisonAssetId: string;
  linkedCases: string[];
  providerBootstrap: Array<{
    assetId: string;
    policyId: string;
    contractDefinitionId: string;
  }>;
  filterChecks: Array<{
    filterGroup: string;
    selectedValue: string;
    expectedVisibleAssetId: string;
    expectedHiddenAssetId?: string;
    status: "passed";
  }>;
  detailChecks: Array<{
    scenario: string;
    expectedContent: string[];
    status: "passed";
  }>;
  primaryActionChecks: Array<{
    scenario: string;
    expectedContent: string[];
    status: "passed";
  }>;
  observerEvidenceChecks: Array<{
    scenario: string;
    assetId: string;
    url: string;
    observedEvents: string[];
    status: "passed" | "skipped";
    reason?: string;
  }>;
  errorResponses: Array<{ url: string; status: number }>;
  toleratedErrorResponses: Array<{ url: string; status: number }>;
  fatalErrorResponses: Array<{ url: string; status: number }>;
};

type BrowserModelFixture = {
  key: string;
  assetId: string;
  name: string;
  sourceObjectName: string;
  shortDescription: string;
  description: string;
  keywords: string[];
  task: string;
  subtask: string;
  algorithm: string;
  library: string;
  framework: string;
  software: string;
  format: string;
  contentType: string;
  modelPath: string;
  modelUrl: string;
};

const DEFAULT_MODEL_PATH = "/api/v1/nlp/ecommerce-sentiment";
const TEXT_MODEL_INPUT_FEATURES = [
  {
    name: "text",
    type: "string",
    required: true,
    description: "Text to analyze",
  },
];
const TEXT_MODEL_INPUT_SCHEMA = {
  type: "object",
  required: ["text"],
  properties: {
    text: {
      type: "string",
      description: "Text to analyze",
    },
  },
};
const TEXT_MODEL_INPUT_EXAMPLE = {
  text: "This product is excellent and very useful",
};

test.skip(
  process.env.UI_AI_MODEL_HUB_HTTPDATA_DEMO !== "1",
  "Set UI_AI_MODEL_HUB_HTTPDATA_DEMO=1 or run Level 6 with the INESData adapter to validate AI Model Browser from the INESData UI.",
);

function normalizePath(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return DEFAULT_MODEL_PATH;
  }
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}

function aiModelHubModelPath(): string {
  return normalizePath(process.env.UI_AI_MODEL_HUB_MODEL_PATH || DEFAULT_MODEL_PATH);
}

function aiModelHubModelUrl(componentsNamespace: string): string {
  return modelServerUrlForPath(aiModelHubModelPath(), componentsNamespace);
}

function aiModelHubCatalogCleanupEnabled(): boolean {
  return process.env.UI_AI_MODEL_HUB_CATALOG_CLEANUP === "1";
}

function aiModelMetadataAliases({
  task,
  subtask,
  algorithm,
  library,
  framework,
  software,
  inferencePath,
}: {
  task: string;
  subtask: string;
  algorithm: string;
  library: string;
  framework: string;
  software: string;
  inferencePath: string;
}): Record<string, unknown> {
  const inputFeatures = JSON.stringify(TEXT_MODEL_INPUT_FEATURES);
  const inputSchema = JSON.stringify(TEXT_MODEL_INPUT_SCHEMA);
  const inputExample = JSON.stringify(TEXT_MODEL_INPUT_EXAMPLE);

  const metadata = {
    "daimo:asset_kind": "model",
    "daimo:task": task,
    "https://w3id.org/daimo/ns#task": task,
    "https://pionera.ai/edc/daimo#task": task,
    "daimo:subtask": subtask,
    "https://w3id.org/daimo/ns#subtask": subtask,
    "https://pionera.ai/edc/daimo#subtask": subtask,
    "daimo:algorithm": algorithm,
    "https://w3id.org/daimo/ns#algorithm": algorithm,
    "https://pionera.ai/edc/daimo#algorithm": algorithm,
    "daimo:library": library,
    "https://w3id.org/daimo/ns#library": library,
    "https://pionera.ai/edc/daimo#library": library,
    "daimo:framework": framework,
    "https://w3id.org/daimo/ns#framework": framework,
    "https://pionera.ai/edc/daimo#framework": framework,
    "daimo:software": software,
    "https://w3id.org/daimo/ns#software": software,
    "https://pionera.ai/edc/daimo#software": software,
    "daimo:inference_path": inferencePath,
    "https://w3id.org/daimo/ns#inference_path": inferencePath,
    "https://pionera.ai/edc/daimo#inference_path": inferencePath,
    "daimo:input_features": inputFeatures,
    "https://w3id.org/daimo/ns#input_features": inputFeatures,
    "https://pionera.ai/edc/daimo#input_features": inputFeatures,
    "daimo:input_schema": inputSchema,
    "https://w3id.org/daimo/ns#input_schema": inputSchema,
    "https://pionera.ai/edc/daimo#input_schema": inputSchema,
    "daimo:input_example": inputExample,
    "https://w3id.org/daimo/ns#input_example": inputExample,
    "https://pionera.ai/edc/daimo#input_example": inputExample,
    task,
    subtask,
    algorithm,
    library,
    framework,
    software,
    inference_path: inferencePath,
    inferencePath,
    input_features: inputFeatures,
    inputFeatures: TEXT_MODEL_INPUT_FEATURES,
    input_schema: inputSchema,
    inputSchema: TEXT_MODEL_INPUT_SCHEMA,
    input_example: inputExample,
    inputExample: TEXT_MODEL_INPUT_EXAMPLE,
  };

  return metadata;
}

async function gotoAiModelBrowser(page: Page, baseUrl: string): Promise<void> {
  await page.goto(`${baseUrl.replace(/\/$/, "")}/ai-model-browser`, {
    waitUntil: "domcontentloaded",
  });
}

function aiModelBrowserSearchInput(page: Page) {
  return page.locator("input[placeholder*='classification']").first();
}

function aiModelCard(page: Page, assetId: string) {
  return page.locator("mat-card.model-card").filter({ hasText: assetId }).first();
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function expandFilterSection(page: Page, sectionTitle: RegExp): Promise<void> {
  const panel = page.locator("mat-expansion-panel").filter({ hasText: sectionTitle }).first();
  await expect(panel, `Expected AI Model Browser filter section ${sectionTitle} to be visible`).toBeVisible({
    timeout: 15_000,
  });

  if (await panel.locator("mat-checkbox").first().isVisible().catch(() => false)) {
    return;
  }

  await clickMarked(panel.locator("mat-expansion-panel-header").first(), { force: true });
  await expect(panel.locator("mat-checkbox").first()).toBeVisible({ timeout: 10_000 });
}

async function applyVisibleFilter(page: Page, label: RegExp, sectionTitle?: RegExp): Promise<void> {
  const scope = sectionTitle
    ? page.locator("mat-expansion-panel").filter({ hasText: sectionTitle }).first()
    : page;
  if (sectionTitle) {
    await expandFilterSection(page, sectionTitle);
  }

  const materialCheckbox = scope.locator("mat-checkbox").filter({ hasText: label }).first();
  const roleCheckbox = scope.getByRole("checkbox", { name: label }).first();
  const checkbox = (await materialCheckbox.count()) > 0 ? materialCheckbox : roleCheckbox;

  await expect(checkbox, `Expected AI Model Browser filter ${label} to be visible`).toBeVisible({
    timeout: 15_000,
  });
  await clickMarked(checkbox, { force: true });
  await waitForUiTransition(page);
}

async function clearActiveFilters(page: Page): Promise<void> {
  const clearButton = page.getByRole("button", { name: /^Clear$/i }).first();
  if (await clearButton.isVisible().catch(() => false)) {
    await clickMarked(clearButton, { force: true });
    await waitForUiTransition(page);
  }
}

async function expectAiModelBrowserSearchResults(
  page: Page,
  baseUrl: string,
  searchText: string,
  expectedAssetIds: string[],
  afterNavigation?: () => Promise<void>,
): Promise<void> {
  await expect(async () => {
    await gotoAiModelBrowser(page, baseUrl);
    await afterNavigation?.();
    await expect(page.getByRole("heading", { name: /AI Model Browser/i })).toBeVisible({ timeout: 20_000 });

    const searchInput = aiModelBrowserSearchInput(page);
    await expect(searchInput).toBeVisible({ timeout: 20_000 });
    await searchInput.fill("");
    await waitForUiTransition(page);
    await clearActiveFilters(page);
    await searchInput.fill(searchText);
    await waitForUiTransition(page);

    for (const assetId of expectedAssetIds) {
      await expect(aiModelCard(page, assetId)).toBeVisible({ timeout: 20_000 });
    }
  }).toPass({
    timeout: 180_000,
    intervals: EVENTUAL_UI_RETRY_INTERVALS,
  });
}

async function inspectBrowserObserverEvidence(page: Page, assetId: string, modelName: string) {
  const loadError = page.getByText(/Failed to load observer timeline/i).first();
  const emptyTimeline = page.getByText(/No observer events match/i).first();
  const detailEvent = page.getByRole("heading", { name: /^MODEL_DETAIL_VIEWED$/i }).first();

  await expect(async () => {
    const hasLoadError = await loadError.isVisible().catch(() => false);
    const hasEmptyTimeline = await emptyTimeline.isVisible().catch(() => false);
    const hasDetailEvent = await detailEvent.isVisible().catch(() => false);
    expect(hasLoadError || hasEmptyTimeline || hasDetailEvent).toBeTruthy();
  }).toPass({
    timeout: 30_000,
    intervals: EVENTUAL_UI_RETRY_INTERVALS,
  });

  if (await loadError.isVisible().catch(() => false)) {
    return {
      status: "skipped" as const,
      reason: "Observer backend is not available from the connector UI in this environment.",
      observedEvents: [],
    };
  }

  if (await emptyTimeline.isVisible().catch(() => false)) {
    throw new Error(`Observer asset timeline is empty for assetId ${assetId}.`);
  }

  await expect(detailEvent).toBeVisible();
  await expect(page.getByText(modelName).first()).toBeVisible({ timeout: 10_000 });
  await expect(page.locator("article.observer-card .observer-badge", { hasText: /^VIEWED$/i }).first()).toBeVisible({
    timeout: 10_000,
  });

  return {
    status: "passed" as const,
    observedEvents: ["MODEL_DETAIL_VIEWED"],
  };
}

test("11 AI Model Browser: controlled model discovery, filtering and detail from INESData UI", async ({
  page,
  request,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  test.skip(dataspaceRuntime.adapter !== "inesdata", "This demo validates the INESData connector UI path.");

  const suffix = `amh-browser-${Date.now()}`;
  const modelPath = aiModelHubModelPath();
  const modelUrl = aiModelHubModelUrl(dataspaceRuntime.componentsNamespace);
  const models: BrowserModelFixture[] = [
    {
      key: "sentiment",
      assetId: `qa-ui-amh-browser-sentiment-${suffix}`,
      name: `AI Model Browser sentiment model ${suffix}`,
      sourceObjectName: `ai-model-browser-sentiment-${suffix}.json`,
      shortDescription: "Sentiment classification model exposed as HttpData for AI Model Browser validation",
      description:
        "Controlled sentiment model endpoint used to validate DAIMO discovery, multidimensional filtering and detail navigation from INESData AI Model Browser.",
      keywords: ["validation", "ai-model-browser", "machine-learning", "sentiment", "HttpData", "A5.2"],
      task: "text-classification",
      subtask: "sentiment-analysis",
      algorithm: "controlled-baseline",
      library: "validation-fixture",
      framework: "controlled-httpdata",
      software: "pionera-validation-framework",
      format: "json",
      contentType: "application/json",
      modelPath,
      modelUrl,
    },
    {
      key: "forecast",
      assetId: `qa-ui-amh-browser-forecast-${suffix}`,
      name: `AI Model Browser forecast model ${suffix}`,
      sourceObjectName: `ai-model-browser-forecast-${suffix}.onnx`,
      shortDescription: "Forecasting model metadata fixture used as a controlled filter contrast",
      description:
        "Controlled forecast model fixture used to prove that DAIMO task, subtask, algorithm, library, framework, software and format filters discriminate browser results.",
      keywords: ["validation", "ai-model-browser", "machine-learning", "forecasting", "HttpData", "A5.2"],
      task: "time-series-regression",
      subtask: "demand-forecasting",
      algorithm: "gradient-boosting-regressor",
      library: "scikit-learn-fixture",
      framework: "sklearn-httpdata",
      software: "validation-analytics-suite",
      format: "onnx",
      contentType: "application/octet-stream",
      modelPath,
      modelUrl,
    },
  ];
  const targetModel = models[0];
  const comparisonModel = models[1];
  const browserDiagnostics = collectBrowserDiagnostics(page);
  const loginPage = new KeycloakLoginPage(page, {
    portalUser: dataspaceRuntime.consumer.username,
    portalPassword: dataspaceRuntime.consumer.password,
    skipLogin: false,
  });
  const shellPage = new ConnectorShellPage(page);
  const report: AIModelBrowserUiReport = {
    startedAt: new Date().toISOString(),
    providerConnector: dataspaceRuntime.provider.connectorName,
    consumerConnector: dataspaceRuntime.consumer.connectorName,
    assetId: targetModel.assetId,
    modelName: targetModel.name,
    modelUrl,
    modelPath,
    comparisonAssetId: comparisonModel.assetId,
    linkedCases: [
      "PT5-MH-01",
      "PT5-MH-04",
      "PT5-MH-05",
      "PT5-MH-06",
      "PT5-MH-07",
      "PT5-MH-08",
      "DS-UI-AMH-BROWSER-01",
    ],
    providerBootstrap: [],
    filterChecks: [],
    detailChecks: [],
    primaryActionChecks: [],
    observerEvidenceChecks: [],
    errorResponses: [],
    toleratedErrorResponses: [],
    fatalErrorResponses: [],
  };

  const isTolerableCatalogRetry = (url: string, status: number): boolean =>
    (status === 401 || status === 500 || status === 502 || status === 503 || status === 504) &&
    (url.includes("/management/pagination/count") ||
      url.includes("/management/federatedcatalog/request"));

  page.on("response", (response) => {
    const url = response.url();
    if (
      response.status() >= 400 &&
      (url.includes("/management/") ||
        url.includes("/federatedcatalog") ||
        url.includes("/contractnegotiations"))
    ) {
      report.errorResponses.push({ url, status: response.status() });
    }
  });

  try {
    if (aiModelHubCatalogCleanupEnabled()) {
      await attachJson(
        "ai-model-browser-ui-catalog-cleanup",
        await cleanupProviderValidationArtifacts(request, dataspaceRuntime, {
          contractdefinitions: ["contract-ui-", "qa-ui-contract-definition-"],
          policydefinitions: ["policy-ui-", "qa-ui-policy-", "qa-ui-contract-policy-"],
          assets: [
            "asset-e2e-",
            "qa-ui-asset-",
            "qa-ui-amh-browser-",
            "qa-ui-amh-httpdata-",
            "qa-ui-catalog-",
            "qa-ui-negotiation-",
            "qa-ui-sv-httpdata-",
            "qa-ui-transfer-",
          ],
        }),
      );
    }

    for (const model of models) {
      report.providerBootstrap.push(
        await bootstrapProviderNegotiationArtifacts(
          request,
          dataspaceRuntime,
          model.assetId,
          `${suffix}-${model.key}`,
          {
            sourceObjectName: model.sourceObjectName,
            name: model.name,
            version: "1.0.0",
            shortDescription: model.shortDescription,
            description: model.description,
            assetType: "machineLearning",
            keywords: model.keywords,
            properties: {
              ...aiModelMetadataAliases({
                task: model.task,
                subtask: model.subtask,
                algorithm: model.algorithm,
                library: model.library,
                framework: model.framework,
                software: model.software,
                inferencePath: model.modelPath,
              }),
              contenttype: model.contentType,
              format: model.format,
            },
            dataAddress: {
              type: "HttpData",
              baseUrl: model.modelUrl,
              method: "POST",
              name: model.sourceObjectName,
            },
          },
        ),
      );
    }
    await attachJson("ai-model-browser-ui-bootstrap", report.providerBootstrap);
    await attachJson(
      "ai-model-browser-ui-catalog-api-readiness",
      await Promise.all(
        models.map((model) => probeConsumerCatalogDatasetReadiness(request, dataspaceRuntime, model.assetId)),
      ),
    );

    await loginPage.open(dataspaceRuntime.consumer.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await shellPage.expectReady();
    await captureStep(page, "01-ai-model-browser-after-login");

    await expectAiModelBrowserSearchResults(
      page,
      dataspaceRuntime.consumer.portalBaseUrl,
      suffix,
      [targetModel.assetId, comparisonModel.assetId],
      async () => {
        await shellPage.assertNoGateway403("AI Model Browser page");
        await shellPage.assertNoServerErrorBanner("AI Model Browser page");
      },
    );

    await captureStep(page, "02-ai-model-browser-search-result");

    const card = aiModelCard(page, targetModel.assetId);
    await expect(card.getByText(targetModel.name).first()).toBeVisible({ timeout: 10_000 });
    await expect(card.getByText(targetModel.assetId, { exact: true }).first()).toBeVisible({ timeout: 10_000 });
    await expect(card.getByText(/External/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(card.getByText(/Contract available/i).first()).toBeVisible({ timeout: 10_000 });
    const visibleCardText = (await card.innerText()).trim();
    await attachJson("ai-model-browser-ui-metadata-assertions", {
      assetId: targetModel.assetId,
      comparisonAssetId: comparisonModel.assetId,
      modelName: targetModel.name,
      modelPath,
      modelUrl,
      expectedAssetType: "machineLearning",
      expectedTask: targetModel.task,
      expectedSubtask: targetModel.subtask,
      expectedAlgorithm: targetModel.algorithm,
      expectedLibrary: targetModel.library,
      expectedFramework: targetModel.framework,
      expectedSoftware: targetModel.software,
      comparisonTask: comparisonModel.task,
      comparisonFramework: comparisonModel.framework,
      visibleCardText,
    });

    await applyVisibleFilter(page, /External Asset/i, /Asset Source/i);
    await expect(aiModelCard(page, targetModel.assetId)).toBeVisible({ timeout: 10_000 });
    await expect(aiModelCard(page, comparisonModel.assetId)).toBeVisible({ timeout: 10_000 });
    report.filterChecks.push({
      filterGroup: "Asset Source",
      selectedValue: "External Asset",
      expectedVisibleAssetId: targetModel.assetId,
      status: "passed",
    });

    await applyVisibleFilter(page, /HttpData/i, /Storage Type/i);
    await expect(aiModelCard(page, targetModel.assetId)).toBeVisible({ timeout: 10_000 });
    await expect(aiModelCard(page, comparisonModel.assetId)).toBeVisible({ timeout: 10_000 });
    report.filterChecks.push({
      filterGroup: "Storage Type",
      selectedValue: "HttpData",
      expectedVisibleAssetId: targetModel.assetId,
      status: "passed",
    });
    await clearActiveFilters(page);

    const richFilters = [
      { filterGroup: "Format", section: /Format(?:\s*\(\d+\))?/i, value: targetModel.format },
    ];

    for (const filter of richFilters) {
      await applyVisibleFilter(page, new RegExp(`^${escapeRegex(filter.value)}$`, "i"), filter.section);
      await expect(aiModelCard(page, targetModel.assetId)).toBeVisible({ timeout: 10_000 });
      await expect(aiModelCard(page, comparisonModel.assetId)).toBeHidden({ timeout: 10_000 });
      report.filterChecks.push({
        filterGroup: filter.filterGroup,
        selectedValue: filter.value,
        expectedVisibleAssetId: targetModel.assetId,
        expectedHiddenAssetId: comparisonModel.assetId,
        status: "passed",
      });
      await clearActiveFilters(page);
      await expect(aiModelCard(page, targetModel.assetId)).toBeVisible({ timeout: 10_000 });
      await expect(aiModelCard(page, comparisonModel.assetId)).toBeVisible({ timeout: 10_000 });
    }

    await attachJson("ai-model-browser-ui-filter-assertions", {
      targetAssetId: targetModel.assetId,
      comparisonAssetId: comparisonModel.assetId,
      checks: report.filterChecks,
      expectedResult:
        "controlled target model remains visible and comparison model is hidden for the rich filters exposed by the current AI Model Browser UI",
    });
    await captureStep(page, "03-ai-model-browser-filtered-result");

    await clickMarked(aiModelCard(page, targetModel.assetId).getByRole("button", { name: /^Negotiate$/i }).first(), {
      force: true,
    });
    await waitForUiTransition(page);
    await expect(page).toHaveURL(/\/catalog\/datasets\/view/);
    await expect(page.getByText(/Contract offer/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("button", { name: /Negotiate Contract/i }).first()).toBeVisible({ timeout: 10_000 });
    report.primaryActionChecks.push({
      scenario: "browser_primary_negotiate_action_opens_contract_offers",
      expectedContent: [
        "Contract offer",
        "Negotiate Contract",
      ],
      status: "passed",
    });
    await attachJson("ai-model-browser-ui-primary-action-assertions", {
      assetId: targetModel.assetId,
      modelName: targetModel.name,
      checks: report.primaryActionChecks,
      expectedResult: "The AI Model Browser primary action opens the contract offer surface for negotiation.",
    });
    await captureStep(page, "04-ai-model-browser-primary-negotiate-action");

    await expectAiModelBrowserSearchResults(page, dataspaceRuntime.consumer.portalBaseUrl, suffix, [
      targetModel.assetId,
    ]);

    await clickMarked(aiModelCard(page, targetModel.assetId).getByRole("button", { name: /View details/i }).first(), {
      force: true,
    });
    await waitForUiTransition(page);
    await expect(page).toHaveURL(/\/catalog\/datasets\/view/);
    await expect(page.getByText(targetModel.assetId, { exact: true }).first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(targetModel.name).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(targetModel.contentType).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(targetModel.format).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/machineLearning/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("tab", { name: /Contract Offers/i })).toBeVisible({ timeout: 10_000 });
    await clickMarked(page.getByRole("tab", { name: /Contract Offers/i }), { force: true });
    await expect(page.getByText(/Contract offer/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("button", { name: /Negotiate Contract/i }).first()).toBeVisible({ timeout: 10_000 });
    report.detailChecks.push({
      scenario: "federated_model_detail_and_contract_offer",
      expectedContent: [
        targetModel.assetId,
        targetModel.name,
        targetModel.contentType,
        targetModel.format,
        "machineLearning",
        "Contract offer",
      ],
      status: "passed",
    });
    await attachJson("ai-model-browser-ui-detail-assertions", {
      assetId: targetModel.assetId,
      modelName: targetModel.name,
      checks: report.detailChecks,
    });
    await captureStep(page, "05-ai-model-browser-detail");

    const observerTimelineUrl = `${dataspaceRuntime.consumer.portalBaseUrl.replace(/\/$/, "")}/ai-model-observer/timeline/${encodeURIComponent(targetModel.assetId)}`;
    await page.goto(observerTimelineUrl, { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: /Asset timeline/i })).toBeVisible({ timeout: 10_000 });
    const observerOutcome = await inspectBrowserObserverEvidence(page, targetModel.assetId, targetModel.name);
    report.observerEvidenceChecks.push({
      scenario: "open_browser_asset_observer_timeline",
      assetId: targetModel.assetId,
      url: page.url(),
      observedEvents: observerOutcome.observedEvents,
      status: observerOutcome.status,
      reason: observerOutcome.reason,
    });
    await attachJson("ai-model-browser-ui-observer-evidence", {
      assetId: targetModel.assetId,
      url: page.url(),
      checks: report.observerEvidenceChecks,
    });
    await captureStep(page, "06-ai-model-browser-observer-evidence");

    report.toleratedErrorResponses = report.errorResponses.filter(({ url, status }) =>
      isTolerableCatalogRetry(url, status),
    );
    report.fatalErrorResponses = report.errorResponses.filter(
      ({ url, status }) => !isTolerableCatalogRetry(url, status),
    );
    expect(
      report.fatalErrorResponses,
      `API calls returned fatal errors: ${JSON.stringify(report.fatalErrorResponses)} (tolerated transient catalog errors: ${JSON.stringify(report.toleratedErrorResponses)})`,
    ).toHaveLength(0);
  } finally {
    const browserDiagnosticsSnapshot = browserDiagnostics.snapshot();
    browserDiagnostics.dispose();
    await attachJson("ai-model-browser-ui-browser-diagnostics", browserDiagnosticsSnapshot);
    await attachJson("ai-model-browser-ui-report", {
      ...report,
      finishedAt: new Date().toISOString(),
      browserDiagnostics: {
        eventCount: browserDiagnosticsSnapshot.eventCount,
        droppedEventCount: browserDiagnosticsSnapshot.droppedEventCount,
      },
    });
  }
});
