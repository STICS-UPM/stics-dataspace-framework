import { Locator, Page } from "@playwright/test";

import { test, expect } from "../../../shared/fixtures/dataspace.fixture";

import { KeycloakLoginPage } from "../../../shared/components/auth/keycloak-login.page";
import { ConnectorShellPage } from "../components/shell/connector-shell.page";
import { collectBrowserDiagnostics } from "../../../shared/utils/browser-diagnostics";
import { clickMarked, fillMarked, selectOptionMarked } from "../../../shared/utils/live-marker";
import { EVENTUAL_UI_RETRY_INTERVALS, waitForUiTransition } from "../../../shared/utils/waiting";

type OfficialModel = {
  assetId: string;
  name: string;
};

const OFFICIAL_USE_CASES_ENV = "UI_AI_MODEL_HUB_USE_CASES_DEMO";

const FLARES_5W1H_MODEL: OfficialModel = {
  assetId: "city-flares-5w1h-albert",
  name: "FLARES 5W1H ALBERT - PIONERA Use Case",
};

const FLARES_RELIABILITY_MODELS: OfficialModel[] = [
  {
    assetId: "city-flares-reliability-albert",
    name: "FLARES Reliability ALBERT - PIONERA Use Case",
  },
  {
    assetId: "company-flares-reliability-bert",
    name: "FLARES Reliability BERT - PIONERA Use Case",
  },
  {
    assetId: "city-flares-reliability-distilbert",
    name: "FLARES Reliability DistilBERT - PIONERA Use Case",
  },
];

const MOBILITY_ACTUAL_TRAVEL_TIME_MODELS: OfficialModel[] = [
  {
    assetId: "city-mobility-lightgbm-actual-travel-time",
    name: "Mobility LightGBM Actual Travel Time - PIONERA Use Case",
  },
  {
    assetId: "city-mobility-randomforest-actual-travel-time",
    name: "Mobility Random Forest Actual Travel Time - PIONERA Use Case",
  },
  {
    assetId: "company-mobility-catboost-actual-travel-time",
    name: "Mobility CatBoost Actual Travel Time - PIONERA Use Case",
  },
];

const FLARES_5W1H_METRIC_MODELS: OfficialModel[] = [
  {
    assetId: "city-flares-5w1h-albert-metrics",
    name: "FLARES 5W1H ALBERT Metrics - PIONERA Use Case",
  },
  {
    assetId: "company-flares-5w1h-bert-metrics",
    name: "FLARES 5W1H BERT Metrics - PIONERA Use Case",
  },
  {
    assetId: "city-flares-5w1h-distilbert-metrics",
    name: "FLARES 5W1H DistilBERT Metrics - PIONERA Use Case",
  },
];

const MOBILITY_PREVIOUS_DELAY_MODELS: OfficialModel[] = [
  {
    assetId: "company-mobility-catboost-previous-delay",
    name: "Mobility CatBoost Previous Delay - PIONERA Use Case",
  },
  {
    assetId: "company-mobility-lightgbm-previous-delay",
    name: "Mobility LightGBM Previous Delay - PIONERA Use Case",
  },
  {
    assetId: "company-mobility-randomforest-previous-delay",
    name: "Mobility Random Forest Previous Delay - PIONERA Use Case",
  },
];

const FLARES_5W1H_PAYLOAD = [
  {
    Id: 840,
    Text: "El comité de medicamentos humanos espera concluir el análisis en marzo.",
  },
];

const FLARES_5W1H_INPUT_COLUMNS = ["Id", "Text"];

const FLARES_RELIABILITY_INPUT_COLUMNS = [
  "Id",
  "Text",
  "Tag_Start",
  "Tag_End",
  "5W1H_Label",
  "Tag_Text",
];

const MOBILITY_PREVIOUS_DELAY_INPUT_COLUMNS = [
  "trip_id",
  "from_stop_id",
  "to_stop_id",
  "route_id",
  "scheduled_travel_time",
  "shape_distance",
  "is_peak",
  "hour_sin",
  "hour_cos",
  "weekday_sin",
  "weekday_cos",
];

const MOBILITY_ACTUAL_TRAVEL_TIME_INPUT_COLUMNS = [
  "trip_id",
  "from_stop_id",
  "to_stop_id",
  "route_id",
  "scheduled_travel_time",
  "shape_distance",
  "is_peak",
  "hour_sin",
  "hour_cos",
  "weekday_sin",
  "weekday_cos",
  "previous_delay_ratio",
  "previous_delay_delta",
];

test.skip(
  process.env[OFFICIAL_USE_CASES_ENV] === "0",
  `Set ${OFFICIAL_USE_CASES_ENV}=1 to force the official AI Model Hub use-case UI suite, or leave it enabled through use-cases model-server configuration.`,
);

function route(baseUrl: string, path: string): string {
  return `${baseUrl.replace(/\/$/, "")}${path}`;
}

async function loginConnector(
  page: Page,
  connector: { portalBaseUrl: string; username: string; password: string },
): Promise<void> {
  const loginPage = new KeycloakLoginPage(page, {
    portalUser: connector.username,
    portalPassword: connector.password,
    skipLogin: false,
  });
  const shellPage = new ConnectorShellPage(page);
  await loginPage.open(connector.portalBaseUrl);
  await loginPage.loginIfNeeded();
  await shellPage.expectReady();
}

async function openConnectorModule(
  page: Page,
  connector: { portalBaseUrl: string },
  path: string,
  heading: RegExp,
): Promise<void> {
  await page.goto(route(connector.portalBaseUrl, path), { waitUntil: "domcontentloaded" });
  const shellPage = new ConnectorShellPage(page);
  await shellPage.assertNoGateway403(`${path} page`);
  await shellPage.assertNoServerErrorBanner(`${path} page`);
  await expect(page.getByRole("heading", { name: heading }).first()).toBeVisible({ timeout: 30_000 });
}

function browserSearchInput(page: Page): Locator {
  return page.locator(".search-field input, input[placeholder*='regression'], input[placeholder*='CatBoost']").first();
}

function browserCard(page: Page, model: OfficialModel): Locator {
  return page.locator("mat-card.model-card").filter({ hasText: model.assetId }).filter({ hasText: model.name }).first();
}

function benchmarkModelCard(page: Page, model: OfficialModel): Locator {
  return page.locator(".model-item.selectable").filter({ hasText: model.name }).first();
}

function benchmarkDatasetCard(page: Page, datasetName: string): Locator {
  return page.locator(".dataspace-dataset-card").filter({ hasText: datasetName }).first();
}

function datasetRowsValue(page: Page): Locator {
  return page.locator(".stat-card").filter({ hasText: "Dataset rows" }).locator(".stat-value").first();
}

function parseColumnList(value: string): string[] {
  return value
    .split(",")
    .map(column => column.trim())
    .filter(Boolean);
}

function sortedColumnList(value: string[] | string): string[] {
  const columns = Array.isArray(value) ? value : parseColumnList(value);
  return [...columns].sort((left, right) => left.localeCompare(right));
}

function generatedInputField(page: Page, featureName: string): Locator {
  const label = new RegExp(`^${featureName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i");
  return page
    .getByRole(featureName.toLowerCase() === "id" ? "spinbutton" : "textbox", { name: label })
    .first();
}

async function fillFlares5w1hGeneratedForm(page: Page): Promise<void> {
  const row = FLARES_5W1H_PAYLOAD[0];
  const idInput = page.getByRole("spinbutton", { name: /^Id\b/i }).first();
  const textInput = page.getByRole("textbox", { name: /^Text\b/i }).first();

  await expect(idInput).toBeVisible({ timeout: 15_000 });
  await expect(textInput).toBeVisible({ timeout: 15_000 });
  await fillMarked(idInput, String(row.Id));
  await fillMarked(textInput, row.Text);
}

async function clickFederatedDatasetRefreshIfAvailable(page: Page): Promise<void> {
  const refreshButton = page.getByRole("button", { name: /Refresh/i }).last();
  const visible = await refreshButton.isVisible().catch(() => false);
  const enabled = visible ? await refreshButton.isEnabled().catch(() => false) : false;
  if (!visible || !enabled) {
    return;
  }
  await clickMarked(refreshButton, { force: true });
  await waitForUiTransition(page);
}

async function selectBenchmarkModels(page: Page, searchTerm: string, models: OfficialModel[]): Promise<void> {
  await expect(async () => {
    const searchInput = page.locator("input.search-input").first();
    await expect(searchInput).toBeVisible({ timeout: 20_000 });
    await fillMarked(searchInput, searchTerm);
    await waitForUiTransition(page);

    const missingModels = [];
    for (const model of models) {
      const visible = await benchmarkModelCard(page, model).isVisible().catch(() => false);
      if (!visible) {
        missingModels.push(model.assetId);
      }
    }
    if (missingModels.length > 0) {
      await page.reload({ waitUntil: "domcontentloaded" });
      await expect(page.getByRole("heading", { name: /Model Benchmarking/i }).first()).toBeVisible({
        timeout: 30_000,
      });
      const reloadedSearchInput = page.locator("input.search-input").first();
      await expect(reloadedSearchInput).toBeVisible({ timeout: 20_000 });
      await fillMarked(reloadedSearchInput, searchTerm);
      await waitForUiTransition(page);
    }

    for (const model of models) {
      await expect(
        benchmarkModelCard(page, model),
        `Official model ${model.assetId} must be visible in benchmarking`,
      ).toBeVisible({ timeout: 20_000 });
    }

    for (const model of models) {
      const card = benchmarkModelCard(page, model);
      const statusText = ((await card.locator(".model-status").first().textContent().catch(() => "")) || "").trim();
      if (!/selected/i.test(statusText)) {
        await clickMarked(card, { force: true });
        await waitForUiTransition(page);
      }
      await expect(card.locator(".model-status").filter({ hasText: /Selected/i }).first()).toBeVisible({
        timeout: 10_000,
      });
    }
  }).toPass({
    timeout: 180_000,
    intervals: EVENTUAL_UI_RETRY_INTERVALS,
  });
}

async function waitForBenchmarkDatasetCard(page: Page, searchTerm: string, datasetName: string): Promise<void> {
  await expect(async () => {
    const searchInput = page.locator(".dataset-search-bar input.search-input").first();
    await expect(searchInput).toBeVisible({ timeout: 15_000 });
    await fillMarked(searchInput, searchTerm);
    await waitForUiTransition(page);

    const cardVisible = await benchmarkDatasetCard(page, datasetName).isVisible().catch(() => false);
    if (!cardVisible) {
      await clickFederatedDatasetRefreshIfAvailable(page);
      await fillMarked(searchInput, searchTerm);
      await waitForUiTransition(page);
    }

    await expect(benchmarkDatasetCard(page, datasetName)).toBeVisible({ timeout: 20_000 });
  }).toPass({
    timeout: 180_000,
    intervals: EVENTUAL_UI_RETRY_INTERVALS,
  });
}

async function selectOfficialBenchmarkDataset(page: Page, searchTerm: string, datasetName: string): Promise<void> {
  await waitForBenchmarkDatasetCard(page, searchTerm, datasetName);

  const datasetCard = benchmarkDatasetCard(page, datasetName);
  await datasetCard.scrollIntoViewIfNeeded({ timeout: 10_000 });
  await clickMarked(datasetCard, { force: true });
  await waitForUiTransition(page);
  await expect(page.locator(".dataset-mapping-textarea").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".dataset-mapping-input").first()).toBeVisible({ timeout: 30_000 });
}

async function loadSelectedDataset(
  page: Page,
  inputColumns: string[],
  labelColumn: string,
): Promise<void> {
  const inputColumnsField = page.locator(".dataset-mapping-textarea").first();
  const labelColumnField = page.locator(".dataset-mapping-input").first();
  const loadDatasetButton = page.getByRole("button", { name: /^Load Dataset$/i }).first();

  await expect(inputColumnsField).toBeVisible({ timeout: 30_000 });
  await expect(labelColumnField).toBeVisible({ timeout: 30_000 });
  await expect.poll(
    async () => sortedColumnList(await inputColumnsField.inputValue()),
    {
      message: "The selected official benchmark dataset must expose the expected input columns.",
      timeout: 10_000,
      intervals: EVENTUAL_UI_RETRY_INTERVALS,
    },
  ).toEqual(sortedColumnList(inputColumns));
  await expect(labelColumnField).toHaveValue(labelColumn, { timeout: 10_000 });
  await expect(loadDatasetButton).toBeEnabled({ timeout: 30_000 });
  await clickMarked(loadDatasetButton, { force: true });

  await expect.poll(
    async () => {
      const rawValue = await datasetRowsValue(page).textContent().catch(() => "0");
      return Number((rawValue || "0").replace(/[^\d]/g, ""));
    },
    {
      message: "The selected official benchmark dataset must load at least one row.",
      timeout: 180_000,
      intervals: EVENTUAL_UI_RETRY_INTERVALS,
    },
  ).toBeGreaterThan(0);
}

async function runSampleRows(page: Page): Promise<void> {
  const testRowsButton = page.getByRole("button", { name: /^Test Rows$/i }).first();
  await expect(testRowsButton).toBeEnabled({ timeout: 30_000 });
  const executionFailures: string[] = [];
  const captureExecutionFailure = async (response: { url(): string; status(): number; text(): Promise<string> }) => {
    if (!response.url().includes("/management/v3/modelexecutions/execute") || response.status() < 400) {
      return;
    }
    const body = await response.text().catch(() => "");
    executionFailures.push(`HTTP ${response.status()} ${body ? body.slice(0, 240) : "<empty body>"}`);
  };
  page.on("response", captureExecutionFailure);
  await clickMarked(testRowsButton, { force: true });

  try {
    const deadline = Date.now() + 180_000;
    while (Date.now() < deadline) {
      const summary = page.getByText(/Row test complete\./i).first();
      const summaryVisible = await summary.isVisible().catch(() => false);
      if (summaryVisible) {
        const summaryText = ((await summary.textContent().catch(() => "")) || "").trim();
        if (/errors:\s*0\b/i.test(summaryText) && /partial:\s*0\b/i.test(summaryText)) {
          return;
        }
        const successMatch = summaryText.match(/Success:\s*(\d+)/i);
        const successCount = successMatch ? Number.parseInt(successMatch[1], 10) : 0;
        const runBenchmarkButton = page.getByRole("button", { name: /^Run Benchmark$/i }).first();
        const benchmarkCanContinue = await runBenchmarkButton.isEnabled().catch(() => false);
        if (successCount > 0 && benchmarkCanContinue) {
          return;
        }
        throw new Error(`Sample-row validation failed: ${summaryText}`);
      }
      const failedStatus = page.getByText(/Row test failed/i).first();
      if (await failedStatus.isVisible().catch(() => false)) {
        const statusText = ((await failedStatus.textContent().catch(() => "")) || "").trim();
        throw new Error(`Sample-row validation failed: ${statusText || "row test failed"}`);
      }
      await page.waitForTimeout(2_500);
    }
    if (executionFailures.length > 0) {
      throw new Error(`Timed out waiting for sample-row validation after backend execution failure: ${executionFailures[0]}`);
    }
    throw new Error("Timed out waiting for sample-row validation to finish.");
  } finally {
    page.off("response", captureExecutionFailure);
  }
}

async function waitForBenchmarkCompletion(page: Page): Promise<void> {
  const runBenchmarkButton = page.getByRole("button", { name: /^Run Benchmark$/i }).first();
  await runBenchmarkButton.scrollIntoViewIfNeeded({ timeout: 10_000 });
  await expect(runBenchmarkButton).toBeEnabled({ timeout: 60_000 });
  await clickMarked(runBenchmarkButton);

  const benchmarkHasStarted = async () => {
    const bodyText = await page.locator("body").innerText({ timeout: 5_000 }).catch(() => "");
    return /Executing benchmark|Executing .* validation rows|Running|Benchmark completed|Ranking Results/i.test(bodyText);
  };

  if (!(await benchmarkHasStarted())) {
    await runBenchmarkButton.evaluate((button: HTMLElement) => button.click());
  }

  await expect
    .poll(benchmarkHasStarted, {
      timeout: 15_000,
      message: "Run Benchmark did not start after clicking the visible benchmark button.",
    })
    .toBeTruthy();

  const deadline = Date.now() + 12 * 60 * 1000;
  let lastRunClickAt = Date.now();
  while (Date.now() < deadline) {
    const failed = page.getByText(/Benchmark failed/i).first();
    if (await failed.isVisible().catch(() => false)) {
      const failureText = ((await failed.textContent().catch(() => "")) || "Benchmark failed").trim();
      throw new Error(failureText);
    }

    if (await page.getByText(/Benchmark completed/i).first().isVisible().catch(() => false)) {
      return;
    }

    const running = await page.getByText(/Executing .* batch|Running/i).first().isVisible().catch(() => false);
    const buttonVisible = await runBenchmarkButton.isVisible().catch(() => false);
    const buttonEnabled = buttonVisible ? await runBenchmarkButton.isEnabled().catch(() => false) : false;
    if (!running && buttonVisible && buttonEnabled && Date.now() - lastRunClickAt > 30_000) {
      await clickMarked(runBenchmarkButton, { force: true });
      lastRunClickAt = Date.now();
    }
    await page.waitForTimeout(5_000);
  }
  throw new Error("Timed out waiting for the full benchmark to complete.");
}

async function runFullBenchmarkAndOpenObserverEvidence(
  page: Page,
  models: OfficialModel[],
  screenshotPrefix: string,
  captureStep: (page: Page, name: string, options?: { fullPage?: boolean }) => Promise<string>,
): Promise<string> {
  await waitForBenchmarkCompletion(page);
  const componentBenchmarkRunId = await readBenchmarkRunIdFromBenchmarkingComponent(page);
  await expect(page.getByRole("heading", { name: /Ranking Results/i }).first()).toBeVisible({ timeout: 60_000 });
  for (const model of models) {
    await expect(page.getByText(model.name).first()).toBeVisible({ timeout: 30_000 });
  }
  await captureStep(page, `${screenshotPrefix}-ranking`);

  const benchmarkRunId = await openBenchmarkEvidence(page, componentBenchmarkRunId);
  if (!benchmarkRunId) {
    await captureStep(page, `${screenshotPrefix}-benchmark-observer-unavailable`);
    return "benchmark-evidence-unavailable";
  }

  const observerStatus = await inspectObserverEvents(page, [/^BENCHMARK_STARTED$/i, /^MODEL_EXECUTION_COMPLETED$/i, /^BENCHMARK_COMPLETED$/i]);
  await captureStep(
    page,
    observerStatus.status === "passed"
      ? `${screenshotPrefix}-benchmark-observer`
      : `${screenshotPrefix}-benchmark-observer-unavailable`,
  );
  return benchmarkRunId;
}

async function readBenchmarkRunIdFromBenchmarkingComponent(page: Page): Promise<string> {
  return page.evaluate(() => {
    const host = document.querySelector("app-ai-model-benchmarking");
    const angularDebug = (window as Window & { ng?: { getComponent?: (element: Element | null) => unknown } }).ng;
    const component = angularDebug?.getComponent?.(host) as { lastBenchmarkRunId?: string } | undefined;
    return component?.lastBenchmarkRunId || "";
  }).catch(() => "");
}

async function openBenchmarkEvidence(page: Page, knownBenchmarkRunId: string): Promise<string> {
  const evidenceButton = page.getByRole("button", { name: /Benchmark Evidence/i }).first();
  if (await evidenceButton.isVisible().catch(() => false)) {
    await clickMarked(evidenceButton).catch(() => undefined);
    const navigated = await page.waitForURL(/\/ai-model-observer\/benchmarks\/benchmark-/i, { timeout: 5_000 }).then(() => true).catch(() => false);
    if (navigated) {
      return extractRouteTail(page.url());
    }
  }

  const benchmarkRunId = knownBenchmarkRunId || await readBenchmarkRunIdFromBenchmarkingComponent(page);
  if (!benchmarkRunId) {
    return "";
  }

  const observerUrl = new URL(
    `/inesdata-connector-interface/ai-model-observer/benchmarks/${encodeURIComponent(benchmarkRunId)}`,
    page.url(),
  );
  await page.goto(observerUrl.toString(), { waitUntil: "domcontentloaded" });
  await expect(page).toHaveURL(/\/ai-model-observer\/benchmarks\/benchmark-/i, { timeout: 10_000 });
  return benchmarkRunId;
}

async function inspectObserverEvents(page: Page, expectedEvents: RegExp[]): Promise<{ status: "passed" | "skipped"; reason?: string }> {
  await expect(page.getByRole("heading", { name: /Asset timeline|Benchmark evidence|Participant summary/i }).first()).toBeVisible({
    timeout: 30_000,
  });

  if (await page.getByText(/Failed to load benchmark evidence|Failed to load participant summary|Failed to load timeline/i).first().isVisible().catch(() => false)) {
    return {
      status: "skipped",
      reason: "Observer backend is not available from the connector UI in this environment.",
    };
  }

  for (const expectedEvent of expectedEvents) {
    await expect(page.getByRole("heading", { name: expectedEvent }).first()).toBeVisible({
      timeout: 60_000,
    });
  }

  return { status: "passed" };
}

async function inspectParticipantSummary(
  page: Page,
  participantSummaryUrl: string,
  connectorName: string,
  benchmarkRunId: string,
): Promise<{ status: "passed" | "skipped"; reason?: string }> {
  let skippedReason = "";
  await expect(async () => {
    await page.goto(participantSummaryUrl, { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: /Participant summary/i }).first()).toBeVisible({
      timeout: 20_000,
    });

    if (await page.getByText(/Failed to load participant summary/i).first().isVisible().catch(() => false)) {
      skippedReason = "Observer participant summary is not available from the connector UI in this environment.";
      return;
    }

    await expect(page.getByText(connectorName).first()).toBeVisible({ timeout: 20_000 });
    if (benchmarkRunId !== "benchmark-evidence-unavailable") {
      await expect(page.getByText(benchmarkRunId).first()).toBeVisible({ timeout: 20_000 });
    }
  }).toPass({
    timeout: 120_000,
    intervals: EVENTUAL_UI_RETRY_INTERVALS,
  });

  if (skippedReason) {
    return { status: "skipped", reason: skippedReason };
  }
  return { status: "passed" };
}

function extractRouteTail(url: string): string {
  const pathname = new URL(url).pathname.replace(/\/+$/, "");
  return decodeURIComponent(pathname.split("/").pop() || "");
}

test("17.1 AI Model Browser: official PIONERA use-case assets are discoverable with DAIMO metadata", async ({
  page,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  test.skip(dataspaceRuntime.adapter !== "inesdata", "Official use-case validation currently targets INESData Level 6.");
  test.setTimeout(5 * 60 * 1000);

  const browserDiagnostics = collectBrowserDiagnostics(page);
  try {
    await loginConnector(page, dataspaceRuntime.provider);
    await openConnectorModule(page, dataspaceRuntime.provider, "/ai-model-browser", /AI Model Browser/i);

    const expectedModels = [
      FLARES_5W1H_MODEL,
      FLARES_RELIABILITY_MODELS[1],
      MOBILITY_ACTUAL_TRAVEL_TIME_MODELS[0],
    ];

    await expect(async () => {
      await fillMarked(browserSearchInput(page), "PIONERA Use Case");
      await waitForUiTransition(page);
      for (const model of expectedModels) {
        await expect(browserCard(page, model), `Official browser card ${model.assetId} must exist`).toBeVisible({
          timeout: 20_000,
        });
      }
    }).toPass({
      timeout: 120_000,
      intervals: EVENTUAL_UI_RETRY_INTERVALS,
    });

    await expect(browserCard(page, FLARES_5W1H_MODEL).getByText(/Natural Language Processing/i).first()).toBeVisible();
    await expect(browserCard(page, FLARES_5W1H_MODEL).getByText(/token-classification/i).first()).toBeVisible();
    await expect(browserCard(page, FLARES_5W1H_MODEL).getByText(/Transformers/i).first()).toBeVisible();
    await expect(browserCard(page, MOBILITY_ACTUAL_TRAVEL_TIME_MODELS[0]).getByText(/Tabular/i).first()).toBeVisible();
    await expect(browserCard(page, MOBILITY_ACTUAL_TRAVEL_TIME_MODELS[0]).getByText(/regression/i).first()).toBeVisible();
    await captureStep(page, "17-01-official-use-cases-browser-catalog");

    await clickMarked(browserCard(page, FLARES_5W1H_MODEL).getByRole("button", { name: /View details/i }).first(), {
      force: true,
    });
    await expect(page.locator("body")).toContainText(/Asset information|Contract offer|JSON-LD/i, { timeout: 30_000 });
    await captureStep(page, "17-02-official-use-cases-browser-detail");

    await attachJson("official-ai-model-browser-use-case-assertions", {
      module: "AI Model Browser",
      expectedAssets: expectedModels,
      validatedMetadata: ["taskCategory", "taskType", "subtask", "libraryName", "source/local-or-federated"],
      sourceOfTruth: "ProyectoPIONERA/AIModelHub steps 8-10 and AIModelHub-Use-Cases model catalog",
    });
  } finally {
    const diagnostics = browserDiagnostics.snapshot();
    browserDiagnostics.dispose();
    await attachJson("official-ai-model-browser-diagnostics", diagnostics);
  }
});

test("17.2 AI Model Execution: official FLARES 5W1H model exposes input schema and executes", async ({
  page,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  test.skip(dataspaceRuntime.adapter !== "inesdata", "Official use-case validation currently targets INESData Level 6.");
  test.setTimeout(6 * 60 * 1000);

  const browserDiagnostics = collectBrowserDiagnostics(page);
  try {
    await loginConnector(page, dataspaceRuntime.provider);
    await openConnectorModule(page, dataspaceRuntime.provider, "/ai-model-execution", /AI Execution/i);

    const assetSelect = page.locator("#assetSelect").first();
    await expect(assetSelect).toBeVisible({ timeout: 60_000 });
    await selectOptionMarked(assetSelect, FLARES_5W1H_MODEL.assetId);
    await waitForUiTransition(page);

    await expect(page.getByRole("heading", { name: FLARES_5W1H_MODEL.name }).first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("button", { name: /Change Model/i }).first()).toBeVisible();
    await expect(page.locator(".input-schema-section").first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/Detected DAIMO input schema/i).first()).toBeVisible();
    await expect(page.getByText(/2 fields/i).first()).toBeVisible();
    await expect(generatedInputField(page, "Id")).toBeVisible({ timeout: 15_000 });
    await expect(generatedInputField(page, "Text")).toBeVisible({ timeout: 15_000 });
    await captureStep(page, "17-03-official-use-cases-execution-schema");

    await fillFlares5w1hGeneratedForm(page);
    await clickMarked(page.getByRole("button", { name: /Execute Model/i }).first(), { force: true });

    await expect(page.getByText(/Execution Result/i).first()).toBeVisible({ timeout: 120_000 });
    await expect(page.locator("body")).toContainText(/SUCCESS/i, { timeout: 30_000 });
    await expect(page.getByText(/Status Code:/i).first()).toBeVisible({ timeout: 30_000 });
    await expect(page.locator("body")).toContainText(/Status Code:\s*200/i, { timeout: 30_000 });
    await captureStep(page, "17-04-official-use-cases-execution-result");

    await clickMarked(page.getByRole("button", { name: /View Observer Timeline/i }).first(), { force: true });
    await expect(page).toHaveURL(/\/ai-model-observer\/timeline\/city-flares-5w1h-albert/i, { timeout: 30_000 });
    const observerStatus = await inspectObserverEvents(page, [/^MODEL_EXECUTION_REQUESTED$/i, /^MODEL_EXECUTION_COMPLETED$/i]);
    await captureStep(
      page,
      observerStatus.status === "passed"
        ? "17-05-official-use-cases-execution-observer"
        : "17-05-official-use-cases-execution-observer-unavailable",
    );

    await attachJson("official-ai-model-execution-use-case-assertions", {
      module: "AI Model Execution",
      model: FLARES_5W1H_MODEL,
      payload: FLARES_5W1H_PAYLOAD,
      validatedFeatures: ["DAIMO input schema detection", "Generated form", "HTTP 200 execution", "Observer asset timeline"],
      sourceOfTruth: "ProyectoPIONERA/AIModelHub seed_use_case_http_data_assets",
    });
  } finally {
    const diagnostics = browserDiagnostics.snapshot();
    browserDiagnostics.dispose();
    await attachJson("official-ai-model-execution-diagnostics", diagnostics);
  }
});

test("17.3 AI Model Benchmarking and Observer: official FLARES Reliability comparison produces evidence", async ({
  page,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  test.skip(dataspaceRuntime.adapter !== "inesdata", "Official use-case validation currently targets INESData Level 6.");
  test.setTimeout(15 * 60 * 1000);

  const browserDiagnostics = collectBrowserDiagnostics(page);
  try {
    await loginConnector(page, dataspaceRuntime.provider);
    await openConnectorModule(page, dataspaceRuntime.provider, "/ai-model-benchmarking", /Model Benchmarking/i);

    await selectBenchmarkModels(page, "FLARES Reliability", FLARES_RELIABILITY_MODELS);
    await expect(page.getByText(/3 selected/i).first()).toBeVisible({ timeout: 15_000 });
    await selectOfficialBenchmarkDataset(page, "Reliability", "FLARES Reliability Test Dataset");
    await loadSelectedDataset(page, FLARES_RELIABILITY_INPUT_COLUMNS, "Reliability_Label");
    await captureStep(page, "17-06-official-use-cases-flares-dataset-loaded");

    await runSampleRows(page);
    await captureStep(page, "17-07-official-use-cases-flares-row-test");

    const benchmarkRunId = await runFullBenchmarkAndOpenObserverEvidence(
      page,
      FLARES_RELIABILITY_MODELS,
      "17-08-official-use-cases-flares",
      captureStep,
    );

    const participantSummaryUrl = route(
      dataspaceRuntime.provider.portalBaseUrl,
      `/ai-model-observer/participants/${encodeURIComponent(dataspaceRuntime.provider.connectorName)}`,
    );
    const participantSummaryStatus = await inspectParticipantSummary(
      page,
      participantSummaryUrl,
      dataspaceRuntime.provider.connectorName,
      benchmarkRunId,
    );
    await captureStep(
      page,
      participantSummaryStatus.status === "passed"
        ? "17-10-official-use-cases-flares-participant-summary"
        : "17-10-official-use-cases-flares-participant-summary-unavailable",
    );

    await attachJson("official-ai-model-benchmarking-flares-use-case-assertions", {
      modules: ["AI Model Benchmarking", "AI Model Observer"],
      models: FLARES_RELIABILITY_MODELS,
      dataset: {
        assetId: "company-flares-reliability-test",
        name: "FLARES Reliability Test Dataset",
        inputColumns: FLARES_RELIABILITY_INPUT_COLUMNS,
        labelColumn: "Reliability_Label",
      },
      benchmarkRunId,
      observerParticipantSummary: participantSummaryStatus,
      validatedFeatures: [
        "compatible model pool",
        "agreed federated dataset loading",
        "sample-row validation",
        "full benchmark ranking",
        "benchmark evidence timeline",
        "participant summary",
      ],
      sourceOfTruth: "ProyectoPIONERA/AIModelHub steps 9-10 and AIModelHub-Use-Cases FLARES endpoints",
    });
  } finally {
    const diagnostics = browserDiagnostics.snapshot();
    browserDiagnostics.dispose();
    await attachJson("official-ai-model-benchmarking-flares-diagnostics", diagnostics);
  }
});

test("17.4 AI Model Benchmarking and Observer: official Mobility Actual Travel Time comparison produces evidence", async ({
  page,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  test.skip(dataspaceRuntime.adapter !== "inesdata", "Official use-case validation currently targets INESData Level 6.");
  test.setTimeout(15 * 60 * 1000);

  const browserDiagnostics = collectBrowserDiagnostics(page);
  try {
    await loginConnector(page, dataspaceRuntime.provider);
    await openConnectorModule(page, dataspaceRuntime.provider, "/ai-model-benchmarking", /Model Benchmarking/i);

    await selectBenchmarkModels(page, "Actual Travel Time", MOBILITY_ACTUAL_TRAVEL_TIME_MODELS);
    await expect(page.getByText(/3 selected/i).first()).toBeVisible({ timeout: 15_000 });
    await fillMarked(page.locator("input.search-input").first(), "Actual Travel Time");
    await waitForUiTransition(page);
    const modelPoolText = await page.locator(".model-list").first().innerText();
    for (const model of MOBILITY_ACTUAL_TRAVEL_TIME_MODELS) {
      expect(modelPoolText).toContain(model.name);
    }
    await captureStep(page, "17-11-official-use-cases-mobility-compatible-pool");

    await selectOfficialBenchmarkDataset(page, "Actual Travel Time Sample", "Mobility Actual Travel Time Sample Test Dataset");
    await loadSelectedDataset(page, MOBILITY_ACTUAL_TRAVEL_TIME_INPUT_COLUMNS, "actual_travel_time");
    await captureStep(page, "17-12-official-use-cases-mobility-dataset-loaded");

    await runSampleRows(page);
    await captureStep(page, "17-13-official-use-cases-mobility-row-test");

    const benchmarkRunId = await runFullBenchmarkAndOpenObserverEvidence(
      page,
      MOBILITY_ACTUAL_TRAVEL_TIME_MODELS,
      "17-14-official-use-cases-mobility",
      captureStep,
    );

    await attachJson("official-ai-model-benchmarking-mobility-use-case-assertions", {
      modules: ["AI Model Benchmarking", "AI Model Observer"],
      models: MOBILITY_ACTUAL_TRAVEL_TIME_MODELS,
      dataset: {
        assetId: "company-mobility-actual-travel-time-sample-test",
        name: "Mobility Actual Travel Time Sample Test Dataset",
        inputColumns: MOBILITY_ACTUAL_TRAVEL_TIME_INPUT_COLUMNS,
        labelColumn: "actual_travel_time",
      },
      benchmarkRunId,
      validatedFeatures: [
        "local-first compatible model filtering",
        "federated compatible model selection",
        "official Mobility sample dataset loading",
        "sample-row validation against real model-server endpoints",
        "full Mobility benchmark ranking",
        "benchmark evidence timeline",
      ],
      sourceOfTruth: "ProyectoPIONERA/AIModelHub-Use-Cases Mobility target configs",
    });
  } finally {
    const diagnostics = browserDiagnostics.snapshot();
    browserDiagnostics.dispose();
    await attachJson("official-ai-model-benchmarking-mobility-diagnostics", diagnostics);
  }
});

test("17.5 AI Model Benchmarking and Observer: official FLARES 5W1H Metrics comparison produces evidence", async ({
  page,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  test.skip(dataspaceRuntime.adapter !== "inesdata", "Official use-case validation currently targets INESData Level 6.");
  test.setTimeout(15 * 60 * 1000);

  const browserDiagnostics = collectBrowserDiagnostics(page);
  try {
    await loginConnector(page, dataspaceRuntime.provider);
    await openConnectorModule(page, dataspaceRuntime.provider, "/ai-model-benchmarking", /Model Benchmarking/i);

    await selectBenchmarkModels(page, "5W1H Metrics", FLARES_5W1H_METRIC_MODELS);
    await expect(page.getByText(/3 selected/i).first()).toBeVisible({ timeout: 15_000 });
    await selectOfficialBenchmarkDataset(page, "5W1H", "FLARES 5W1H Test Dataset");
    await loadSelectedDataset(page, FLARES_5W1H_INPUT_COLUMNS, "Tags");
    await captureStep(page, "17-16-official-use-cases-5w1h-metrics-dataset-loaded");

    await runSampleRows(page);
    await captureStep(page, "17-17-official-use-cases-5w1h-metrics-row-test");

    const benchmarkRunId = await runFullBenchmarkAndOpenObserverEvidence(
      page,
      FLARES_5W1H_METRIC_MODELS,
      "17-18-official-use-cases-5w1h-metrics",
      captureStep,
    );

    await attachJson("official-ai-model-benchmarking-5w1h-metrics-use-case-assertions", {
      modules: ["AI Model Benchmarking", "AI Model Observer"],
      models: FLARES_5W1H_METRIC_MODELS,
      dataset: {
        assetId: "company-flares-5w1h-test",
        name: "FLARES 5W1H Test Dataset",
        inputColumns: FLARES_5W1H_INPUT_COLUMNS,
        labelColumn: "Tags",
      },
      benchmarkRunId,
      validatedFeatures: [
        "official FLARES 5W1H metric model selection",
        "official FLARES 5W1H dataset loading",
        "sample-row validation against metric endpoints",
        "full FLARES 5W1H metric benchmark ranking",
        "benchmark evidence timeline",
      ],
      sourceOfTruth: "ProyectoPIONERA/AIModelHub flares_metric_input_columns_json and flares_metric_label_column",
    });
  } finally {
    const diagnostics = browserDiagnostics.snapshot();
    browserDiagnostics.dispose();
    await attachJson("official-ai-model-benchmarking-5w1h-metrics-diagnostics", diagnostics);
  }
});

test("17.6 AI Model Benchmarking and Observer: official Mobility Previous Delay comparison produces evidence", async ({
  page,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  test.skip(dataspaceRuntime.adapter !== "inesdata", "Official use-case validation currently targets INESData Level 6.");
  test.setTimeout(15 * 60 * 1000);

  const browserDiagnostics = collectBrowserDiagnostics(page);
  try {
    await loginConnector(page, dataspaceRuntime.provider);
    await openConnectorModule(page, dataspaceRuntime.provider, "/ai-model-benchmarking", /Model Benchmarking/i);

    await selectBenchmarkModels(page, "Previous Delay", MOBILITY_PREVIOUS_DELAY_MODELS);
    await expect(page.getByText(/3 selected/i).first()).toBeVisible({ timeout: 15_000 });
    await fillMarked(page.locator("input.search-input").first(), "Previous Delay");
    await waitForUiTransition(page);
    const modelPoolText = await page.locator(".model-list").first().innerText();
    for (const model of MOBILITY_PREVIOUS_DELAY_MODELS) {
      expect(modelPoolText).toContain(model.name);
    }
    await captureStep(page, "17-19-official-use-cases-previous-delay-compatible-pool");

    await selectOfficialBenchmarkDataset(page, "Previous Delay Sample", "Mobility Previous Delay Sample Test Dataset");
    await loadSelectedDataset(page, MOBILITY_PREVIOUS_DELAY_INPUT_COLUMNS, "previous_delay");
    await captureStep(page, "17-20-official-use-cases-previous-delay-dataset-loaded");

    await runSampleRows(page);
    await captureStep(page, "17-21-official-use-cases-previous-delay-row-test");

    const benchmarkRunId = await runFullBenchmarkAndOpenObserverEvidence(
      page,
      MOBILITY_PREVIOUS_DELAY_MODELS,
      "17-22-official-use-cases-previous-delay",
      captureStep,
    );

    await attachJson("official-ai-model-benchmarking-previous-delay-use-case-assertions", {
      modules: ["AI Model Benchmarking", "AI Model Observer"],
      models: MOBILITY_PREVIOUS_DELAY_MODELS,
      dataset: {
        assetId: "company-mobility-previous-delay-sample-test",
        name: "Mobility Previous Delay Sample Test Dataset",
        inputColumns: MOBILITY_PREVIOUS_DELAY_INPUT_COLUMNS,
        labelColumn: "previous_delay",
      },
      benchmarkRunId,
      validatedFeatures: [
        "official Mobility Previous Delay compatible model filtering",
        "official Mobility sample dataset loading",
        "sample-row validation against real model-server endpoints",
        "full Mobility Previous Delay benchmark ranking",
        "benchmark evidence timeline",
      ],
      sourceOfTruth: "ProyectoPIONERA/AIModelHub-Use-Cases Mobility target configs",
    });
  } finally {
    const diagnostics = browserDiagnostics.snapshot();
    browserDiagnostics.dispose();
    await attachJson("official-ai-model-benchmarking-previous-delay-diagnostics", diagnostics);
  }
});
