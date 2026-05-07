// Excel traceability: Ontology Hub cases 22, 23 and 24.
const fs = require("fs");

const { test, expect } = require("../../ui/fixtures");
const { checkMarked, clickMarked, setInputFilesMarked } = require("../../ui/support/live-marker");
const { OntologyHubHomePage } = require("../../ui/pages/home.page");
const { OntologyHubVocabCatalogPage } = require("../../ui/pages/vocab-catalog.page");
const {
  expectHealthyPage,
  listZipEntries,
  loadRunState,
  openThemisPanel,
  openVocabularyDetail,
  persistGeneratedArtifact,
  resolveThemisTestFile,
  runtimeFromCreatedVocabulary,
  resolveThemisSource,
  signInToEdition,
  signOut,
  URI_VOCAB_STATE_KEY,
} = require("../support/excel-flows");

async function waitForThemisResults(page, timeoutMs = 30000) {
  await page.waitForFunction(
    () => {
      const isVisible = (node) =>
        Boolean(node) && Boolean(node.offsetWidth || node.offsetHeight || node.getClientRects().length);
      const headings = Array.from(document.querySelectorAll("h1, h2, h3"));
      const buttons = Array.from(document.querySelectorAll("button"));
      const rows = Array.from(document.querySelectorAll("table tr"));

      const resultsHeadingVisible = headings.some(
        (node) => isVisible(node) && /tests results/i.test(String(node.textContent || "")),
      );
      const downloadButtonVisible = buttons.some(
        (node) => isVisible(node) && /download results/i.test(String(node.textContent || "")),
      );
      const resultRowVisible = rows.some(
        (node) => isVisible(node) && /test\s+\d+/i.test(String(node.textContent || "")),
      );

      return resultsHeadingVisible && (downloadButtonVisible || resultRowVisible);
    },
    { timeout: timeoutMs },
  );
}

test("OH-APP-22: patterns page generates a zip", async ({
  page,
  ontologyHubRuntime,
  captureStep,
  attachJson,
}, testInfo) => {
  await signInToEdition(page, ontologyHubRuntime);
  await page.goto(`${ontologyHubRuntime.baseUrl}/dataset/patterns`, { waitUntil: "domcontentloaded" });
  await expectHealthyPage(page, "Patterns");

  const selectAllButton = page.locator("button, input[type='submit'], input[type='button']").filter({
    hasText: /select all/i,
  }).first();
  if ((await selectAllButton.count()) === 0) {
    throw new Error("Patterns page does not expose the 'Select All' control expected by the Excel flow.");
  }

  await clickMarked(selectAllButton);

  const bothOption = page.getByLabel(/both/i).first();
  if ((await bothOption.count()) > 0) {
    await checkMarked(bothOption).catch(async () => {
      await clickMarked(bothOption);
    });
  }

  const noOption = page.getByLabel(/^no$/i).first();
  if ((await noOption.count()) > 0) {
    await checkMarked(noOption).catch(async () => {
      await clickMarked(noOption);
    });
  }

  const submitButton = page.locator("button, input[type='submit']").filter({ hasText: /submit/i }).first();
  if ((await submitButton.count()) === 0) {
    throw new Error("Patterns page does not expose the Submit control expected by the Excel flow.");
  }

  const downloadPromise = page.waitForEvent("download", { timeout: 30000 });
  await clickMarked(submitButton);
  const download = await downloadPromise;
  const filePath = testInfo.outputPath("patterns.zip");
  await download.saveAs(filePath);
  const persistedPath = persistGeneratedArtifact(filePath, "excel-22-patterns.zip", "patterns");

  const stat = fs.statSync(filePath);
  expect(stat.size).toBeGreaterThan(0);
  const entries = listZipEntries(filePath);
  const hasDataFolder = entries.some((entry) => entry.startsWith("data/"));
  const hasWebFolder = entries.some((entry) => entry.startsWith("web/"));
  expect(hasDataFolder).toBeTruthy();
  expect(hasWebFolder).toBeTruthy();

  const expectedDataFiles = ["error.log.txt", "Patterns_name.txt", "Patterns_type.txt", "Structure.csv"];
  const expectedWebFiles = ["PatternName.html", "PatternType.html", "Structure.html"];
  const missingDataFiles = expectedDataFiles.filter(
    (file) => !entries.some((entry) => entry === `data/${file}` || entry.endsWith(`/${file}`)),
  );
  const missingWebFiles = expectedWebFiles.filter(
    (file) => !entries.some((entry) => entry === `web/${file}` || entry.endsWith(`/${file}`)),
  );
  if (missingDataFiles.length > 0 || missingWebFiles.length > 0) {
    throw new Error(
      `ZIP content does not match Excel spec. Missing in data/: [${missingDataFiles.join(", ")}]. ` +
        `Missing in web/: [${missingWebFiles.join(", ")}].`,
    );
  }

  await captureStep(page, "22-patterns");
  await signOut(page, ontologyHubRuntime);

  await attachJson("22-patterns-report", {
    downloadFile: download.suggestedFilename(),
    size: stat.size,
    entries,
    hasDataFolder,
    hasWebFolder,
    missingDataFiles,
    missingWebFiles,
    persistedPath,
  });
});

test("OH-APP-23: FOOPS metrics are shown for a vocabulary", async ({
  page,
  ontologyHubRuntime,
  captureStep,
  attachJson,
}) => {
  const created = loadRunState(URI_VOCAB_STATE_KEY);
  const flowRuntime = runtimeFromCreatedVocabulary(ontologyHubRuntime, created);
  await signInToEdition(page, flowRuntime);
  const prefix = created.prefix;
  const title = created.title;

  const catalogPage = new OntologyHubVocabCatalogPage(page);
  await Promise.all([
    page.waitForURL(/\/dataset\/vocabs(?:\?|$)/, { timeout: 5000 }),
    clickMarked(page.getByRole("link", { name: /vocabs/i }).first()),
  ]);
  await catalogPage.expectReady();
  await catalogPage.search("saref4grid");
  await catalogPage.waitForSuggestions().catch(async () => {
    await catalogPage.waitForResults();
  });
  if ((await catalogPage.suggestionItems().count().catch(() => 0)) > 0) {
    await catalogPage.openSuggestion("saref4grid");
  } else {
    await catalogPage.expectResultVisible("saref4grid");
    await catalogPage.openResult(prefix);
  }

  await openVocabularyDetail(page, flowRuntime, prefix, title);
  const foopsTab = page.getByRole("tab", { name: /foops/i }).first();
  await foopsTab.waitFor({ state: "visible", timeout: 5000 });
  await foopsTab.scrollIntoViewIfNeeded();
  await page.evaluate(() => {
    if (typeof window.activateOntologyTab === "function") {
      window.activateOntologyTab("foops");
      return;
    }

    const tab = document.querySelector(".ontology-tab[data-onto-target='foops']");
    if (tab instanceof HTMLElement) {
      tab.click();
    }
  });
  await page.waitForFunction(() => {
    const tab = document.querySelector(".ontology-tab[data-onto-target='foops']");
    const panel = document.querySelector(".ontology-tab-panel[data-onto-panel='foops']");
    return (
      tab?.getAttribute("aria-selected") === "true" &&
      panel?.classList.contains("is-active")
    );
  }, { timeout: 5000 });
  await page.locator("#foopsHeader").waitFor({ state: "visible", timeout: 5000 });
  const foopsResults = page.locator("#foops-results");
  const callFoopsButton = page.locator("#callFoopsButton");
  const bodyText = await page
    .locator("body")
    .evaluate((node) => (node.textContent || "").replace(/\s+/g, " ").trim())
    .catch(() => "");
  const foopsAlreadyRendered =
    /FOOPS! FAIR VALIDATOR/i.test(bodyText) &&
    /(Reusable|Findable|Accessible|Interoperable)/i.test(bodyText);
  if (!(await foopsResults.isVisible().catch(() => false)) && !foopsAlreadyRendered) {
    await callFoopsButton.waitFor({ state: "visible", timeout: 5000 });
    await clickMarked(callFoopsButton);
    await foopsResults.waitFor({ state: "visible", timeout: 5000 });
  }
  await page.locator("text=/FOOPS! FAIR VALIDATOR/i").first().waitFor({ state: "visible", timeout: 5000 });
  await captureStep(page, "23-foops");
  await signOut(page, flowRuntime);

  await attachJson("23-foops-report", {
    prefix,
    title,
    searchTerm: "saref4grid",
    url: page.url(),
  });
});

test("OH-APP-24: Themis accepts a test file and downloads results", async ({
  page,
  ontologyHubRuntime,
  captureStep,
  attachJson,
}, testInfo) => {
  const created = loadRunState(URI_VOCAB_STATE_KEY);
  const flowRuntime = runtimeFromCreatedVocabulary(ontologyHubRuntime, created);
  await signInToEdition(page, flowRuntime);
  const prefix = created.prefix;
  const title = created.title;

  const homePage = new OntologyHubHomePage(page);
  await homePage.goto(flowRuntime.baseUrl);
  await homePage.expectReady();
  await homePage.openVocabularyBubble(prefix);
  const detailUrlPattern = new RegExp(`/dataset/vocabs/${prefix.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`);
  const graphNavigationCompleted = await page
    .waitForURL(detailUrlPattern, {
      timeout: 10000,
      waitUntil: "commit",
    })
    .then(() => true)
    .catch(() => false);
  if (!graphNavigationCompleted) {
    await openVocabularyDetail(page, flowRuntime, prefix, title);
  }
  await expectHealthyPage(page, `Vocabulary detail for ${prefix}`);
  const themisActivation = await openThemisPanel(page);
  const themisSource = await resolveThemisSource(page);
  const sourceUrl = themisSource.sourceUrl || `/dataset/vocabs/${prefix}/versions/${themisSource.prefix || ""}.n3`;
  const testFilePath = resolveThemisTestFile();
  const persistedUploadedPath = persistGeneratedArtifact(testFilePath, "excel-24-test_cases.txt", "themis");

  await checkMarked(page.locator("#themisModeManual")).catch(async () => {
    await clickMarked(page.locator("#themisModeManual"));
  });
  await page.locator("label").filter({ hasText: /user tests/i }).first().waitFor({ state: "visible", timeout: 5000 }).catch(() => {});
  await page.locator("#themisUploadContainer").waitFor({ state: "visible", timeout: 5000 });
  await setInputFilesMarked(page.locator("#themisTestFile"), testFilePath);
  await clickMarked(page.locator("#executeThemisButton"));
  await waitForThemisResults(page);
  await page.getByRole("heading", { name: /tests results/i, level: 3 }).first().waitFor({
    state: "visible",
    timeout: 5000,
  });
  await page.getByRole("button", { name: /download results/i }).first().waitFor({
    state: "visible",
    timeout: 5000,
  });

  const downloadPromise = page.waitForEvent("download", { timeout: 30000 });
  await clickMarked(page.getByRole("button", { name: /download results/i }).first());
  const download = await downloadPromise;
  const outputPath = testInfo.outputPath("themis-results.txt");
  await download.saveAs(outputPath);
  const persistedResultPath = persistGeneratedArtifact(outputPath, "excel-24-themis-results.txt", "themis");
  const stat = fs.statSync(outputPath);
  expect(stat.size).toBeGreaterThan(0);
  const themisUrl = page.url();

  await captureStep(page, "24-themis");
  await signOut(page, flowRuntime);

  await attachJson("24-themis-report", {
    prefix,
    title,
    themisActivation,
    sourceUrl,
    themisUrl,
    uploadedFile: testFilePath,
    persistedUploadedPath,
    resultDownload: download.suggestedFilename(),
    resultSize: stat.size,
    persistedResultPath,
    graphNavigationCompleted,
  });
});
