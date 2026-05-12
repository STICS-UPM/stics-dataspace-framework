// Excel traceability: Ontology Hub cases 26 and 27.
const { test } = require("../../ui/fixtures");
const { clickMarked } = require("../../ui/support/live-marker");
const { OntologyHubTermsPage } = require("../../ui/pages/terms.page");
const { probeTermSearchApi } = require("../../ui/support/capabilities");
const {
  waitForTermsReady,
  waitForTermsResults,
} = require("../support/functional");
const {
  loadRunState,
  runtimeFromCreatedVocabulary,
  signInToEdition,
  signOut,
  URI_VOCAB_STATE_KEY,
} = require("../support/excel-flows");

async function applyFacetLink(page, termsPage, groupLabel, valueLabel) {
  const facetLink = termsPage.facetLink(groupLabel, valueLabel);
  if ((await facetLink.count()) === 0) {
    throw new Error(`Terms facet '${groupLabel}' with value '${valueLabel}' is not available.`);
  }

  await clickMarked(facetLink);
  await page.waitForLoadState("networkidle", { timeout: 5000 });
  await waitForTermsReady(page, 5000);
  await waitForTermsResults(page, 5000);
  const count = await termsPage.currentResultCount().catch(() => null);
  if (!count || count <= 0) {
    throw new Error(`Terms facet '${groupLabel}' with value '${valueLabel}' returned no results.`);
  }
  return { applied: true, url: page.url(), count };
}

async function runTermsFacetCase(page, ontologyHubRuntime, valueLabel, captureStep, attachJson, reportName) {
  const created = loadRunState(URI_VOCAB_STATE_KEY);
  const flowRuntime = runtimeFromCreatedVocabulary(ontologyHubRuntime, created, {
    expectedSearchTerm: created.prefix,
  });
  const termProbe = await probeTermSearchApi(page.request, flowRuntime, { refresh: true });
  if (!termProbe.available) {
    throw new Error(termProbe.reason || "No searchable terms were derived from the ontology created in OH-APP-03.");
  }

  await signInToEdition(page, flowRuntime);
  const termsPage = new OntologyHubTermsPage(page);
  const query = termProbe.query;

  await termsPage.goto(flowRuntime.baseUrl, query);
  await waitForTermsReady(page, 5000);
  await waitForTermsResults(page, 5000);
  const outcome = await applyFacetLink(page, termsPage, /Type/i, valueLabel);

  await captureStep(page, reportName);
  await signOut(page, flowRuntime);

  await attachJson(`${reportName}-report`, {
    vocabulary: created,
    query,
    termProbe,
    outcome,
  });
}

test("OH-APP-26: terms filter by class", async ({
  page,
  ontologyHubRuntime,
  captureStep,
  attachJson,
}) => {
  await runTermsFacetCase(page, ontologyHubRuntime, /class/i, captureStep, attachJson, "26-terms-class-filter");
});

test("OH-APP-27: terms filter by property", async ({
  page,
  ontologyHubRuntime,
  captureStep,
  attachJson,
}) => {
  await runTermsFacetCase(
    page,
    ontologyHubRuntime,
    /property/i,
    captureStep,
    attachJson,
    "27-terms-property-filter",
  );
});
