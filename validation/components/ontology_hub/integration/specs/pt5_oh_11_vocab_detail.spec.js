const { test } = require("../../ui/fixtures");
const { OntologyHubVocabDetailPage } = require("../../ui/pages/vocab-detail.page");

test("PT5-OH-11: vocabulary detail displays metadata and descriptive sections", async ({
  page,
  ontologyHubRuntime,
  ontologyHubBootstrap,
  captureStep,
  attachJson,
}) => {
  const detailProbe = ontologyHubBootstrap.capabilities.detailProbe;
  test.skip(
    !detailProbe.available,
    detailProbe.reason || "La vista detalle de vocabularios no esta disponible.",
  );

  const detailPage = new OntologyHubVocabDetailPage(page);
  const targetPrefix = ontologyHubBootstrap.prefix || ontologyHubRuntime.expectedVocabularyPrefix;
  const targetTitle = ontologyHubBootstrap.title || ontologyHubRuntime.expectedVocabularyTitle;

  await detailPage.goto(ontologyHubRuntime.baseUrl, targetPrefix);
  await detailPage.expectReady(
    targetPrefix,
    targetTitle,
  );
  await detailPage.expectMetadataMarkers();
  await page.getByText("Tags", { exact: true }).waitFor({ state: "visible" });
  await captureStep(page, "01-vocab-detail-metadata");

  await attachJson("pt5-oh-11-report", {
    detailProbe,
    vocabularyPrefix: targetPrefix,
    vocabularyTitle: targetTitle,
    url: page.url(),
  });
});
