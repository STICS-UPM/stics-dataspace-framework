// Excel traceability: Ontology Hub cases 3 and 4.
const { test } = require("../../ui/fixtures");
const { OntologyHubVocabCatalogPage } = require("../../ui/pages/vocab-catalog.page");
const {
  DEFAULT_REPOSITORY_URI,
  buildExcelRepositoryVocabularyRuntime,
  buildExcelUriVocabularyRuntime,
  createVocabularyByUri,
  createVocabularyFromRepository,
  deleteRunState,
  REPOSITORY_VOCAB_STATE_KEY,
  reopenVocabularyEditionAndSave,
  runIndexAllFromEdition,
  saveRunState,
  signOut,
  URI_VOCAB_STATE_KEY,
  VERSION_STATE_KEY,
} = require("../support/excel-flows");

async function expectVocabularyVisibleInCatalog(page, runtime, created) {
  const catalogPage = new OntologyHubVocabCatalogPage(page);
  const query = created.catalogLabel || created.title || created.prefix;
  await catalogPage.goto(runtime.baseUrl, query);
  await catalogPage.expectReady();
  await catalogPage.waitForResults();
  await catalogPage.expectResultVisible(query);
}

test("OH-APP-03: register ontology by URI", async ({
  page,
  ontologyHubRuntime,
  captureStep,
  attachJson,
}) => {
  const runtime = buildExcelUriVocabularyRuntime(ontologyHubRuntime);

  const created = {
    ...(await createVocabularyByUri(page, runtime)),
    catalogLabel: runtime.creationTitle,
    creationTag: runtime.creationTag,
    creationReview: runtime.creationReview,
  };
  await runIndexAllFromEdition(page, runtime);
  await reopenVocabularyEditionAndSave(page, runtime, created.prefix, {
    title: runtime.creationTitle,
    description: runtime.creationDescription,
  });
  await runIndexAllFromEdition(page, runtime);
  await captureStep(page, "03-uri-detail");

  await expectVocabularyVisibleInCatalog(page, runtime, created);
  await captureStep(page, "03-uri-catalog");
  await signOut(page, runtime);
  saveRunState(URI_VOCAB_STATE_KEY, created);

  await attachJson("03-uri-registration-report", created);
});

test("OH-APP-04: register ontology from repository", async ({
  page,
  ontologyHubRuntime,
  captureStep,
  attachJson,
}) => {
  const runtime = buildExcelRepositoryVocabularyRuntime(ontologyHubRuntime, {
    creationRepositoryUri: normalizeRepo(ontologyHubRuntime.creationRepositoryUri || DEFAULT_REPOSITORY_URI),
  });

  const created = {
    ...(await createVocabularyFromRepository(page, runtime)),
    catalogLabel: runtime.creationTitle,
    creationTag: runtime.creationTag,
    creationReview: runtime.creationReview,
  };
  await runIndexAllFromEdition(page, runtime);
  await reopenVocabularyEditionAndSave(page, runtime, created.prefix);
  await runIndexAllFromEdition(page, runtime);
  await captureStep(page, "04-repository-detail");

  await expectVocabularyVisibleInCatalog(page, runtime, created);
  await captureStep(page, "04-repository-catalog");
  await signOut(page, runtime);
  deleteRunState(VERSION_STATE_KEY);
  saveRunState(REPOSITORY_VOCAB_STATE_KEY, created);

  await attachJson("04-repository-registration-report", created);
});

function normalizeRepo(value) {
  const normalized = String(value || "").trim();
  return normalized || DEFAULT_REPOSITORY_URI;
}
