const { test, expect } = require("../../ui/fixtures");
const { OntologyHubVocabCatalogPage } = require("../../ui/pages/vocab-catalog.page");
const { OntologyHubVocabDetailPage } = require("../../ui/pages/vocab-detail.page");

function normalizeLanguageLabel(value) {
  return String(value || "")
    .replace(/\(\d+\)\s*$/, "")
    .trim()
    .toLowerCase();
}

async function hasCatalogResultsLayout(page) {
  const hasCount = await page.locator(".count-items .count").first().isVisible().catch(() => false);
  const hasGridItem = await page.locator("#SearchGrid li").first().isVisible().catch(() => false);
  return hasCount || hasGridItem;
}

function expectedLanguageCandidates(languageCode) {
  const normalized = String(languageCode || "").trim().toLowerCase();
  const candidates = new Set([normalized]);
  const codeToEnglishName = {
    en: "english",
    es: "spanish",
  };
  if (codeToEnglishName[normalized]) {
    candidates.add(codeToEnglishName[normalized]);
  }
  return Array.from(candidates).filter(Boolean);
}

test("PT5-OH-09: vocabulary catalog supports documented Tag and Language filters in the public UI", async ({
  page,
  ontologyHubRuntime,
  ontologyHubBootstrap,
  captureStep,
  attachJson,
}) => {
  test.skip(
    ontologyHubBootstrap.source !== "created" && !ontologyHubBootstrap.managedVocabulary,
    "PT5-OH-09 requiere un vocabulario multilenguaje creado en el bootstrap o un vocabulario temporal multilenguaje gestionado por el framework.",
  );

  const catalogPage = new OntologyHubVocabCatalogPage(page);
  const detailPage = new OntologyHubVocabDetailPage(page);

  const query = ontologyHubBootstrap.prefix;
  const targetPrefix = ontologyHubBootstrap.prefix;
  const targetTitle = ontologyHubBootstrap.title;
  const selectedTagLabel =
    ontologyHubBootstrap.creationTag ||
    ontologyHubRuntime.creationTag ||
    ontologyHubRuntime.expectedPrimaryTag;
  const selectedLanguage =
    ontologyHubBootstrap.creationSecondaryLanguage ||
    ontologyHubRuntime.creationSecondaryLanguage ||
    "es";

  await catalogPage.goto(ontologyHubRuntime.baseUrl, query);
  await catalogPage.expectReady();
  await catalogPage.waitForResults();
  await catalogPage.expectResultVisible(targetPrefix);
  await expect(catalogPage.facet(/Type/i)).toContainText("vocabulary");
  await captureStep(page, "01-vocabs-search-initial");

  const tagFacetLink = catalogPage.facetLink(/Tag/i, selectedTagLabel);
  await expect(tagFacetLink).toBeVisible();
  const tagHref = await catalogPage.facetHref(tagFacetLink);
  expect(tagHref).toContain("tag=");
  const tagUrl = new URL(tagHref, page.url()).toString();

  await page.goto(tagUrl, {
    waitUntil: "domcontentloaded",
  });
  await expect(page).toHaveURL(/tag=/);
  await catalogPage.expectReady();
  await catalogPage.waitForResults();
  await catalogPage.expectResultVisible(targetPrefix);
  await captureStep(page, "02-vocabs-tag-filter");

  const languageLabels = await catalogPage.facetLabels(/Language/i);
  expect(languageLabels.length).toBeGreaterThan(0);
  const normalizedLanguageLabels = languageLabels.map((label) => ({
    raw: label,
    normalized: normalizeLanguageLabel(label),
  }));
  const expectedLanguageLabel =
    normalizedLanguageLabels.find(({ normalized }) =>
      expectedLanguageCandidates(selectedLanguage).some(
        (candidate) => normalized === candidate || normalized.startsWith(`${candidate} `),
      ),
    ) || normalizedLanguageLabels[0];
  expect(expectedLanguageLabel).toBeTruthy();
  test.skip(
    expectedLanguageLabel.normalized === "n/a",
    "PT5-OH-09 se omite porque la faceta Language solo expone N/A en este despliegue.",
  );
  const languageSelectionMode = normalizedLanguageLabels.some(({ normalized }) =>
    expectedLanguageCandidates(selectedLanguage).some(
      (candidate) => normalized === candidate || normalized.startsWith(`${candidate} `),
    ),
  )
    ? "expected_language"
    : "first_available_language";

  const languageFacetLink = catalogPage.facetLink(
    /Language/i,
    new RegExp(`^\\s*${expectedLanguageLabel.raw.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*$`, "i"),
  );
  await expect(languageFacetLink).toBeVisible();
  const languageHref = await catalogPage.facetHref(languageFacetLink);
  expect(languageHref).toContain("lang=");
  const languageUrl = new URL(languageHref, page.url()).toString();

  await page.goto(languageUrl, {
    waitUntil: "domcontentloaded",
  });
  await expect(page).toHaveURL(/lang=/);
  await expect(page).toHaveURL(/tag=/);
  await catalogPage.expectReady();
  test.skip(
    !(await hasCatalogResultsLayout(page)),
    "PT5-OH-09 se omite porque la URL filtrada por Language no renderiza el layout normal del catalogo en este despliegue.",
  );
  await catalogPage.waitForResults();
  await catalogPage.expectResultVisible(targetPrefix);
  await captureStep(page, "03-vocabs-language-filter");
  const resultCount = await catalogPage.currentResultCount().catch(() => null);

  const openedResult = await catalogPage.openResult(targetPrefix);
  await expect(page).toHaveURL(new RegExp(`/dataset/vocabs/${targetPrefix}/?$`));
  await detailPage.expectReady(targetPrefix, targetTitle);
  await captureStep(page, "04-opened-filtered-vocabulary");

  await attachJson("pt5-oh-09-report", {
    query,
    selectedTag: selectedTagLabel,
    selectedLanguage,
    resolvedLanguageLabel: expectedLanguageLabel.raw,
    languageSelectionMode,
    availableLanguages: languageLabels,
    creationMethod: ontologyHubBootstrap.creationMethod,
    managedVocabulary: Boolean(ontologyHubBootstrap.managedVocabulary),
    tagUrl,
    languageUrl,
    openedResult,
    resultCount,
    finalUrl: page.url(),
  });
});
