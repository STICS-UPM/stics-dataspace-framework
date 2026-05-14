const path = require("path");

const { test, expect } = require("../fixtures");
const { joinUrl } = require("../runtime");
const {
  checkMarked,
  clickMarked,
  fillMarked,
  highlightMarked,
  pressMarked,
} = require("../support/live-marker");

const ONTOLOGY_FIXTURE_PATH = path.resolve(
  __dirname,
  "..",
  "..",
  "fixtures",
  "ontology",
  "mobility-mini.owl",
);
const CSV_FIXTURE_PATH = path.resolve(
  __dirname,
  "..",
  "..",
  "fixtures",
  "sources",
  "csv",
  "stops.csv",
);
const MAPPING_FIXTURE_PATH = path.resolve(
  __dirname,
  "..",
  "..",
  "fixtures",
  "mappings",
  "mapping_editor_mobility_network.rml.ttl",
);

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

async function uploadStreamlitFileMarked(page, labelPattern, filePath) {
  const dropzone = page.getByLabel(labelPattern).first();
  await expect(dropzone).toBeVisible({ timeout: 30 * 1000 });
  await highlightMarked(dropzone);

  const fileInput = dropzone.locator('input[type="file"]').first();
  await expect(fileInput).toBeAttached({ timeout: 30 * 1000 });
  await fileInput.setInputFiles(filePath);
  await page.waitForLoadState("networkidle").catch(() => {});
}

async function chooseStreamlitSelectboxOptionMarked(page, labelPattern, optionPattern) {
  const selectbox = page.getByLabel(labelPattern).first();
  await expect(selectbox).toBeVisible({ timeout: 30 * 1000 });
  await clickMarked(selectbox);

  let option = page.getByRole("option", { name: optionPattern }).first();
  const optionVisible = await option
    .waitFor({ state: "visible", timeout: 10 * 1000 })
    .then(() => true)
    .catch(() => false);

  if (!optionVisible) {
    option = page.locator('[role="option"]').filter({ hasText: optionPattern }).first();
    await expect(option).toBeVisible({ timeout: 10 * 1000 });
  }

  await clickMarked(option);
  await page.waitForLoadState("networkidle").catch(() => {});
}

async function importMappingFixture(page) {
  const mappingLabel = `qaNetwork${String(Date.now()).slice(-8)}`;

  await openSidebarPage(page, /Global Configuration/i);
  await waitForBodyText(page, /Select Mapping|Configure Namespaces|Save Mapping|Set Style/i);

  const fileOption = page
    .getByRole("radiogroup", { name: /Select an option/i })
    .getByText(/File/i)
    .first();
  await expect(fileOption).toBeVisible({ timeout: 30 * 1000 });
  await clickMarked(fileOption);
  await page.waitForLoadState("networkidle").catch(() => {});

  await uploadStreamlitFileMarked(page, /Upload mapping file/i, MAPPING_FIXTURE_PATH);

  const labelInput = page.getByLabel(/Enter mapping label/i).last();
  await expect(labelInput).toBeVisible({ timeout: 45 * 1000 });
  await fillMarked(labelInput, mappingLabel);
  await pressMarked(labelInput, "Enter");
  await page.waitForLoadState("networkidle").catch(() => {});

  const importButton = page.getByRole("button", { name: /^Import$/ }).first();
  await expect(importButton).toBeVisible({ timeout: 45 * 1000 });
  await clickMarked(importButton);

  await waitForBodyText(page, new RegExp(mappingLabel, "i"));
  const importedText = await expect
    .poll(() => bodyText(page), { timeout: 45 * 1000 })
    .toMatch(/[1-9]\d* TriplesMaps/i)
    .then(() => bodyText(page));

  return { mappingLabel, importedText };
}

async function importOntologyFixture(page) {
  await openSidebarPage(page, /Ontologies/i);
  await waitForBodyText(page, /Import Ontology|Explore Ontology|View Ontology|Custom Terms/i);

  const fileOption = page
    .getByRole("radiogroup", { name: /Import ontology from/i })
    .getByText(/File/i)
    .first();
  await expect(fileOption).toBeVisible({ timeout: 30 * 1000 });
  await clickMarked(fileOption);
  await page.waitForLoadState("networkidle").catch(() => {});

  await uploadStreamlitFileMarked(page, /Upload ontology file/i, ONTOLOGY_FIXTURE_PATH);

  const addButton = page.getByRole("button", { name: /^Add$/ }).first();
  await expect(addButton).toBeVisible({ timeout: 45 * 1000 });
  await clickMarked(addButton);

  const importedText = await waitForBodyText(
    page,
    /Remove Ontology|ontology.*imported|mobility|PIONERA|Stop|Route/i,
  );
  await highlightMarked(
    page.getByText(/Remove Ontology|ontology.*imported|mobility|PIONERA|Stop|Route/i).first(),
  );

  return importedText;
}

test.describe("Mapping editor validation", () => {
  test.skip(
    process.env.SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_UI !== "1",
    "Mapping editor validation was disabled explicitly for this execution.",
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

test("SV-UI-07: mapping editor manages namespaces and exports a mapping", async ({
  page,
  semanticVirtualizationRuntime,
  captureStep,
  attachJson,
}) => {
  test.setTimeout(4 * 60 * 1000);

  const { url, status } = await openMappingEditor(page, semanticVirtualizationRuntime);

  await test.step("Create an ephemeral mapping from Global Configuration", async () => {
    await openSidebarPage(page, /Global Configuration/i);
    await waitForBodyText(page, /Select Mapping|Configure Namespaces|Save Mapping|Set Style/i);
  });

  const mappingLabel = await createEphemeralMapping(page);

  const namespacePrefix = `qa${String(Date.now()).slice(-6)}`;
  const namespaceIri = `https://pionera.example/ns/${namespacePrefix}#`;

  await test.step("Bind a custom namespace for the mapping", async () => {
    await clickMarked(page.getByRole("tab", { name: /Configure Namespaces/i }));
    await waitForBodyText(page, /Enter prefix|Enter IRI|Base|Predefined/i);

    await fillMarked(page.getByLabel(/Enter prefix/i).first(), namespacePrefix);
    const iriInput = page.getByLabel(/Enter IRI for the new namespace/i).first();
    await fillMarked(iriInput, namespaceIri);
    await pressMarked(iriInput, "Enter");
    await page.waitForLoadState("networkidle").catch(() => {});

    const bindButton = page.getByRole("button", { name: /^Bind$/ }).first();
    await expect(bindButton).toBeVisible({ timeout: 30 * 1000 });
    await clickMarked(bindButton);

    await waitForBodyText(page, new RegExp(`${namespacePrefix}|Namespace|bound`, "i"));
    await highlightMarked(page.getByText(new RegExp(`${namespacePrefix}|Namespace|bound`, "i")).first());
    await captureStep(page, "sv-ui-07-custom-namespace-bound");
  });

  await test.step("Export the mapping from the UI", async () => {
    await clickMarked(page.getByRole("tab", { name: /Save Mapping/i }));
    await waitForBodyText(page, /Export mapping|Select format|Enter filename/i);

    const exportFilename = `qa_mapping_${String(Date.now()).slice(-6)}`;
    const filenameInput = page.getByLabel(/Enter filename/i).first();
    await fillMarked(filenameInput, exportFilename);
    await pressMarked(filenameInput, "Enter");
    await page.waitForLoadState("networkidle").catch(() => {});

    const exportButton = page.getByRole("button", { name: /^Export$/ }).first();
    await expect(exportButton).toBeVisible({ timeout: 30 * 1000 });
    await highlightMarked(exportButton);

    const downloadPromise = page.waitForEvent("download", { timeout: 15 * 1000 }).catch(() => null);
    await clickMarked(exportButton);
    const download = await downloadPromise;
    expect(download, "Expected mapping export to produce a browser download").not.toBeNull();

    await captureStep(page, "sv-ui-07-export-mapping");
    await attachJson("sv-ui-07-export-state", {
      url,
      status,
      linkedCases: ["PT5-VS-09"],
      mappingLabel,
      namespacePrefix,
      namespaceIri,
      exportDownloadObserved: Boolean(download),
      suggestedFilename: download ? download.suggestedFilename() : null,
      bodyExcerpt: (await bodyText(page)).slice(0, 900),
    });
  });

  await test.step("Open style controls for visual evidence", async () => {
    await clickMarked(page.getByRole("tab", { name: /Set Style/i }));
    const styleText = await waitForBodyText(page, /Style|Dark|Light|theme|mode/i);
    const toggle = page.getByRole("checkbox").first();
    if (await toggle.isVisible().catch(() => false)) {
      await checkMarked(toggle).catch(() => highlightMarked(toggle));
    } else {
      await highlightMarked(page.getByText(/Style|Dark|Light|theme|mode/i).first());
    }

    await captureStep(page, "sv-ui-07-style-controls");
    await attachJson("sv-ui-07-state", {
      url,
      status,
      linkedCases: ["PT5-VS-07", "PT5-VS-09"],
      mappingLabel,
      namespacePrefix,
      namespaceIri,
      mutationScope: "Streamlit browser session only; no connector or cluster resource is created.",
      bodyExcerpt: styleText.slice(0, 700),
    });
  });
});

test("SV-UI-08: mapping editor imports ontology and data source fixtures", async ({
  page,
  semanticVirtualizationRuntime,
  captureStep,
  attachJson,
}) => {
  test.setTimeout(4 * 60 * 1000);

  const { url, status } = await openMappingEditor(page, semanticVirtualizationRuntime);

  await test.step("Create an isolated mapping session", async () => {
    await openSidebarPage(page, /Global Configuration/i);
    await waitForBodyText(page, /Select Mapping|Configure Namespaces|Save Mapping|Set Style/i);
  });
  const mappingLabel = await createEphemeralMapping(page);

  await test.step("Import the mobility ontology fixture from the UI", async () => {
    await openSidebarPage(page, /Ontologies/i);
    await waitForBodyText(page, /Import Ontology|Explore Ontology|View Ontology|Custom Terms/i);

    const fileOption = page
      .getByRole("radiogroup", { name: /Import ontology from/i })
      .getByText(/File/i)
      .first();
    await expect(fileOption).toBeVisible({ timeout: 30 * 1000 });
    await clickMarked(fileOption);
    await page.waitForLoadState("networkidle").catch(() => {});

    await uploadStreamlitFileMarked(page, /Upload ontology file/i, ONTOLOGY_FIXTURE_PATH);

    const addButton = page.getByRole("button", { name: /^Add$/ }).first();
    await expect(addButton).toBeVisible({ timeout: 45 * 1000 });
    await clickMarked(addButton);

    const importedText = await waitForBodyText(
      page,
      /Remove Ontology|ontology.*imported|mobility|PIONERA|Stop|Route/i,
    );
    await highlightMarked(
      page.getByText(/Remove Ontology|ontology.*imported|mobility|PIONERA|Stop|Route/i).first(),
    );
    await captureStep(page, "sv-ui-08-ontology-imported");

    await clickMarked(page.getByRole("tab", { name: /Explore Ontology/i }));
    const exploredText = await waitForBodyText(
      page,
      /Explore Ontology|Results|Classes|Properties|Stop|Route/i,
    );
    await highlightMarked(
      page.getByText(/Explore Ontology|Results|Classes|Properties|Stop|Route/i).first(),
    );
    await captureStep(page, "sv-ui-08-ontology-explored");

    await attachJson("sv-ui-08-ontology-state", {
      mappingLabel,
      ontologyFixture: path.basename(ONTOLOGY_FIXTURE_PATH),
      importedBodyExcerpt: importedText.slice(0, 900),
      exploredBodyExcerpt: exploredText.slice(0, 900),
    });
  });

  await test.step("Upload the CSV data source fixture from the UI", async () => {
    await openSidebarPage(page, /Data Files/i);
    await waitForBodyText(page, /Manage Files|Display Data|Manage Paths|Upload File/i);

    await uploadStreamlitFileMarked(page, /Upload data source file/i, CSV_FIXTURE_PATH);

    const saveButton = page.getByRole("button", { name: /^Save$/ }).first();
    await expect(saveButton).toBeVisible({ timeout: 45 * 1000 });
    await clickMarked(saveButton);

    const uploadedText = await waitForBodyText(
      page,
      /Remove Files|uploaded files|stops\.csv|data source file/i,
    );
    await highlightMarked(
      page.getByText(/Remove Files|uploaded files|stops\.csv|data source file/i).first(),
    );
    await captureStep(page, "sv-ui-08-data-source-uploaded");

    await clickMarked(page.getByRole("tab", { name: /Display Data/i }));
    const displayText = await waitForBodyText(page, /Display Table|Select file|stops\.csv/i);
    await highlightMarked(page.getByText(/Display Table|Select file|stops\.csv/i).first());
    await captureStep(page, "sv-ui-08-data-display-panel");

    await attachJson("sv-ui-08-state", {
      url,
      status,
      linkedCases: ["PT5-VS-01", "PT5-VS-06", "PT5-VS-07"],
      mappingLabel,
      ontologyFixture: path.basename(ONTOLOGY_FIXTURE_PATH),
      csvFixture: path.basename(CSV_FIXTURE_PATH),
      mutationScope: "Streamlit browser session only; no connector or cluster resource is created.",
      uploadedBodyExcerpt: uploadedText.slice(0, 900),
      displayBodyExcerpt: displayText.slice(0, 900),
    });
  });
});

test("SV-UI-10: mapping editor explores a non-empty mapping with ontology lens", async ({
  page,
  semanticVirtualizationRuntime,
  captureStep,
  attachJson,
}) => {
  test.setTimeout(5 * 60 * 1000);

  const { url, status } = await openMappingEditor(page, semanticVirtualizationRuntime);
  const { mappingLabel, importedText } = await importMappingFixture(page);
  await highlightMarked(page.getByText(/[1-9]\d* TriplesMaps/i).first());
  await captureStep(page, "sv-ui-10-mapping-imported");

  const ontologyText = await importOntologyFixture(page);
  await captureStep(page, "sv-ui-10-ontology-imported");

  await test.step("Explore the imported mapping as a network", async () => {
    await openSidebarPage(page, /Explore Mapping/i);
    const networkText = await waitForBodyText(
      page,
      /Network Visualisation|Select TriplesMaps|StopTriplesMap|RouteTriplesMap|Subject legend/i,
    );
    expect(networkText).not.toMatch(/contains no TriplesMaps/i);
    await highlightMarked(
      page
        .getByText(/Network Visualisation|Select TriplesMaps|StopTriplesMap|RouteTriplesMap|Subject legend/i)
        .first(),
    );
    await captureStep(page, "sv-ui-10-network-view");
  });

  let triplesMapsText = "";
  let subjectMapsText = "";
  let predicateObjectText = "";
  let previewText = "";

  await test.step("Inspect predefined mapping searches", async () => {
    await clickMarked(page.getByRole("tab", { name: /Predefined Searches/i }));
    await waitForBodyText(page, /Predefined Searches|Select search/i);

    await chooseStreamlitSelectboxOptionMarked(page, /Select search/i, /TriplesMaps/i);
    triplesMapsText = await waitForBodyText(
      page,
      /TriplesMap|StopTriplesMap|RouteTriplesMap|sources\/csv\/stops\.csv|sources\/json\/routes\.json/i,
    );
    await highlightMarked(
      page
        .getByText(/TriplesMap|StopTriplesMap|RouteTriplesMap|sources\/csv\/stops\.csv|sources\/json\/routes\.json/i)
        .first(),
    );
    await captureStep(page, "sv-ui-10-predefined-triplesmaps");

    await chooseStreamlitSelectboxOptionMarked(page, /Select search/i, /Subject Maps/i);
    subjectMapsText = await waitForBodyText(
      page,
      /Subject Maps|stop\/\{stop_id\}|route\/\{route_id\}|Stop|Route/i,
    );
    await highlightMarked(
      page.getByText(/Subject Maps|stop\/\{stop_id\}|route\/\{route_id\}|Stop|Route/i).first(),
    );
    await captureStep(page, "sv-ui-10-predefined-subject-maps");

    await chooseStreamlitSelectboxOptionMarked(page, /Select search/i, /Predicate-Object Maps/i);
    predicateObjectText = await waitForBodyText(
      page,
      /Predicate-Object Maps|hasStopName|hasLatitude|hasLongitude|routeShortName|servesStop/i,
    );
    await highlightMarked(
      page
        .getByText(/Predicate-Object Maps|hasStopName|hasLatitude|hasLongitude|routeShortName|servesStop/i)
        .first(),
    );
    await captureStep(page, "sv-ui-10-predefined-predicate-object-maps");
  });

  await test.step("Preview the imported mapping serialisation", async () => {
    await clickMarked(page.getByRole("tab", { name: /Preview/i }));
    previewText = await waitForBodyText(
      page,
      /Preview|Select format|StopTriplesMap|RouteTriplesMap|hasStopName|servesStop/i,
    );
    await highlightMarked(
      page
        .getByText(/Preview|Select format|StopTriplesMap|RouteTriplesMap|hasStopName|servesStop/i)
        .first(),
    );
    await captureStep(page, "sv-ui-10-mapping-preview");
  });

  let compositionText = "";
  let classUsageText = "";
  let propertyUsageText = "";
  let externalTermsText = "";

  await test.step("Explain the mapping through Ontology-Mapping Lens", async () => {
    await openSidebarPage(page, /Ontology-Mapping Lens/i);
    compositionText = await waitForBodyText(
      page,
      /Mapping composition by ontology|#TriplesMap|#Rules|composition calculated/i,
    );
    await highlightMarked(
      page.getByText(/Mapping composition by ontology|#TriplesMap|#Rules|composition calculated/i).first(),
    );
    await captureStep(page, "sv-ui-10-lens-composition");

    await clickMarked(page.getByRole("tab", { name: /Class Usage/i }));
    classUsageText = await waitForBodyText(page, /Class Usage|Stop|Route|used|frequency/i);
    await highlightMarked(page.getByText(/Class Usage|Stop|Route|used|frequency/i).first());
    await captureStep(page, "sv-ui-10-lens-class-usage");

    await clickMarked(page.getByRole("tab", { name: /Property Usage/i }));
    propertyUsageText = await waitForBodyText(
      page,
      /Property Usage|hasStopName|hasLatitude|hasLongitude|routeShortName|servesStop|used/i,
    );
    await highlightMarked(
      page
        .getByText(/Property Usage|hasStopName|hasLatitude|hasLongitude|routeShortName|servesStop|used/i)
        .first(),
    );
    await captureStep(page, "sv-ui-10-lens-property-usage");

    await clickMarked(page.getByRole("tab", { name: /External Terms/i }));
    externalTermsText = await waitForBodyText(page, /External Terms|external|terms|ontology/i);
    await highlightMarked(page.getByText(/External Terms|external|terms|ontology/i).first());
    await captureStep(page, "sv-ui-10-lens-external-terms");
  });

  await attachJson("sv-ui-10-state", {
    url,
    status,
    linkedCases: ["PT5-VS-01", "PT5-VS-06", "PT5-VS-07", "PT5-VS-09"],
    mappingLabel,
    mappingFixture: path.basename(MAPPING_FIXTURE_PATH),
    ontologyFixture: path.basename(ONTOLOGY_FIXTURE_PATH),
    mutationScope: "Streamlit browser session only; no connector or cluster resource is created.",
    importedBodyExcerpt: importedText.slice(0, 900),
    ontologyBodyExcerpt: ontologyText.slice(0, 900),
    predefinedSearchExcerpts: {
      triplesMaps: triplesMapsText.slice(0, 700),
      subjectMaps: subjectMapsText.slice(0, 700),
      predicateObjectMaps: predicateObjectText.slice(0, 700),
    },
    previewBodyExcerpt: previewText.slice(0, 700),
    lensExcerpts: {
      composition: compositionText.slice(0, 700),
      classUsage: classUsageText.slice(0, 700),
      propertyUsage: propertyUsageText.slice(0, 700),
      externalTerms: externalTermsText.slice(0, 700),
    },
  });
});
});
