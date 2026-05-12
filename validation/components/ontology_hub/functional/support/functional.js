const { clickMarked } = require("../../ui/support/live-marker");
const { resolveOntologyHubTimeouts } = require("../../ui/runtime");

const { readyTimeoutMs, navigationTimeoutMs } = resolveOntologyHubTimeouts();

function normalizeText(value) {
  return String(value || "").trim();
}

async function readPrimaryHeading(page) {
  try {
    const heading = page.locator("h1").first();
    if ((await heading.count()) === 0) {
      return "";
    }
    return normalizeText(await heading.textContent());
  } catch (error) {
    return "";
  }
}

function resolveSearchQuery(runtime) {
  return (
    normalizeText(runtime.listingSearchTerm) ||
    normalizeText(runtime.expectedVocabularyPrefix) ||
    normalizeText(runtime.expectedSearchTerm) ||
    normalizeText(runtime.expectedLabel) ||
    "saref"
  );
}

function normalizeLanguageLabel(value) {
  return normalizeText(value)
    .replace(/\(\d+\)\s*$/, "")
    .toLowerCase();
}

function expectedLanguageCandidates(languageCode) {
  const normalized = normalizeText(languageCode).toLowerCase();
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

function pickLanguageLabel(labels, preferredCode) {
  const normalizedLabels = labels.map((label) => ({
    raw: label,
    normalized: normalizeLanguageLabel(label),
  }));
  const expected = normalizedLabels.find(({ normalized }) =>
    expectedLanguageCandidates(preferredCode).some(
      (candidate) => normalized === candidate || normalized.startsWith(`${candidate} `),
    ),
  );
  if (expected) {
    return expected.raw;
  }
  return normalizedLabels[0]?.raw || "";
}

async function waitForCatalogReady(page, timeoutMs = readyTimeoutMs) {
  try {
    await page.locator("#searchInput").waitFor({ state: "visible", timeout: timeoutMs });
  } catch (error) {
    const heading = await readPrimaryHeading(page);
    if (/404|500|oops!/i.test(heading)) {
      throw new Error(`Catalog page failed to load: ${heading}`);
    }
    throw new Error(`Catalog page not ready after ${timeoutMs}ms. Missing selector: #searchInput`);
  }
}

async function waitForTermsReady(page, timeoutMs = readyTimeoutMs) {
  try {
    await page.locator("#searchInput").waitFor({ state: "visible", timeout: timeoutMs });
  } catch (error) {
    const heading = await readPrimaryHeading(page);
    if (/404|500|oops!/i.test(heading)) {
      throw new Error(`Terms page failed to load: ${heading}`);
    }
    throw new Error(`Terms page not ready after ${timeoutMs}ms. Missing selector: #searchInput`);
  }
}

async function waitForSelectorAny(page, selectors, timeoutMs, label) {
  try {
    await page.waitForFunction(
      (selectorList) => selectorList.some((selector) => document.querySelector(selector)),
      selectors,
      { timeout: timeoutMs },
    );
  } catch (error) {
    throw new Error(
      `${label} layout not ready after ${timeoutMs}ms. Selectors: ${selectors.join(", ")}`,
    );
  }
}

async function waitForCatalogResults(page, timeoutMs = readyTimeoutMs) {
  await waitForSelectorAny(
    page,
    [".count-items .count", "#SearchGrid li"],
    timeoutMs,
    "Catalog",
  );
}

async function waitForTermsResults(page, timeoutMs = readyTimeoutMs) {
  await waitForSelectorAny(
    page,
    [
      ".count-items .count",
      "#SearchGrid li",
      "#SearchGrid .prefixedName a",
      "section#posts a[href*='/dataset/terms/']",
    ],
    timeoutMs,
    "Terms",
  );
}

async function openFirstCatalogResult(page) {
  const prefixLink = page.locator("#SearchGrid .prefix a").first();
  if ((await prefixLink.count()) > 0) {
    const label = normalizeText(await prefixLink.textContent());
    await clickMarked(prefixLink);
    await page.waitForLoadState("domcontentloaded", { timeout: navigationTimeoutMs });
    return { label, source: "prefix-link" };
  }

  const fallback = page.locator("#SearchGrid a").first();
  if ((await fallback.count()) > 0) {
    const label = normalizeText(await fallback.textContent());
    await clickMarked(fallback);
    await page.waitForLoadState("domcontentloaded", { timeout: navigationTimeoutMs });
    return { label, source: "first-link" };
  }

  return { label: "", source: "none" };
}

async function safeWaitForSuggestions(catalogPage, timeout = 2500) {
  try {
    await catalogPage.suggestionItems().first().waitFor({ state: "visible", timeout });
    return true;
  } catch (error) {
    return false;
  }
}

module.exports = {
  normalizeText,
  resolveSearchQuery,
  normalizeLanguageLabel,
  expectedLanguageCandidates,
  pickLanguageLabel,
  waitForCatalogReady,
  waitForCatalogResults,
  waitForTermsReady,
  waitForTermsResults,
  openFirstCatalogResult,
  safeWaitForSuggestions,
};
