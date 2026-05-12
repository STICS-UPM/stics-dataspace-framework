const { test, expect } = require("../../ui/fixtures");
const { OntologyHubVocabCatalogPage } = require("../../ui/pages/vocab-catalog.page");
const { OntologyHubVocabDetailPage } = require("../../ui/pages/vocab-detail.page");

test("OH-LIST-SEARCH: public catalog lists vocabularies and opens a search result", async ({
  page,
  ontologyHubRuntime,
  ontologyHubBootstrap,
  captureStep,
  attachJson,
}) => {
  const autocompleteProbe = ontologyHubBootstrap.capabilities.autocompleteProbe;

  const catalogPage = new OntologyHubVocabCatalogPage(page);
  const detailPage = new OntologyHubVocabDetailPage(page);
  const query =
    autocompleteProbe.query || ontologyHubBootstrap.prefix || ontologyHubRuntime.listingSearchTerm;
  const targetPrefix = autocompleteProbe.prefix || ontologyHubBootstrap.prefix;
  const targetTitle = autocompleteProbe.title || ontologyHubBootstrap.title;
  const mode = autocompleteProbe.available ? "autocomplete" : "catalog_search_fallback";

  await catalogPage.goto(ontologyHubRuntime.baseUrl, query);
  await catalogPage.expectReady();
  let suggestions = [];
  let openedResult = "";
  if (autocompleteProbe.available) {
    await catalogPage.search(query);
    await catalogPage.waitForSuggestions();
    suggestions = await catalogPage.suggestionLabels();
    expect(suggestions.length).toBeGreaterThan(0);
    await captureStep(page, "01-vocabulary-autocomplete");
    openedResult = await catalogPage.openSuggestion(targetPrefix);
  } else {
    await catalogPage.waitForResults();
    await catalogPage.expectResultVisible(targetPrefix);
    await captureStep(page, "01-vocabulary-catalog-search");
    openedResult = await catalogPage.openResult(targetPrefix);
  }

  await expect(page).toHaveURL(new RegExp(`/dataset/vocabs/${targetPrefix}/?$`));
  await detailPage.expectReady(targetPrefix, targetTitle);
  await captureStep(page, "02-opened-search-result");

  await attachJson("oh-list-search-report", {
    mode,
    query,
    suggestions,
    openedResult,
    targetPrefix,
    autocompleteAvailable: autocompleteProbe.available,
    autocompleteReason: autocompleteProbe.reason || "",
    finalUrl: page.url(),
  });
});
