// Excel traceability: Ontology Hub cases 3 and 4, partial coverage from the configured source.
const { test } = require("../../ui/fixtures");
const { OntologyHubVocabCatalogPage } = require("../../ui/pages/vocab-catalog.page");
const { OntologyHubVocabDetailPage } = require("../../ui/pages/vocab-detail.page");

async function waitForCatalogPublication(page, baseUrl, prefix, timeoutMs = 90000) {
  const catalogPage = new OntologyHubVocabCatalogPage(page);
  const startedAt = Date.now();
  let lastCount = 0;

  while (Date.now() - startedAt < timeoutMs) {
    await catalogPage.goto(baseUrl, prefix);
    await catalogPage.expectReady();

    const matches = await page
      .locator("#SearchGrid .prefix a, #SearchGrid li, ul.ui-autocomplete li")
      .filter({ hasText: prefix })
      .count()
      .catch(() => 0);
    lastCount = matches;

    if (matches > 0) {
      return catalogPage;
    }

    await page.waitForTimeout(2000);
  }

  throw new Error(
    `El vocabulario '${prefix}' no aparecio publicado en el catalogo tras ${timeoutMs}ms. ` +
      `Ultimo numero de coincidencias detectadas: ${lastCount}.`,
  );
}

test("PT5-OH-01: vocabulary can be registered from the configured source and become visible in the catalog", async ({
  page,
  ontologyHubRuntime,
  ontologyHubBootstrap,
  captureStep,
  attachJson,
}) => {
  test.skip(
    ontologyHubBootstrap.source !== "created" &&
      !ontologyHubBootstrap.creationOutcome?.reusedExistingImport &&
      !ontologyHubBootstrap.managedVocabulary,
    "PT5-OH-01 requiere un vocabulario nuevo creado por el bootstrap, uno importado por ese mismo flujo o un vocabulario temporal gestionado por el framework. El entorno actual reutilizo un vocabulario no apto para esta validacion.",
  );

  if (ontologyHubBootstrap.creationOutcome?.recoveredAfterSaveError) {
    throw new Error(
      "Ontology Hub devolvio un error durante el guardado del registro. " +
        "El test ya no considera valido recuperar el vocabulario despues de un save fallido.",
    );
  }

  const detailPage = new OntologyHubVocabDetailPage(page);
  const catalogPage = await waitForCatalogPublication(
    page,
    ontologyHubRuntime.baseUrl,
    ontologyHubBootstrap.prefix,
  );

  await captureStep(page, "01-created-vocabulary-in-catalog");
  await catalogPage.openResult(ontologyHubBootstrap.prefix);
  await detailPage.expectReady(ontologyHubBootstrap.prefix, ontologyHubBootstrap.title);
  await captureStep(page, "01-created-vocabulary-public-detail");

  await attachJson("pt5-oh-01-report", {
    creationMethod: ontologyHubBootstrap.creationMethod,
    creationUri: ontologyHubBootstrap.creationUri,
    creationRepositoryUri: ontologyHubBootstrap.creationRepositoryUri,
    creationPrefix: ontologyHubBootstrap.prefix,
    creationNamespace: ontologyHubBootstrap.creationNamespace,
    source: ontologyHubBootstrap.source,
    managedVocabulary: Boolean(ontologyHubBootstrap.managedVocabulary),
    creationOutcome: ontologyHubBootstrap.creationOutcome,
    capabilities: ontologyHubBootstrap.capabilities,
    finalUrl: page.url(),
    publicationVerification: "catalog-search",
  });
});
