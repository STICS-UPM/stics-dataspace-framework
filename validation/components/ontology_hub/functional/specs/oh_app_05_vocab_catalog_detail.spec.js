// Excel traceability: Ontology Hub case 5 (Visualizar Ontologia), adapted to the current UI.
const { test } = require("../../ui/fixtures");
const { OntologyHubVocabCatalogPage } = require("../../ui/pages/vocab-catalog.page");
const { OntologyHubVocabDetailPage } = require("../../ui/pages/vocab-detail.page");
const {
  openFirstCatalogResult,
  safeWaitForSuggestions,
} = require("../support/functional");
const { clickMarked } = require("../../ui/support/live-marker");
const {
  downloadFirstN3,
  loadRunState,
  normalizeText,
  runtimeFromCreatedVocabulary,
  saveRunState,
  signInToEdition,
  signOut,
  REPOSITORY_VOCAB_STATE_KEY,
  VISUALIZATION_N3_STATE_KEY,
} = require("../support/excel-flows");

test("OH-APP-05: vocabulary detail is visible and the .n3 can be downloaded", async ({
  page,
  ontologyHubRuntime,
  captureStep,
  attachJson,
}, testInfo) => {
  const created = loadRunState(REPOSITORY_VOCAB_STATE_KEY);
  const flowRuntime = runtimeFromCreatedVocabulary(ontologyHubRuntime, created);
  await signInToEdition(page, flowRuntime);

  const catalogPage = new OntologyHubVocabCatalogPage(page);
  const detailPage = new OntologyHubVocabDetailPage(page);
  const query = normalizeText(created.catalogLabel || created.title || created.prefix);
  const targetPrefix = normalizeText(created.prefix);
  const targetTitle = normalizeText(created.title);

  await catalogPage.goto(flowRuntime.baseUrl, query);
  await catalogPage.expectReady();
  await catalogPage.waitForResults();
  const initialCount = await catalogPage.currentResultCount().catch(() => null);
  await captureStep(page, "01-catalog-search");

  await catalogPage.search(query);
  const hasSuggestions = await safeWaitForSuggestions(catalogPage);

  let openedLabel = "";
  let openSource = "none";
  if (hasSuggestions) {
    if (targetPrefix) {
      try {
        openedLabel = await catalogPage.openSuggestion(targetPrefix);
        openSource = "autocomplete-target";
      } catch (error) {
        openedLabel = await catalogPage.openSuggestion();
        openSource = "autocomplete-first";
      }
    } else {
      openedLabel = await catalogPage.openSuggestion();
      openSource = "autocomplete-first";
    }
  } else if (targetPrefix) {
    openedLabel = await catalogPage.openResult(targetPrefix);
    openSource = "result-prefix";
  } else {
    const fallback = await openFirstCatalogResult(page);
    openedLabel = fallback.label;
    openSource = fallback.source;
  }

  await page.waitForLoadState("domcontentloaded", { timeout: 10000 }).catch(() => {});
  const detailMatch = page.url().match(/\/dataset\/vocabs\/([^/?#]+)/);
  const resolvedPrefix = detailMatch ? decodeURIComponent(detailMatch[1]) : targetPrefix;

  await detailPage.expectReady(resolvedPrefix, targetTitle);
  await detailPage.expectMetadataMarkers();
  await page.locator("a[href$='.n3']").first().waitFor({ state: "visible", timeout: 5000 });
  await captureStep(page, "02-vocab-detail");

  const generalTab = page.locator(".ontology-tab").filter({ hasText: "General" }).first();
  if (await generalTab.isVisible().catch(() => false)) {
    await clickMarked(generalTab);
  }
  const downloadInfo = await downloadFirstN3(page, testInfo, "05-vocab-download", {
    runtime: flowRuntime,
  });
  saveRunState(VISUALIZATION_N3_STATE_KEY, {
    ...downloadInfo,
    vocabularyPrefix: targetPrefix,
    vocabularyTitle: targetTitle,
  });
  await captureStep(page, "03-vocab-n3-downloaded");

  await signOut(page, flowRuntime);

  await attachJson("05-vocab-visualization-report", {
    query,
    initialCount,
    openedLabel,
    openSource,
    resolvedPrefix,
    detailUrl: page.url(),
    downloadInfo,
  });
});
