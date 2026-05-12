// Excel traceability: Ontology Hub cases 6, 7, 8 and 9.
const { test } = require("../../ui/fixtures");
const { OntologyHubVocabCatalogPage } = require("../../ui/pages/vocab-catalog.page");
const {
  pickLanguageLabel,
  waitForCatalogReady,
  waitForCatalogResults,
} = require("../support/functional");
const {
  loadRunState,
  runtimeFromCreatedVocabulary,
  signInToEdition,
  signOut,
  REPOSITORY_VOCAB_STATE_KEY,
  URI_VOCAB_STATE_KEY,
} = require("../support/excel-flows");

function escapeRegExp(value) {
  return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function normalizeFacetPattern(value) {
  if (value instanceof RegExp) {
    return value;
  }
  return new RegExp(`^\\s*${escapeRegExp(String(value || ""))}(?:\\s*\\(\\d+\\))?\\s*$`, "i");
}

async function collectVocabularyMetadataEvidence(page, runtime, vocabulary) {
  const prefix = String((vocabulary && vocabulary.prefix) || "").trim();
  if (!prefix) {
    return {
      available: false,
      reason: "Vocabulary prefix is empty.",
    };
  }

  const evidence = {
    available: true,
    prefix,
    catalogLabel: String((vocabulary && vocabulary.catalogLabel) || ""),
    edit: null,
    publicDetail: null,
  };

  try {
    await page.goto(`${runtime.baseUrl}/edition/vocabs/${encodeURIComponent(prefix)}`, {
      waitUntil: "domcontentloaded",
    });
    evidence.edit = {
      titleLanguages: await page
        .locator("select[name^='titles']")
        .evaluateAll((nodes) => nodes.map((node) => String(node.value || "").trim()).filter(Boolean))
        .catch(() => []),
      descriptionLanguages: await page
        .locator("select[name^='descriptions']")
        .evaluateAll((nodes) => nodes.map((node) => String(node.value || "").trim()).filter(Boolean))
        .catch(() => []),
      tags: await page
        .locator("#tagsUl input[name='tags[]']")
        .evaluateAll((nodes) => nodes.map((node) => String(node.value || "").trim()).filter(Boolean))
        .catch(() => []),
      review: await page.locator("textarea[name^='reviews']").first().inputValue().catch(() => ""),
    };
  } catch (error) {
    evidence.edit = {
      error: String((error && error.message) || error || ""),
    };
  }

  try {
    await page.goto(`${runtime.baseUrl}/dataset/vocabs/${encodeURIComponent(prefix)}`, {
      waitUntil: "domcontentloaded",
    });
    const bodyText = await page
      .locator("body")
      .evaluate((node) => (node.textContent || "").replace(/\s+/g, " ").trim())
      .catch(() => "");
    evidence.publicDetail = {
      heading: await page.locator("h1").first().textContent().catch(() => ""),
      hasServices: /Services/i.test(bodyText),
      hasEnglish: /English/i.test(bodyText),
      hasSpanish: /Spanish/i.test(bodyText),
      bodySnippet: bodyText.slice(0, 500),
    };
  } catch (error) {
    evidence.publicDetail = {
      error: String((error && error.message) || error || ""),
    };
  }

  return evidence;
}

async function waitForFacetLink(page, catalogPage, baseUrl, query, groupLabel, valueLabel, options = {}) {
  const deadline = Date.now() + (options.timeoutMs || 15000);
  const exactPattern = normalizeFacetPattern(valueLabel);
  let availableLabels = [];

  while (Date.now() < deadline) {
    const directFacetLink = catalogPage.facetLink(groupLabel, exactPattern);
    if ((await directFacetLink.count()) > 0) {
      return {
        facetLink: directFacetLink,
        availableLabels,
        matchedLabel: null,
      };
    }

    availableLabels = await catalogPage.facetLabels(groupLabel).catch(() => []);
    if (/language/i.test(String(groupLabel)) && availableLabels.length > 0) {
      const matchedLanguageLabel = pickLanguageLabel(availableLabels, "en");
      if (matchedLanguageLabel && !/^n\/a(?:\s*\(\d+\))?$/i.test(matchedLanguageLabel)) {
        const languageFacetLink = catalogPage.facetLink(
          groupLabel,
          normalizeFacetPattern(matchedLanguageLabel),
        );
        if ((await languageFacetLink.count()) > 0) {
          return {
            facetLink: languageFacetLink,
            availableLabels,
            matchedLabel: matchedLanguageLabel,
          };
        }
      }
    }

    if (Date.now() >= deadline) {
      break;
    }

    await page.waitForTimeout(5000);
    await catalogPage.goto(baseUrl, query);
    await waitForCatalogReady(page, 5000);
    await waitForCatalogResults(page, 5000);
  }

  throw new Error(
    `Facet '${groupLabel}' with value '${valueLabel}' is not available in this deployment. ` +
      `Available values: ${availableLabels.length > 0 ? availableLabels.join(", ") : "none"}.`,
  );
}

async function applyFacetLink(page, catalogPage, baseUrl, query, groupLabel, valueLabel) {
  const { facetLink, matchedLabel, availableLabels } = await waitForFacetLink(
    page,
    catalogPage,
    baseUrl,
    query,
    groupLabel,
    valueLabel,
  );
  const href = await catalogPage.facetHref(facetLink);
  if (!href) {
    throw new Error(
      `Facet '${groupLabel}' with value '${matchedLabel || valueLabel}' does not expose a navigable link. ` +
        `Available values: ${availableLabels.length > 0 ? availableLabels.join(", ") : "none"}.`,
    );
  }

  const url = new URL(href, page.url()).toString();
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await waitForCatalogReady(page, 5000);
  await waitForCatalogResults(page, 5000);
  const count = await catalogPage.currentResultCount().catch(() => null);
  if (!count || count <= 0) {
    throw new Error(`Facet '${groupLabel}' with value '${valueLabel}' returned no catalog results.`);
  }
  return { applied: true, url, count };
}

async function runFacetCase(page, ontologyHubRuntime, facetGroup, facetValue, captureStep, attachJson, reportName) {
  const uriVocabulary = loadRunState(URI_VOCAB_STATE_KEY);
  const repositoryVocabulary = loadRunState(REPOSITORY_VOCAB_STATE_KEY);
  const flowRuntime = runtimeFromCreatedVocabulary(ontologyHubRuntime, uriVocabulary, {
    listingSearchTerm: "",
  });

  await signInToEdition(page, flowRuntime);
  const catalogPage = new OntologyHubVocabCatalogPage(page);
  const query = "";

  await catalogPage.goto(flowRuntime.baseUrl, query);
  await waitForCatalogReady(page, 5000);
  await waitForCatalogResults(page, 5000);

  let outcome;
  try {
    outcome = await applyFacetLink(
      page,
      catalogPage,
      flowRuntime.baseUrl,
      query,
      facetGroup,
      facetValue,
    );
  } catch (error) {
    const diagnostic = {
      query,
      facetGroup: String(facetGroup),
      facetValue: String(facetValue),
      availableTagLabels: await catalogPage.facetLabels(/Tag/i).catch(() => []),
      availableLanguageLabels: await catalogPage.facetLabels(/Language/i).catch(() => []),
      uriVocabulary: await collectVocabularyMetadataEvidence(page, flowRuntime, uriVocabulary).catch(
        (diagnosticError) => ({
          available: false,
          reason: String((diagnosticError && diagnosticError.message) || diagnosticError || ""),
        }),
      ),
      repositoryVocabulary: await collectVocabularyMetadataEvidence(
        page,
        flowRuntime,
        repositoryVocabulary,
      ).catch((diagnosticError) => ({
        available: false,
        reason: String((diagnosticError && diagnosticError.message) || diagnosticError || ""),
      })),
    };
    await attachJson(`${reportName}-diagnostic`, diagnostic);
    throw new Error(
      `${error.message} ` +
        `URI metadata tags: ${(diagnostic.uriVocabulary.edit && diagnostic.uriVocabulary.edit.tags || []).join(", ") || "none"}. ` +
        `URI title languages: ${(diagnostic.uriVocabulary.edit && diagnostic.uriVocabulary.edit.titleLanguages || []).join(", ") || "none"}. ` +
        `Catalog Tag facet values: ${diagnostic.availableTagLabels.join(", ") || "none"}. ` +
        `Catalog Language facet values: ${diagnostic.availableLanguageLabels.join(", ") || "none"}.`,
    );
  }
  if (/tag|language/i.test(String(facetGroup))) {
    const expectedLabel = uriVocabulary.catalogLabel || repositoryVocabulary.catalogLabel || uriVocabulary.title;
    await catalogPage.expectResultVisible(expectedLabel);
  }
  await captureStep(page, reportName);
  await signOut(page, flowRuntime);

  await attachJson(`${reportName}-report`, {
    query,
    facetGroup: String(facetGroup),
    facetValue: String(facetValue),
    outcome,
    uriVocabulary,
    repositoryVocabulary,
  });
}

test("OH-APP-06: vocabulary catalog filters by class", async ({
  page,
  ontologyHubRuntime,
  captureStep,
  attachJson,
}) => {
  await runFacetCase(page, ontologyHubRuntime, /Type/i, /class/i, captureStep, attachJson, "06-class-filter");
});

test("OH-APP-07: vocabulary catalog filters by property", async ({
  page,
  ontologyHubRuntime,
  captureStep,
  attachJson,
}) => {
  await runFacetCase(
    page,
    ontologyHubRuntime,
    /Type/i,
    /property/i,
    captureStep,
    attachJson,
    "07-property-filter",
  );
});

test("OH-APP-08: vocabulary catalog filters by tag Services", async ({
  page,
  ontologyHubRuntime,
  captureStep,
  attachJson,
}) => {
  await runFacetCase(
    page,
    ontologyHubRuntime,
    /Tag/i,
    new RegExp(`^\\s*${escapeRegExp("Services")}(?:\\s*\\(\\d+\\))?\\s*$`, "i"),
    captureStep,
    attachJson,
    "08-tag-filter",
  );
});

test("OH-APP-09: vocabulary catalog filters by language English", async ({
  page,
  ontologyHubRuntime,
  captureStep,
  attachJson,
}) => {
  await runFacetCase(
    page,
    ontologyHubRuntime,
    /Language/i,
    new RegExp(`^\\s*${escapeRegExp("English")}(?:\\s*\\(\\d+\\))?\\s*$`, "i"),
    captureStep,
    attachJson,
    "09-language-filter",
  );
});
