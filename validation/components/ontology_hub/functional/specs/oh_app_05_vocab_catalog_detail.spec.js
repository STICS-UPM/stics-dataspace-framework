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
  let catalogReady = true;
  let catalogFailure = "";
  try {
    await catalogPage.waitForResults();
  } catch (error) {
    catalogReady = false;
    catalogFailure = normalizeText(error?.message);
  }
  const initialCount = catalogReady
    ? await catalogPage.currentResultCount().catch(() => null)
    : null;
  await captureStep(page, "01-catalog-search");

  let openedLabel = "";
  let openSource = "none";
  let openFallbackReason = catalogFailure;
  if (catalogReady) {
    try {
      await catalogPage.search(query);
      const hasSuggestions = await safeWaitForSuggestions(catalogPage);

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
    } catch (error) {
      openFallbackReason = normalizeText(error?.message);
      if (!targetPrefix) {
        throw error;
      }
    }
  }

  if (openSource === "none" && targetPrefix) {
    openedLabel = targetPrefix;
    openSource = "direct-prefix-fallback";
    await detailPage.goto(flowRuntime.baseUrl, targetPrefix);
  } else {
    await page.waitForLoadState("domcontentloaded");
  }
  const detailMatch = page.url().match(/\/dataset\/vocabs\/([^/?#]+)/);
  const resolvedPrefix = detailMatch ? decodeURIComponent(detailMatch[1]) : targetPrefix;

  await detailPage.expectReady(resolvedPrefix, targetTitle);
  await detailPage.expectMetadataMarkers();
  await page.getByText(/Incoming Links/i).waitFor({ state: "visible", timeout: 5000 });
  const versionHistoryTab = page.locator(".ontology-tab").filter({ hasText: "Version History" }).first();
  if (await versionHistoryTab.isVisible().catch(() => false)) {
    await clickMarked(versionHistoryTab);
  }
  const versionHistoryHeading = page.getByText("Vocabulary Version History", { exact: true });
  await versionHistoryHeading.scrollIntoViewIfNeeded().catch(() => {});
  await versionHistoryHeading.waitFor({ state: "visible", timeout: 5000 });
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

  const detailUrl = page.url();
  await signOut(page, flowRuntime);

  await attachJson("05-vocab-visualization-report", {
    query,
    initialCount,
    openedLabel,
    openSource,
    openFallbackReason,
    resolvedPrefix,
    detailUrl,
    downloadInfo,
  });
});
