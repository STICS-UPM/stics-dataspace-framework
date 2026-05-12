// Excel traceability: Ontology Hub case 25 (Buscador de Terminos).
const { test } = require("../../ui/fixtures");
const { OntologyHubTermsPage } = require("../../ui/pages/terms.page");
const { probeTermSearchApi } = require("../../ui/support/capabilities");
const { waitForTermsReady, waitForTermsResults } = require("../support/functional");
const {
  loadRunState,
  runtimeFromCreatedVocabulary,
  signInToEdition,
  signOut,
  URI_VOCAB_STATE_KEY,
} = require("../support/excel-flows");

test("OH-APP-25: terms search returns results for the ontology created in OH-APP-03", async ({
  page,
  ontologyHubRuntime,
  captureStep,
  attachJson,
}) => {
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
  await waitForTermsReady(page);
  await waitForTermsResults(page);
  const resultCount = await termsPage.currentResultCount().catch(() => null);
  if (termProbe.label) {
    await termsPage.expectResultVisible(termProbe.label);
  }

  await captureStep(page, "01-terms-search");
  await signOut(page, flowRuntime);

  await attachJson("25-terms-search-report", {
    vocabulary: created,
    query,
    termProbe,
    resultCount,
    url: page.url(),
  });
});
