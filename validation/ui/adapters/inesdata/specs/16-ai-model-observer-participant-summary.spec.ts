import type { Page } from "@playwright/test";

import { test, expect } from "../../../shared/fixtures/dataspace.fixture";

import { KeycloakLoginPage } from "../../../shared/components/auth/keycloak-login.page";
import { ConnectorShellPage } from "../components/shell/connector-shell.page";
import { collectBrowserDiagnostics } from "../../../shared/utils/browser-diagnostics";
import { clickMarked } from "../../../shared/utils/live-marker";
import { EVENTUAL_UI_RETRY_INTERVALS } from "../../../shared/utils/waiting";

type ObserverEvent = {
  eventId: string;
  eventType: string;
  status: string;
  sourceComponent: string;
  participantId: string;
  actorType: string;
  actorId: string;
  correlationId: string;
  processId: string;
  assetId: string;
  agreementId: string;
  benchmarkRunId: string;
  providerParticipantId: string;
  consumerParticipantId: string;
  modelName: string;
  executionMode: string;
  endpointKind: string;
  taskType: string;
  datasetFingerprint: string;
  datasetRowCount: number;
  payloadHash: string;
  responseHash: string;
  selectedMetrics?: string[];
  benchmarkSummary?: Record<string, unknown>;
  details: Record<string, unknown>;
  occurredAt: string;
};

type ObserverFetchResult = {
  url: string;
  status: number;
  ok: boolean;
  payload?: unknown;
  rawBody?: string;
  error?: string;
};

type ObserverParticipantSummaryReport = {
  startedAt: string;
  connector: string;
  portalBaseUrl: string;
  linkedCases: string[];
  runContext: {
    runId: string;
    assetId: string;
    agreementId: string;
    benchmarkRunId: string;
    participantId: string;
    correlationId: string;
  };
  observerHomeUrl: string;
  participantSummaryUrl: string;
  ingestion?: ObserverFetchResult;
  routeChecks: Array<{
    scenario: string;
    url: string;
    status: "passed";
  }>;
  skippedReason?: string;
};

const OBSERVER_DEMO_ENV = "UI_AI_MODEL_OBSERVER_DEMO";
const UNAVAILABLE_STATUS_CODES = new Set([0, 401, 403, 404, 405, 501, 502, 503, 504]);

test.skip(
  process.env[OBSERVER_DEMO_ENV] !== "1",
  `Set ${OBSERVER_DEMO_ENV}=1 or run Level 6 with the INESData adapter to validate AI Model Observer participant summaries from the INESData UI.`,
);

function observerHomeUrl(portalBaseUrl: string): string {
  return `${portalBaseUrl.replace(/\/$/, "")}/ai-model-observer`;
}

function observerApiBaseUrl(portalBaseUrl: string): string {
  return `${portalBaseUrl.replace(/\/$/, "")}/model-observer`;
}

function participantSummaryUrl(portalBaseUrl: string, participantId: string): string {
  return `${observerHomeUrl(portalBaseUrl)}/participants/${encodeURIComponent(participantId)}`;
}

function stableHash(value: string): string {
  let hash = 0;
  for (const character of value) {
    hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  }
  return hash.toString(16).padStart(8, "0");
}

function buildObserverEvents(runId: string) {
  const assetId = `asset-${runId}`;
  const agreementId = `agreement-${runId}`;
  const benchmarkRunId = `benchmark-${runId}`;
  const participantId = "qa-ai-model-consumer";
  const correlationId = `correlation-${runId}`;
  const occurredAt = new Date().toISOString();
  const baseEvent = {
    sourceComponent: "validation-framework",
    participantId,
    actorType: "system",
    actorId: "a52-validation",
    correlationId,
    processId: runId,
    assetId,
    agreementId,
    benchmarkRunId,
    providerParticipantId: "qa-ai-model-provider",
    consumerParticipantId: participantId,
    modelName: "A5.2 Observer Participant Summary Model",
    executionMode: "external-httpdata",
    endpointKind: "model-server",
    taskType: "observer-participant-summary",
    datasetFingerprint: stableHash(`dataset:${runId}`),
    datasetRowCount: 3,
    payloadHash: stableHash(`payload:${runId}`),
    responseHash: stableHash(`response:${runId}`),
    details: {
      scope: "A5.2 observer participant summary",
      sensitivePayloadStored: false,
      rawDatasetStored: false,
    },
    occurredAt,
  };
  const events: ObserverEvent[] = [
    {
      ...baseEvent,
      eventId: `${runId}-detail-viewed`,
      eventType: "MODEL_DETAIL_VIEWED",
      status: "VIEWED",
    },
    {
      ...baseEvent,
      eventId: `${runId}-benchmark-started`,
      eventType: "BENCHMARK_STARTED",
      status: "STARTED",
      selectedMetrics: ["accuracy", "latency"],
      benchmarkSummary: {
        modelsCompared: 2,
        datasetRows: 3,
      },
    },
    {
      ...baseEvent,
      eventId: `${runId}-execution-completed`,
      eventType: "MODEL_EXECUTION_COMPLETED",
      status: "COMPLETED",
    },
  ];

  return {
    assetId,
    agreementId,
    benchmarkRunId,
    participantId,
    correlationId,
    events,
  };
}

async function observerHomeIsVisible(page: Page): Promise<boolean> {
  const heading = page.getByRole("heading", { name: /AI Model Observer/i }).first();
  try {
    await expect(heading).toBeVisible({ timeout: 10_000 });
  } catch {
    return false;
  }
  return true;
}

async function postObserverEventsFromBrowser(
  page: Page,
  apiBaseUrl: string,
  events: ObserverEvent[],
): Promise<ObserverFetchResult> {
  return page.evaluate(
    async ({ endpoint, payload }) => {
      try {
        const response = await fetch(endpoint, {
          method: "POST",
          credentials: "include",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
          },
          body: JSON.stringify(payload),
        });
        const rawBody = await response.text();
        let parsed: unknown;
        try {
          parsed = rawBody ? JSON.parse(rawBody) : undefined;
        } catch {
          parsed = undefined;
        }
        return {
          url: response.url,
          status: response.status,
          ok: response.ok,
          payload: parsed,
          rawBody: parsed === undefined ? rawBody.slice(0, 1000) : undefined,
        };
      } catch (error) {
        return {
          url: endpoint,
          status: 0,
          ok: false,
          error: error instanceof Error ? error.message : String(error),
        };
      }
    },
    {
      endpoint: `${apiBaseUrl}/events/bulk`,
      payload: events,
    },
  );
}

async function expectParticipantSummary(
  page: Page,
  summaryUrl: string,
  runContext: ReturnType<typeof buildObserverEvents>,
): Promise<void> {
  await expect(async () => {
    await page.goto(summaryUrl, { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: /Participant summary/i })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(runContext.participantId).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Totals by event type/i).first()).toBeVisible({ timeout: 10_000 });

    for (const eventType of ["MODEL_DETAIL_VIEWED", "BENCHMARK_STARTED", "MODEL_EXECUTION_COMPLETED"]) {
      const totalRow = page.locator(".observer-summary-page__total-row").filter({ hasText: eventType }).first();
      await expect(totalRow, `${eventType} total row is not visible`).toBeVisible({ timeout: 10_000 });
      await expect(totalRow.locator("strong").first()).toHaveText(/[1-9]\d*/, { timeout: 10_000 });
    }

    await expect(page.getByText(runContext.assetId).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(runContext.agreementId).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(runContext.benchmarkRunId).first()).toBeVisible({ timeout: 10_000 });
  }).toPass({
    timeout: 45_000,
    intervals: EVENTUAL_UI_RETRY_INTERVALS,
  });
}

test("16 AI Model Observer: participant summary aggregates controlled model evidence", async ({
  page,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  test.skip(dataspaceRuntime.adapter !== "inesdata", "This demo validates the INESData connector UI path.");

  const runId = `a52-observer-participant-${Date.now()}`;
  const runContext = buildObserverEvents(runId);
  const homeUrl = observerHomeUrl(dataspaceRuntime.consumer.portalBaseUrl);
  const apiBaseUrl = observerApiBaseUrl(dataspaceRuntime.consumer.portalBaseUrl);
  const summaryUrl = participantSummaryUrl(dataspaceRuntime.consumer.portalBaseUrl, runContext.participantId);
  const browserDiagnostics = collectBrowserDiagnostics(page);
  const loginPage = new KeycloakLoginPage(page, {
    portalUser: dataspaceRuntime.consumer.username,
    portalPassword: dataspaceRuntime.consumer.password,
    skipLogin: false,
  });
  const shellPage = new ConnectorShellPage(page);
  const report: ObserverParticipantSummaryReport = {
    startedAt: new Date().toISOString(),
    connector: dataspaceRuntime.consumer.connectorName,
    portalBaseUrl: dataspaceRuntime.consumer.portalBaseUrl,
    linkedCases: ["MH-OBS-06", "PT5-MH-17", "DS-UI-AMH-OBS-02", "Model Clearing House"],
    runContext: {
      runId,
      assetId: runContext.assetId,
      agreementId: runContext.agreementId,
      benchmarkRunId: runContext.benchmarkRunId,
      participantId: runContext.participantId,
      correlationId: runContext.correlationId,
    },
    observerHomeUrl: homeUrl,
    participantSummaryUrl: summaryUrl,
    routeChecks: [],
  };

  try {
    await loginPage.open(dataspaceRuntime.consumer.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await shellPage.expectReady();
    await captureStep(page, "01-ai-model-observer-participant-after-login");

    await shellPage.navigateToSection(/^\s*AI Model Observer\s*$/i, homeUrl);
    await shellPage.assertNoGateway403("AI Model Observer page");
    await shellPage.assertNoServerErrorBanner("AI Model Observer page");

    if (!(await observerHomeIsVisible(page))) {
      report.skippedReason =
        "AI Model Observer UI is not integrated in this INESData connector build yet.";
      await attachJson("ai-model-observer-participant-summary-report", report);
      test.skip(true, report.skippedReason);
    }
    await captureStep(page, "02-ai-model-observer-participant-home");

    report.ingestion = await postObserverEventsFromBrowser(page, apiBaseUrl, runContext.events);
    await attachJson("ai-model-observer-participant-summary-ingestion", report.ingestion);
    if (!report.ingestion.ok && UNAVAILABLE_STATUS_CODES.has(report.ingestion.status)) {
      report.skippedReason =
        `Model Observer API is not available from the connector UI proxy (HTTP ${report.ingestion.status}).`;
      await attachJson("ai-model-observer-participant-summary-report", report);
      test.skip(true, report.skippedReason);
    }
    expect(
      report.ingestion.ok,
      `Observer bulk ingestion failed: ${JSON.stringify(report.ingestion)}`,
    ).toBeTruthy();

    await expectParticipantSummary(page, summaryUrl, runContext);
    await captureStep(page, "03-ai-model-observer-participant-summary");
    report.routeChecks.push({
      scenario: "participant_summary_totals",
      url: page.url(),
      status: "passed",
    });

    await clickMarked(page.getByRole("button", { name: /Open asset timeline/i }).first(), { force: true });
    await expect(page).toHaveURL(new RegExp(`/ai-model-observer/timeline/${runContext.assetId}`, "i"), {
      timeout: 10_000,
    });
    await expect(page.getByRole("heading", { name: /Asset timeline/i })).toBeVisible({ timeout: 10_000 });
    report.routeChecks.push({
      scenario: "latest_event_asset_timeline_navigation",
      url: page.url(),
      status: "passed",
    });
    await captureStep(page, "04-ai-model-observer-participant-asset-timeline");
  } finally {
    const browserDiagnosticsSnapshot = browserDiagnostics.snapshot();
    browserDiagnostics.dispose();
    await attachJson("ai-model-observer-participant-summary-browser-diagnostics", browserDiagnosticsSnapshot);
    await attachJson("ai-model-observer-participant-summary-report", {
      ...report,
      finishedAt: new Date().toISOString(),
      browserDiagnostics: {
        eventCount: browserDiagnosticsSnapshot.eventCount,
        droppedEventCount: browserDiagnosticsSnapshot.droppedEventCount,
      },
    });
  }
});
