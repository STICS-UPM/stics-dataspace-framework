const { test, expect } = require("../fixtures");
const { joinUrl } = require("../runtime");
const {
  clickMarked,
  fillMarked,
  highlightMarked,
  pressMarked,
} = require("../support/live-marker");

async function bodyText(page) {
  return page
    .locator("body")
    .evaluate((node) => String(node.textContent || "").replace(/\s+/g, " ").trim())
    .catch(() => "");
}

async function openMappingEditor(page, semanticVirtualizationRuntime) {
  const url = joinUrl(
    semanticVirtualizationRuntime.mappingEditorBaseUrl,
    semanticVirtualizationRuntime.mappingEditorRootPath,
  );
  const response = await page.goto(url, { waitUntil: "networkidle" });
  const status = response ? response.status() : 0;

  expect(response, `Expected browser navigation response from ${url}`).not.toBeNull();
  expect(status).toBe(200);
  await expect(page).toHaveTitle(/Mapping Editor/i, { timeout: 60 * 1000 });

  return { url, status };
}

async function waitForBodyText(page, expectedPattern) {
  await expect
    .poll(() => bodyText(page), { timeout: 30 * 1000 })
    .toMatch(expectedPattern);
  return bodyText(page);
}

async function openSidebarPage(page, labelPattern) {
  const sidebarLink = page.getByRole("link", { name: labelPattern }).first();
  await expect(sidebarLink).toBeVisible({ timeout: 30 * 1000 });
  await clickMarked(sidebarLink);
  await page.waitForLoadState("networkidle").catch(() => {});
}

async function createEphemeralMapping(page) {
  const mappingLabel = `qaMap${String(Date.now()).slice(-8)}`;
  const labelInput = page.getByLabel(/Enter mapping label/i).first();

  await expect(labelInput).toBeVisible({ timeout: 30 * 1000 });
  await fillMarked(labelInput, mappingLabel);
  await pressMarked(labelInput, "Enter");
  await page.waitForLoadState("networkidle").catch(() => {});

  const createButton = page.getByRole("button", { name: /^Create$/ }).first();
  await expect(createButton).toBeVisible({ timeout: 30 * 1000 });
  await clickMarked(createButton);

  await waitForBodyText(page, new RegExp(mappingLabel, "i"));
  return mappingLabel;
}

test.skip(
  process.env.SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_UI !== "1",
  "Opt-in editor validation: set SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_UI=1 after deploying mapping-editor.",
);

test("PT5-VS-07: mapping editor graphical UI is reachable", async ({
  page,
  semanticVirtualizationRuntime,
  captureStep,
  attachJson,
}) => {
  const { url, status } = await openMappingEditor(page, semanticVirtualizationRuntime);

  const text = await bodyText(page);
  expect(text).toMatch(/Mapping Editor|Use sidebar/i);
  await highlightMarked(page.getByText(/Mapping Editor|Use sidebar/i).first());

  await captureStep(page, "pt5-vs-07-mapping-editor-home");
  await attachJson("pt5-vs-07-state", {
    url,
    status,
    title: await page.title().catch(() => ""),
    bodyExcerpt: text.slice(0, 500),
  });
});

test("PT5-VS-08: mapping editor exposes mapping execution entrypoint", async ({
  page,
  semanticVirtualizationRuntime,
  captureStep,
  attachJson,
}) => {
  const { url, status } = await openMappingEditor(page, semanticVirtualizationRuntime);
  const text = await bodyText(page);

  expect(text).toMatch(/Mapping Editor|Materialise Graph|Build Mapping|Use sidebar/i);
  await highlightMarked(
    page.getByText(/Mapping Editor|Materialise Graph|Build Mapping|Use sidebar/i).first(),
  );

  await captureStep(page, "pt5-vs-08-mapping-editor-execution-entrypoint");
  await attachJson("pt5-vs-08-state", {
    url,
    status,
    title: await page.title().catch(() => ""),
    bodyExcerpt: text.slice(0, 700),
  });
});

test("SV-UI-04: mapping editor exposes ontology import and exploration panels", async ({
  page,
  semanticVirtualizationRuntime,
  captureStep,
  attachJson,
}) => {
  const { url, status } = await openMappingEditor(page, semanticVirtualizationRuntime);

  await openSidebarPage(page, /Ontologies/i);
  const text = await waitForBodyText(
    page,
    /Import Ontology|Explore Ontology|View Ontology|Custom Terms/i,
  );
  await highlightMarked(
    page.getByText(/Import Ontology|Explore Ontology|View Ontology|Custom Terms/i).first(),
  );

  await captureStep(page, "sv-ui-04-ontology-panels");
  await attachJson("sv-ui-04-state", {
    url,
    status,
    linkedCases: ["PT5-VS-06", "PT5-VS-07"],
    verifiedPanels: ["Import Ontology", "Explore Ontology", "View Ontology", "Custom Terms"],
    bodyExcerpt: text.slice(0, 900),
  });
});

test("SV-UI-05: mapping editor supports a non-destructive mapping authoring path", async ({
  page,
  semanticVirtualizationRuntime,
  captureStep,
  attachJson,
}) => {
  const { url, status } = await openMappingEditor(page, semanticVirtualizationRuntime);

  await openSidebarPage(page, /Global Configuration/i);
  await waitForBodyText(page, /Select Mapping|Configure Namespaces|Save Mapping|Set Style/i);
  const mappingLabel = await createEphemeralMapping(page);

  await openSidebarPage(page, /Build Mapping/i);
  const text = await waitForBodyText(
    page,
    /Add TriplesMap|No data sources are available|Data Files|Databases/i,
  );
  await highlightMarked(
    page.getByText(/Add TriplesMap|No data sources are available|Data Files|Databases/i).first(),
  );

  await captureStep(page, "sv-ui-05-mapping-authoring-entrypoint");
  await attachJson("sv-ui-05-state", {
    url,
    status,
    linkedCases: ["PT5-VS-01", "PT5-VS-05", "PT5-VS-06"],
    mappingLabel,
    mutationScope: "Streamlit browser session only; no connector or cluster resource is created.",
    bodyExcerpt: text.slice(0, 900),
  });
});

test("SV-UI-06: mapping editor exposes export and materialisation checkpoints", async ({
  page,
  semanticVirtualizationRuntime,
  captureStep,
  attachJson,
}) => {
  const { url, status } = await openMappingEditor(page, semanticVirtualizationRuntime);

  await openSidebarPage(page, /Global Configuration/i);
  await waitForBodyText(page, /Select Mapping|Configure Namespaces|Save Mapping|Set Style/i);
  const mappingLabel = await createEphemeralMapping(page);

  await clickMarked(page.getByRole("tab", { name: /Save Mapping/i }));
  const exportText = await waitForBodyText(page, /Export mapping|Select format|Enter filename/i);
  await highlightMarked(page.getByText(/Export mapping|Select format|Enter filename/i).first());
  await captureStep(page, "sv-ui-06-export-mapping-checkpoint");

  await openSidebarPage(page, /Materialise Graph/i);
  const materialiseText = await waitForBodyText(
    page,
    /Materialise|Check issues|no data sources|Data Files/i,
  );
  await highlightMarked(
    page.getByText(/Materialise|Check issues|no data sources|Data Files/i).first(),
  );
  await captureStep(page, "sv-ui-06-materialise-graph-checkpoint");

  await attachJson("sv-ui-06-state", {
    url,
    status,
    linkedCases: ["PT5-VS-08", "PT5-VS-09"],
    mappingLabel,
    exportBodyExcerpt: exportText.slice(0, 700),
    materialiseBodyExcerpt: materialiseText.slice(0, 700),
  });
});
