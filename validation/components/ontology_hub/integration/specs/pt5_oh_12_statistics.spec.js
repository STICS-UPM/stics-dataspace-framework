const { test } = require("../../ui/fixtures");
const { OntologyHubVocabDetailPage } = require("../../ui/pages/vocab-detail.page");

test("PT5-OH-12: vocabulary detail exposes statistics and LOD usage markers", async ({
  page,
  ontologyHubRuntime,
  ontologyHubBootstrap,
  captureStep,
  attachJson,
}) => {
  const detailProbe = ontologyHubBootstrap.capabilities.detailProbe;
  test.skip(
    !detailProbe.available || !detailProbe.statistics,
    detailProbe.reason || "La vista detalle no expone estadisticas reutilizables.",
  );

  const detailPage = new OntologyHubVocabDetailPage(page);
  const targetPrefix = ontologyHubBootstrap.prefix || ontologyHubRuntime.expectedVocabularyPrefix;
  const targetTitle = ontologyHubBootstrap.title || ontologyHubRuntime.expectedVocabularyTitle;

  await detailPage.goto(ontologyHubRuntime.baseUrl, targetPrefix);
  await detailPage.expectReady(
    targetPrefix,
    targetTitle,
  );
  await detailPage.expectStatisticsMarkers();
  await page.getByText("Vocabulary used in", { exact: false }).waitFor({ state: "visible" });
  await captureStep(page, "01-vocab-detail-statistics");

  await attachJson("pt5-oh-12-report", {
    detailProbe,
    vocabularyPrefix: targetPrefix,
    chartSelector: "#chartElements",
    lodSectionVisible: true,
    url: page.url(),
  });
});
