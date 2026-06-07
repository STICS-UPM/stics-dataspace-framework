const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const {
  gotoEdition,
  pageShowsTransientAvailabilityFailure,
} = require("../../ui/support/bootstrap");
const { resolveOntologyHubTimeouts } = require("../../ui/runtime");
const { OntologyHubVocabFormPage } = require("../../ui/pages/vocab-form.page");
const { OntologyHubVocabDetailPage } = require("../../ui/pages/vocab-detail.page");
const { probeVocabularyDetail } = require("../../ui/support/capabilities");
const {
  checkMarked,
  clickMarked,
  fillMarked,
  highlightMarked,
  selectOptionMarked,
  setInputFilesMarked,
} = require("../../ui/support/live-marker");

const DEFAULT_URI = "https://saref.etsi.org/saref4grid/v2.1.1/";
const DEFAULT_REPOSITORY_URI =
  "https://github.com/ProyectoPIONERA/Ontology-Development-Repository-Example";
const URI_VOCAB_STATE_KEY = "oh-app-03-uri-vocabulary";
const REPOSITORY_VOCAB_STATE_KEY = "oh-app-04-repository-vocabulary";
const VISUALIZATION_N3_STATE_KEY = "oh-app-05-visualization-n3";
const VERSION_VOCAB_STATE_KEY = "oh-app-11-version-vocabulary";
const VERSION_STATE_KEY = "oh-app-11-version-state";
const { readyTimeoutMs, navigationTimeoutMs } = resolveOntologyHubTimeouts();

function normalizeText(value) {
  return String(value || "").trim();
}

function runStateDir() {
  const runtimeFile = normalizeText(process.env.ONTOLOGY_HUB_RUNTIME_FILE);
  if (runtimeFile) {
    return path.resolve(process.cwd(), path.dirname(runtimeFile));
  }

  const explicitDir = normalizeText(
    process.env.ONTOLOGY_HUB_FUNCTIONAL_STATE_DIR ||
      process.env.ONTOLOGY_HUB_APP_FLOWS_STATE_DIR,
  );
  if (explicitDir) {
    return path.resolve(process.cwd(), explicitDir);
  }

  return path.resolve(__dirname, "../state");
}

function generatedArtifactsDir() {
  const explicitDir = normalizeText(
    process.env.ONTOLOGY_HUB_FUNCTIONAL_GENERATED_DIR ||
      process.env.ONTOLOGY_HUB_APP_FLOWS_GENERATED_DIR,
  );
  if (explicitDir) {
    return path.resolve(process.cwd(), explicitDir);
  }

  return path.resolve(__dirname, "../generated");
}

function runStatePath(key) {
  return path.join(runStateDir(), `${normalizeText(key)}.json`);
}

function persistGeneratedArtifact(sourcePath, targetName = "", subdir = "") {
  const source = path.resolve(sourcePath);
  if (!fs.existsSync(source)) {
    throw new Error(`Generated artifact source does not exist: ${source}`);
  }

  const directory = path.join(generatedArtifactsDir(), normalizeText(subdir));
  fs.mkdirSync(directory, { recursive: true });
  const fileName = normalizeText(targetName) || path.basename(source);
  const destination = path.join(directory, fileName);
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.copyFileSync(source, destination);
  return destination;
}

function saveRunState(key, payload) {
  const filePath = runStatePath(key);
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(payload, null, 2), "utf8");
  return filePath;
}

function loadRunState(key) {
  const filePath = runStatePath(key);
  if (!fs.existsSync(filePath)) {
    throw new Error(
      `Required Ontology Hub shared state is missing for '${key}'. Expected file: ${filePath}`,
    );
  }

  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function deleteRunState(key) {
  const filePath = runStatePath(key);
  if (fs.existsSync(filePath)) {
    fs.unlinkSync(filePath);
  }
}

async function safeTextContent(locator) {
  try {
    if ((await locator.count()) === 0) {
      return "";
    }
    return (await locator.first().textContent()) || "";
  } catch (error) {
    return "";
  }
}

function escapeRegExp(value) {
  return normalizeText(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function caseSlug(caseId) {
  return normalizeText(caseId)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function uniqueSuffix(testInfo) {
  const now = Date.now().toString(36);
  const retry = String(testInfo.retry || 0);
  const worker = String(testInfo.parallelIndex || 0);
  return `${now}-${worker}-${retry}`.slice(-18);
}

function buildVocabularyRuntime(runtime, caseId, testInfo, overrides = {}) {
  const suffix = uniqueSuffix(testInfo).replace(/[^a-z0-9-]/g, "");
  const prefix = normalizeText(
    overrides.creationPrefix || `oh-${caseSlug(caseId)}-${suffix}`.slice(0, 40),
  )
    .toLowerCase()
    .replace(/[^a-z0-9-]/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-+|-+$/g, "");

  return {
    ...runtime,
    ...overrides,
    creationUri: normalizeText(overrides.creationUri || runtime.creationUri || DEFAULT_URI),
    creationRepositoryUri: normalizeText(
      overrides.creationRepositoryUri || runtime.creationRepositoryUri || DEFAULT_REPOSITORY_URI,
    ),
    creationPrefix: prefix,
    expectedVocabularyPrefix: prefix,
    listingSearchTerm: prefix,
    creationTitle:
      normalizeText(overrides.creationTitle) || `Ontology Hub ${caseId} ${suffix}`.slice(0, 70),
    expectedVocabularyTitle:
      normalizeText(overrides.creationTitle) || `Ontology Hub ${caseId} ${suffix}`.slice(0, 70),
    creationDescription:
      normalizeText(overrides.creationDescription) ||
      `Vocabulary created for automated Excel case ${caseId}.`,
    creationTag: normalizeText(overrides.creationTag || "Services"),
    creationReview:
      normalizeText(overrides.creationReview) ||
      `Automated validation evidence for Excel case ${caseId}.`,
  };
}

function buildExcelUriVocabularyRuntime(runtime, overrides = {}) {
  return {
    ...runtime,
    ...overrides,
    creationUri: normalizeText(overrides.creationUri || runtime.creationUri || DEFAULT_URI),
    creationNamespace: normalizeText(
      overrides.creationNamespace || runtime.creationNamespace || "https://saref.etsi.org/saref4grid/",
    ),
    creationPrefix: normalizeText(overrides.creationPrefix || "saref4grid"),
    expectedVocabularyPrefix: normalizeText(overrides.expectedVocabularyPrefix || "saref4grid"),
    listingSearchTerm: normalizeText(overrides.listingSearchTerm || "saref4grid"),
    creationTitle: normalizeText(overrides.creationTitle || "saref4grid"),
    expectedVocabularyTitle: normalizeText(overrides.expectedVocabularyTitle || "saref4grid"),
    creationDescription:
      normalizeText(overrides.creationDescription) ||
      "Ontology registered from the ETSI SAREF4GRID URI for Excel validation.",
    creationTag: normalizeText(overrides.creationTag || "Services"),
    creationReview: normalizeText(overrides.creationReview || "Admin"),
    expectedPrimaryTag: normalizeText(overrides.expectedPrimaryTag || "Services"),
  };
}

function buildExcelRepositoryVocabularyRuntime(runtime, overrides = {}) {
  return {
    ...runtime,
    ...overrides,
    creationRepositoryUri: normalizeText(
      overrides.creationRepositoryUri || runtime.creationRepositoryUri || DEFAULT_REPOSITORY_URI,
    ),
    creationPrefix: normalizeText(overrides.creationPrefix || "ontology-development-repository-example"),
    expectedVocabularyPrefix: normalizeText(
      overrides.expectedVocabularyPrefix || "ontology-development-repository-example",
    ),
    listingSearchTerm: normalizeText(
      overrides.listingSearchTerm || "Ontology-Development-Repository-Example",
    ),
    creationTitle: normalizeText(overrides.creationTitle || "Ontology-Development-Repository-Example"),
    expectedVocabularyTitle: normalizeText(
      overrides.expectedVocabularyTitle || "Ontology-Development-Repository-Example",
    ),
    creationDescription:
      normalizeText(overrides.creationDescription) ||
      "Ontology registered from the public repository for Excel validation.",
    creationTag: normalizeText(overrides.creationTag || "Services"),
    creationReview: normalizeText(overrides.creationReview || "Admin"),
    expectedPrimaryTag: normalizeText(overrides.expectedPrimaryTag || "Services"),
  };
}

function runtimeFromCreatedVocabulary(runtime, created = {}, overrides = {}) {
  const prefix = normalizeText(overrides.expectedVocabularyPrefix || created.prefix || runtime.expectedVocabularyPrefix);
  const title = normalizeText(overrides.expectedVocabularyTitle || created.title || runtime.expectedVocabularyTitle);
  return {
    ...runtime,
    ...created,
    ...overrides,
    expectedVocabularyPrefix: prefix,
    expectedVocabularyTitle: title,
    listingSearchTerm: normalizeText(overrides.listingSearchTerm || created.catalogLabel || title || prefix),
    expectedPrimaryTag: normalizeText(overrides.expectedPrimaryTag || created.creationTag || created.tag || runtime.expectedPrimaryTag || "Services"),
  };
}

async function expectHealthyPage(page, label) {
  const heading = normalizeText(await safeTextContent(page.locator("h1").first()));
  if (/404|500|oops!/i.test(heading)) {
    throw new Error(`${label} page failed to load: ${heading}`);
  }
}

async function waitForEditionShellOrTransientFailure(page) {
  const editionShell = page.locator(
    ".createVocab, a[href='/edition/logout'], a[href='/edition/'], a[href^='/edition/users/']",
  );
  const deadline = Date.now() + readyTimeoutMs;

  while (Date.now() < deadline) {
    if (await editionShell.first().isVisible().catch(() => false)) {
      return true;
    }
    if (await pageShowsTransientAvailabilityFailure(page)) {
      return false;
    }
    await page.waitForTimeout(500);
  }

  await editionShell.first().waitFor({ state: "visible", timeout: 1000 });
  return true;
}

async function signInToEdition(page, runtime, credentials = {}) {
  const email = normalizeText(credentials.email || runtime.adminEmail);
  const password = normalizeText(credentials.password || runtime.adminPassword);
  let lastError = null;
  let attempt = 0;
  const recoveryTimeoutMs = Number.parseInt(credentials.recoveryTimeoutMs || "0", 10);
  const deadline = Date.now() + Math.max(
    readyTimeoutMs * 3,
    90000,
    Number.isFinite(recoveryTimeoutMs) ? recoveryTimeoutMs : 0,
  );

  while (Date.now() < deadline) {
    attempt += 1;
    try {
      await page.goto(`${runtime.baseUrl}/edition`, {
        waitUntil: "commit",
        timeout: navigationTimeoutMs,
      });
      await page.waitForLoadState("domcontentloaded", { timeout: navigationTimeoutMs }).catch(() => {});
      if (/\/edition\/login\/?$/i.test(page.url())) {
        await fillMarked(page.getByPlaceholder("Email"), email);
        await fillMarked(page.getByPlaceholder("Password"), password);
        const sessionResponse = page.waitForResponse(
          (response) => {
            const request = response.request();
            try {
              return request.method() === "POST" && new URL(response.url()).pathname.endsWith("/edition/session");
            } catch {
              return false;
            }
          },
          { timeout: navigationTimeoutMs },
        );
        const submitButton = page.getByRole("button", { name: /log in it!?/i });
        await highlightMarked(submitButton);
        await submitButton.evaluate((button) => button.click());
        const response = await sessionResponse;
        if (![200, 302, 303].includes(response.status())) {
          throw new Error(`Ontology Hub login returned HTTP ${response.status()} for '${email}'.`);
        }
        await page.goto(`${runtime.baseUrl}/edition`, {
          waitUntil: "commit",
          timeout: navigationTimeoutMs,
        });
        await page.waitForLoadState("domcontentloaded", { timeout: navigationTimeoutMs }).catch(() => {});
      }

      const invalidCredentials = normalizeText(await safeTextContent(page.locator("#formErrors")));
      if (/invalid email or password/i.test(invalidCredentials)) {
        throw new Error(`Ontology Hub rejected the credentials for '${email}'.`);
      }

      const editionReady = await waitForEditionShellOrTransientFailure(page);
      if (!editionReady) {
        throw new Error(`Ontology Hub edition is temporarily unavailable for '${email}'.`);
      }

      return page.url();
    } catch (error) {
      lastError = error;
      const errorLooksTransient = /temporarily unavailable|service temporarily unavailable|bad gateway|\b50[23]\b/i.test(
        String(error?.message || ""),
      );
      const pageLooksTransient = await pageShowsTransientAvailabilityFailure(page);
      if ((!pageLooksTransient && !errorLooksTransient) || Date.now() >= deadline) {
        throw error;
      }
      await page.waitForTimeout(5000);
    }
  }

  throw lastError || new Error(`Ontology Hub edition login did not stabilize for '${email}'.`);
}

function isEditionPath(url, suffix) {
  try {
    const pathname = new URL(String(url)).pathname.replace(/\/+$/, "");
    return pathname === suffix || pathname.endsWith(suffix);
  } catch {
    return false;
  }
}

async function waitForEditionLogin(page, runtime) {
  if (isEditionPath(page.url(), "/edition/login")) {
    await page.waitForLoadState("domcontentloaded", { timeout: navigationTimeoutMs }).catch(() => {});
    return;
  }

  await page
    .waitForURL((url) => isEditionPath(url, "/edition/login"), {
      waitUntil: "domcontentloaded",
      timeout: 5000,
    })
    .catch(async () => {
      try {
        await page.goto(`${runtime.baseUrl}/edition/login`, {
          waitUntil: "domcontentloaded",
          timeout: navigationTimeoutMs,
        });
      } catch (error) {
        if (!isEditionPath(page.url(), "/edition/login")) {
          throw error;
        }
      }
    });
}

async function signOut(page, runtime) {
  const logoutLink = page.getByRole("link", { name: /logout/i }).first();
  if ((await logoutLink.count()) > 0 && (await logoutLink.isVisible().catch(() => false))) {
    const logoutResponse = page.waitForResponse(
      (response) => {
        const request = response.request();
        try {
          return request.method() === "GET" && isEditionPath(response.url(), "/edition/logout");
        } catch {
          return false;
        }
      },
      { timeout: navigationTimeoutMs },
    ).catch(() => null);
    await highlightMarked(logoutLink);
    await logoutLink.evaluate((link) => link.click());
    await logoutResponse;
    await waitForEditionLogin(page, runtime);
    return;
  }

  try {
    await page.goto(`${runtime.baseUrl}/edition/logout`, { waitUntil: "domcontentloaded" });
  } catch (error) {
    if (!isEditionPath(page.url(), "/edition/login")) {
      throw error;
    }
  }
  await waitForEditionLogin(page, runtime);
}

async function ensureTagSelected(page, tagLabel) {
  const normalized = normalizeText(tagLabel);
  if (!normalized) {
    return;
  }

  const currentTags = await page
    .locator("#tagsUl input[name='tags[]']")
    .evaluateAll((nodes) => nodes.map((node) => String(node.value || "").trim()))
    .catch(() => []);
  if (currentTags.some((value) => value.toLowerCase() === normalized.toLowerCase())) {
    return;
  }

  await clickMarked(page.locator(".fieldTagsAddAction"));
  await page.locator("#listOfTags").waitFor({ state: "visible", timeout: readyTimeoutMs });

  const tagPattern = new RegExp(`^\\s*${escapeRegExp(normalized)}\\s*$`, "i");
  let tagOption = page.locator("#tagsPickerList .tagFromList").filter({ hasText: tagPattern }).first();

  if ((await tagOption.count()) === 0) {
    await clickMarked(page.locator("#toggleCreateTag"));
    await fillMarked(page.locator("#newTagLabel"), normalized);
    await clickMarked(page.locator("#btnCreateTag"));
    tagOption = page.locator("#tagsPickerList .tagFromList").filter({ hasText: tagPattern }).first();
    await tagOption.waitFor({ state: "visible", timeout: readyTimeoutMs });
  }

  const alreadyInForm = await page.evaluate(
    (expectedTag) =>
      Array.from(document.querySelectorAll('#tagsUl input[name="tags[]"]')).some(
        (node) => String(node.value || "").trim().toLowerCase() === expectedTag.toLowerCase(),
      ),
    normalized,
  );
  if (!alreadyInForm) {
    await clickMarked(tagOption);
  }

  await page.keyboard.press("Escape").catch(() => {});
  await page.locator("#listOfTags").waitFor({ state: "hidden", timeout: 5000 }).catch(() => {});

  const inFormAfterClose = await page.evaluate(
    (expectedTag) =>
      Array.from(document.querySelectorAll('#tagsUl input[name="tags[]"]')).some(
        (node) => String(node.value || "").trim().toLowerCase() === expectedTag.toLowerCase(),
      ),
    normalized,
  );
  if (!inFormAfterClose) {
    await page.evaluate(
      (tagName) => {
        if (typeof window.addTag === "function") {
          window.addTag(tagName);
        }
      },
      normalized,
    );
  }

  await page.waitForFunction(
    (expectedTag) =>
      Array.from(document.querySelectorAll('#tagsUl input[name="tags[]"]')).some(
        (node) => String(node.value || "").trim().toLowerCase() === expectedTag.toLowerCase(),
      ),
    normalized,
    { timeout: readyTimeoutMs },
  );

}

async function ensureMultilingualTextareas(page, fieldKind, primaryLanguage, secondaryLanguage) {
  const addButton =
    fieldKind === "titles"
      ? page.locator(".fieldWithLangAddActionTitle")
      : page.locator(".fieldWithLangAddActionDescription");
  const selects = page.locator(`select[name^='${fieldKind}']`);

  if ((await selects.count()) === 0) {
    await clickMarked(addButton);
  }
  if ((await selects.count()) < 2) {
    await clickMarked(addButton);
  }

  const primary = normalizeText(primaryLanguage).toLowerCase();
  const secondary = normalizeText(secondaryLanguage).toLowerCase();

  if (primary) {
    await selectOptionMarked(selects.first(), primary);
  }
  if (secondary && (await selects.count()) > 1) {
    await selectOptionMarked(selects.nth(1), secondary);
  }
}

async function fillVocabularyMetadata(page, runtime) {
  const createHeader = page.getByRole("heading", { name: "Create a new Vocabulary", exact: true });
  await createHeader.waitFor({ state: "visible", timeout: readyTimeoutMs });

  await fillMarked(page.locator("#inputVocabPrefix"), runtime.creationPrefix);
  if ((await page.locator("#inputVocabUri").count()) > 0 && normalizeText(runtime.creationUri)) {
    await fillMarked(page.locator("#inputVocabUri"), runtime.creationUri);
  }
  if ((await page.locator("#inputVocabNsp").count()) > 0 && normalizeText(runtime.creationNamespace)) {
    await fillMarked(page.locator("#inputVocabNsp"), runtime.creationNamespace);
  }

  await ensureMultilingualTextareas(
    page,
    "titles",
    runtime.creationPrimaryLanguage || "en",
    runtime.creationSecondaryLanguage || "es",
  );
  await fillMarked(page.locator("textarea[name^='titles']").first(), runtime.creationTitle);
  if ((await page.locator("textarea[name^='titles']").count()) > 1) {
    await fillMarked(page
      .locator("textarea[name^='titles']")
      .nth(1), `${runtime.creationTitle} ES`);
  }

  await ensureMultilingualTextareas(
    page,
    "descriptions",
    runtime.creationPrimaryLanguage || "en",
    runtime.creationSecondaryLanguage || "es",
  );
  await fillMarked(page.locator("textarea[name^='descriptions']").first(), runtime.creationDescription);
  if ((await page.locator("textarea[name^='descriptions']").count()) > 1) {
    await fillMarked(page
      .locator("textarea[name^='descriptions']")
      .nth(1), `${runtime.creationDescription} ES`);
  }

  await ensureTagSelected(page, runtime.creationTag || "Services");

  const reviews = page.locator("textarea[name^='reviews']");
  if ((await reviews.count()) === 0) {
    await clickMarked(page.locator(".fieldReviewAddAction"));
  }
  await fillMarked(page.locator("textarea[name^='reviews']").first(), runtime.creationReview);
}

async function saveVocabulary(page, runtime = {}, expectedPrefix = "", expectedTitle = "") {
  const formPage = new OntologyHubVocabFormPage(page);
  const outcome = await formPage.save();
  const formErrors = await formPage.readFormErrors();
  const prefix = normalizeText(expectedPrefix || runtime.creationPrefix || runtime.expectedVocabularyPrefix);

  if (formErrors) {
    throw new Error(`Ontology Hub reported vocabulary form errors: ${formErrors}`);
  }
  if (outcome.responseStatus && outcome.responseStatus >= 400) {
    const responseExcerpt = normalizeText(outcome.responseBody).replace(/\s+/g, " ").slice(0, 240);
    throw new Error(
      `Ontology Hub vocabulary save returned HTTP ${outcome.responseStatus} for '${
        prefix || "unknown"
      }'. ${responseExcerpt ? `Response excerpt: ${responseExcerpt}` : `Final URL: ${outcome.finalUrl || "unknown"}`}`,
    );
  }

  const landedOnVocabularyDetail = /\/dataset\/vocabs\/[^/]+\/?$/i.test(outcome.finalUrl || "");
  if (!landedOnVocabularyDetail) {
    if (prefix) {
      await waitForPublicVocabularyDetail(
        page,
        runtime,
        prefix,
        expectedTitle || runtime.expectedVocabularyTitle || runtime.creationTitle,
      );
      return {
        ...outcome,
        finalUrl: page.url(),
        recoveredFromPublicProbe: true,
      };
    }

    throw new Error(
      `Ontology Hub did not publish the vocabulary after save. Final URL: ${
        outcome.finalUrl || "unknown"
      }`,
    );
  }

  return outcome;
}

async function confirmVisibleDialog(page, labels = [/^confirm$/i], options = {}) {
  for (const label of labels) {
    const button = page
      .locator(".ui-dialog-buttonpane button, .ui-dialog-buttonset button, button")
      .filter({ hasText: label })
      .last();
    if (await button.isVisible().catch(() => false)) {
      await clickMarked(button, options);
      return true;
    }
  }
  return false;
}

async function runIndexAllFromEdition(page, runtime) {
  try {
    await gotoEdition(page, runtime);
    const indexAllForm = page.locator("form[action='/edition/indexAll']").first();
    const formVisible = await indexAllForm.isVisible({ timeout: 5000 }).catch(() => false);
    if (!formVisible) {
      return;
    }

    await clickMarked(indexAllForm.locator("button.featureLink, button[type='submit']").first(), {
      timeout: 5000,
    });

    const confirmed = await page
      .waitForFunction(() => {
        const buttons = Array.from(
          document.querySelectorAll(".ui-dialog-buttonpane button, .ui-dialog-buttonset button, button"),
        );
        return buttons.some((node) => /confirm/i.test(String(node.textContent || "").trim()));
      }, null, { timeout: 2500 })
      .then(() => true)
      .catch(() => false);

    if (confirmed) {
      await confirmVisibleDialog(page, [/^confirm$/i], {
        noWaitAfter: true,
        timeout: 5000,
      });
    }

    await page.waitForLoadState("domcontentloaded", { timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(1000).catch(() => {});
  } catch (error) {
    console.warn(`[runIndexAllFromEdition] Non-blocking error: ${error.message}`);
  }
}

async function reopenVocabularyEditionAndSave(page, runtime, prefix, patch = {}) {
  await signInToEdition(page, runtime);
  const formPage = new OntologyHubVocabFormPage(page);
  await formPage.gotoEdit(runtime.baseUrl, prefix);
  await formPage.expectReady(prefix);

  if (patch.title) {
    await formPage.ensureTitles("en", "es", patch.title, `${patch.title} ES`);
  }
  if (patch.description) {
    await formPage.ensureDescriptions("en", "es", patch.description, `${patch.description} ES`);
  }

  await saveVocabulary(page, runtime, prefix, patch.title || runtime.expectedVocabularyTitle || runtime.creationTitle);
  await openVocabularyDetail(page, runtime, prefix, patch.title || "");
}

async function waitForPublicVocabularyDetail(page, runtime, prefix, title = "") {
  let lastReason = `Ontology Hub did not expose the public detail page for '${prefix}'.`;
  const maxAttempts = 30;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const detailProbe = await probeVocabularyDetail(page.request, runtime, prefix, {
      refresh: attempt > 1,
    });
    if (detailProbe.available) {
      await openVocabularyDetail(page, runtime, prefix, title);
      return;
    }

    lastReason = detailProbe.reason || lastReason;
    if (attempt < maxAttempts) {
      await page.waitForTimeout(2000);
    }
  }

  throw new Error(lastReason);
}

async function createVocabularyByUri(page, runtime) {
  await gotoEdition(page, runtime);
  await clickMarked(page.locator(".createVocab"));
  await page.locator("#dialogCreateVocab").waitFor({ state: "visible", timeout: readyTimeoutMs });
  await fillMarked(page.locator("#formDialogCreateVocabFromURI input[name='uri']"), runtime.creationUri);
  await clickMarked(page.getByRole("button", { name: "Confirm", exact: true }));
  await page.waitForLoadState("domcontentloaded");

  const duplicateError = normalizeText(
    await page
      .locator(".alert-error, #dialogCreateVocabError, #formErrors")
      .first()
      .textContent()
      .catch(() => ""),
  );
  if (/already exists/i.test(duplicateError)) {
    await waitForPublicVocabularyDetail(page, runtime, runtime.creationPrefix, runtime.creationTitle);
    return {
      prefix: runtime.creationPrefix,
      title: runtime.creationTitle,
      url: page.url(),
      method: "uri",
      reusedExistingImport: true,
    };
  }

  await fillVocabularyMetadata(page, runtime);
  await saveVocabulary(page, runtime, runtime.creationPrefix, runtime.creationTitle);

  return {
    prefix: runtime.creationPrefix,
    title: runtime.creationTitle,
    url: page.url(),
    method: "uri",
  };
}

async function createVocabularyFromRepository(page, runtime) {
  const existing = await reuseExistingPublicVocabulary(page, runtime, "repository");
  if (existing) {
    return existing;
  }

  await gotoEdition(page, runtime);
  await clickMarked(page.locator(".createVocab"));
  await page.locator("#dialogCreateVocab").waitFor({ state: "visible", timeout: readyTimeoutMs });
  await fillMarked(page
    .locator("#formDialogCreateVocabFromOntologyDevelopmentRepository input[name='repositoryUri']"), runtime.creationRepositoryUri);
  await clickMarked(page.getByRole("button", { name: "Confirm", exact: true }));
  await page.waitForLoadState("domcontentloaded");

  const visibleError = normalizeText(
    await page
      .locator(".alert-error, #dialogCreateVocabError, #formErrors")
      .first()
      .textContent()
      .catch(() => ""),
  );
  if (/already exists/i.test(visibleError)) {
    const reused = await reuseExistingPublicVocabulary(page, runtime, "repository");
    if (reused) {
      return reused;
    }
  }
  if (visibleError && !/create a new vocabulary/i.test((await page.content()).toLowerCase())) {
    const reused = await reuseExistingPublicVocabulary(page, runtime, "repository");
    if (reused) {
      return reused;
    }
    const repositoryDiagnostic = await probeRepositoryAccess(page, runtime.creationRepositoryUri).catch(() => "");
    throw new Error(
      `Ontology Hub rejected the repository registration: ${visibleError}` +
        (repositoryDiagnostic ? ` ${repositoryDiagnostic}` : ""),
    );
  }

  await fillVocabularyMetadata(page, runtime);
  await saveVocabulary(page, runtime, runtime.creationPrefix, runtime.creationTitle);

  return {
    prefix: runtime.creationPrefix,
    title: runtime.creationTitle,
    url: page.url(),
    method: "repository",
  };
}

function githubContentsApiUrl(repositoryUri) {
  const rawValue = normalizeText(repositoryUri);
  if (!rawValue) {
    return "";
  }

  let parsed;
  try {
    parsed = new URL(rawValue);
  } catch (error) {
    return "";
  }

  if (!["github.com", "www.github.com"].includes(parsed.hostname.toLowerCase())) {
    return "";
  }

  const parts = parsed.pathname.replace(/^\/+|\/+$/g, "").replace(/\.git$/i, "").split("/");
  if (parts.length < 2 || !parts[0] || !parts[1]) {
    return "";
  }

  return `https://api.github.com/repos/${parts[0]}/${parts[1]}/contents/tests`;
}

async function probeRepositoryAccess(page, repositoryUri) {
  const apiUrl = githubContentsApiUrl(repositoryUri);
  if (!apiUrl) {
    return "";
  }

  const response = await page.request.get(apiUrl, { timeout: 10000 });
  const headers = response.headers();
  const remaining = headers["x-ratelimit-remaining"];
  const limit = headers["x-ratelimit-limit"];
  const reset = headers["x-ratelimit-reset"];
  const resetText = reset ? new Date(Number(reset) * 1000).toISOString() : "";
  const rateLimit =
    limit || remaining || reset
      ? ` GitHub rate limit: remaining=${remaining || "unknown"}/${limit || "unknown"}` +
        (resetText ? `, reset=${resetText}` : "")
      : "";
  return `Runner-side repository diagnostic: ${apiUrl} returned HTTP ${response.status()}.${rateLimit}`;
}

async function reuseExistingPublicVocabulary(page, runtime, method) {
  const prefix = normalizeText(runtime.creationPrefix || runtime.expectedVocabularyPrefix);
  if (!prefix) {
    return null;
  }

  const detailProbe = await probeVocabularyDetail(page.request, runtime, prefix, {
    refresh: true,
  }).catch(() => null);
  if (!detailProbe || !detailProbe.available) {
    return null;
  }

  await openVocabularyDetail(page, runtime, prefix, runtime.creationTitle || runtime.expectedVocabularyTitle || "");
  return {
    prefix,
    title: normalizeText(runtime.creationTitle || runtime.expectedVocabularyTitle || prefix),
    url: page.url(),
    method,
    reusedExistingImport: true,
  };
}

async function createAgent(page, runtime, agent) {
  await gotoEdition(page, runtime);
  await page.goto(`${runtime.baseUrl}/edition/agents/new`, { waitUntil: "domcontentloaded" });
  await expectHealthyPage(page, "Create agent");

  await fillMarked(page.locator("input[name='name']"), agent.name);
  await selectOptionMarked(page.locator("select[name='type']"), agent.type || "person");
  await fillMarked(page.locator("input[name='prefUri']"), agent.prefUri);
  await clickMarked(page.locator("input[type='submit'][value='Save']"));
  await page.waitForLoadState("domcontentloaded");

  const agentDetailUrl = `${runtime.baseUrl}/dataset/agents/${encodeURIComponent(agent.name)}`;
  await page.goto(agentDetailUrl, { waitUntil: "domcontentloaded" });
  await expectHealthyPage(page, "Agent detail");
  await page.getByRole("heading", { level: 1, name: new RegExp(escapeRegExp(agent.name), "i") }).waitFor({
    state: "visible",
    timeout: 5000,
  });

  return {
    ...agent,
    detailUrl: page.url(),
  };
}

async function createUserForAgent(page, runtime, user) {
  await gotoEdition(page, runtime);
  await page.goto(`${runtime.baseUrl}/edition/signup`, { waitUntil: "domcontentloaded" });
  await expectHealthyPage(page, "Signup");

  await fillMarked(page.locator("#userNameAgent"), user.agentName);
  const suggestions = page.locator("ul.ui-autocomplete li");
  await suggestions.first().waitFor({ state: "visible", timeout: 5000 });
  await clickMarked(suggestions.filter({ hasText: new RegExp(`^\\s*${escapeRegExp(user.agentName)}\\s*$`, "i") }).first());
  await clickMarked(page.locator("#next:not([disabled])"));

  await fillMarked(page.locator("#email"), user.email);
  await fillMarked(page.locator("input[name='password']"), user.password);
  await fillMarked(page.locator("input[name='password_confirm']"), user.password);
  await clickMarked(page.locator("input[type='submit'][value='Submit']"));
  await page.waitForLoadState("domcontentloaded");

  const formErrors = normalizeText(await safeTextContent(page.locator("#formErrors")));
  if (formErrors) {
    throw new Error(`Ontology Hub rejected the user signup flow: ${formErrors}`);
  }

  await page.goto(`${runtime.baseUrl}/edition/users`, { waitUntil: "domcontentloaded" });
  const usersRow = page.locator(".SearchBoxperson").filter({ hasText: user.email }).first();
  if (await usersRow.isVisible().catch(() => false)) {
    return user;
  }

  const editionEmail = page.getByText(user.email, { exact: false }).first();
  if (await editionEmail.isVisible().catch(() => false)) {
    return user;
  }

  await page.goto(`${runtime.baseUrl}/edition`, { waitUntil: "domcontentloaded" });
  await page.getByText(user.email, { exact: false }).first().waitFor({ state: "visible", timeout: 5000 });

  return user;
}

async function reviewPendingUser(page, runtime, user) {
  await gotoEdition(page, runtime);
  const reviewForm = page.locator("#formUsers");
  await reviewForm.waitFor({ state: "visible", timeout: 5000 });

  const row = reviewForm.locator("li.editionBoxperson").filter({
    hasText: new RegExp(`${escapeRegExp(user.agentName || "")}|${escapeRegExp(user.email || "")}`, "i"),
  }).first();
  await row.waitFor({ state: "visible", timeout: 5000 });
  const checkbox = row.locator("input.checkboxUser");
  await checkMarked(checkbox);
  await clickMarked(reviewForm.locator("#submitUsers"));
  await page.waitForLoadState("domcontentloaded", { timeout: 10000 }).catch(() => {});

  const stillPending = reviewForm.locator("li.editionBoxperson").filter({
    hasText: new RegExp(escapeRegExp(user.email || user.agentName || ""), "i"),
  }).first();
  if (await stillPending.isVisible().catch(() => false)) {
    throw new Error(`The pending user review entry for '${user.email || user.agentName}' is still visible after save.`);
  }
}

async function promoteUserToAdmin(page, runtime, user) {
  await gotoEdition(page, runtime);
  await page.goto(`${runtime.baseUrl}/edition/users`, { waitUntil: "domcontentloaded" });
  try {
    await expectHealthyPage(page, "Users administration");
  } catch (error) {
    throw new Error(
      "The users administration page is broken, so the Admin promotion flow cannot continue. " +
        `This currently blocks OH-APP-17 after the preceding agent edit flow. Details: ${error.message}`,
    );
  }
  const row = page
    .locator(".SearchBoxperson, li, article, .editionBoxSugg")
    .filter({ hasText: user.email })
    .first();
  await row.waitFor({ state: "visible", timeout: 5000 });
  // The admin control is an input value, not visible text.
  const promoteButton = row
    .locator("input.statusSubmit[value='admin'], input[type='submit'][value='admin']")
    .first();
  if ((await promoteButton.count()) === 0) {
    throw new Error(`Could not find the Admin promotion control for '${user.email}'.`);
  }
  await clickMarked(promoteButton);
  await page.waitForLoadState("domcontentloaded");
  const deadline = Date.now() + Math.max(readyTimeoutMs * 2, 30000);

  while (Date.now() < deadline) {
    const refreshedRow = page
      .locator(".SearchBoxperson, li, article, .editionBoxSugg")
      .filter({ hasText: user.email })
      .first();
    if (await refreshedRow.isVisible().catch(() => false)) {
      return;
    }

    await page.waitForTimeout(3000);
    await signInToEdition(page, runtime);
    await page.goto(`${runtime.baseUrl}/edition/users`, { waitUntil: "domcontentloaded" });
  }

  await page
    .locator(".SearchBoxperson, li, article, .editionBoxSugg")
    .filter({ hasText: user.email })
    .first()
    .waitFor({ state: "visible", timeout: 5000 });
}

async function assertCreateUserControl(page, visible) {
  const createUserLink = page.locator("a[href='/edition/signup'], a[href='/edition/signup/']").first();
  if (visible) {
    await createUserLink.waitFor({ state: "visible", timeout: 5000 });
    return;
  }

  if ((await createUserLink.count()) > 0 && (await createUserLink.isVisible().catch(() => false))) {
    throw new Error("The + USER control is visible, but the current case expected it to be hidden.");
  }
}

async function deleteUserByEmail(page, runtime, email) {
  await signInToEdition(page, runtime);
  await page.goto(`${runtime.baseUrl}/edition/users`, { waitUntil: "domcontentloaded" });
  await expectHealthyPage(page, "Users administration");

  const row = page
    .locator(".SearchBoxperson, li, article, .editionBoxSugg")
    .filter({ hasText: email })
    .first();
  if (!(await row.isVisible().catch(() => false))) {
    return false;
  }

  await clickMarked(row.locator("img.removeUser, .removeUser").first());
  await clickMarked(page.getByRole("button", { name: "Confirm Deletion", exact: true }));
  await page.waitForLoadState("domcontentloaded");
  await page.goto(`${runtime.baseUrl}/edition/users`, { waitUntil: "domcontentloaded" });
  await expectHealthyPage(page, "Users administration after user deletion");

  const remaining = page
    .locator(".SearchBoxperson, li, article, .editionBoxSugg")
    .filter({ hasText: email })
    .first();
  if (await remaining.isVisible().catch(() => false)) {
    throw new Error(`User '${email}' is still visible after deletion.`);
  }

  return true;
}

async function editAgentFromPublicDetail(page, runtime, agentName, newAgentName) {
  await signInToEdition(page, runtime);
  await page.goto(`${runtime.baseUrl}/dataset/agents/${encodeURIComponent(agentName)}`, {
    waitUntil: "domcontentloaded",
  });
  await expectHealthyPage(page, "Agent detail");
  await clickMarked(page.locator("a[href*='/edition/agents/'] img[src*='edit_grey']"));
  await page.waitForLoadState("domcontentloaded");
  await fillMarked(page.locator("input[name='name']"), newAgentName);
  await clickMarked(page.locator("input[type='submit'][value='Save']"));
  await page.waitForLoadState("domcontentloaded");
  await page.goto(`${runtime.baseUrl}/dataset/agents/${encodeURIComponent(newAgentName)}`, {
    waitUntil: "domcontentloaded",
  });
  await page.getByRole("heading", { level: 1, name: new RegExp(escapeRegExp(newAgentName), "i") }).waitFor({
    state: "visible",
    timeout: 5000,
  });
}

async function deleteAgentFromPublicDetail(page, runtime, agentName) {
  await signInToEdition(page, runtime);
  await page.goto(`${runtime.baseUrl}/dataset/agents/${encodeURIComponent(agentName)}`, {
    waitUntil: "domcontentloaded",
  });
  await expectHealthyPage(page, "Agent detail");
  await clickMarked(page.locator("#agentDelete"));
  await clickMarked(page.getByRole("button", { name: "Confirm Deletion", exact: true }));
  await page.waitForLoadState("domcontentloaded");
  await page.goto(`${runtime.baseUrl}/dataset/agents`, { waitUntil: "domcontentloaded" });
  await fillMarked(page.locator("#searchInput"), agentName);
  await page.waitForTimeout(1000);
  const suggestions = page.locator("ul.ui-autocomplete li").filter({ hasText: new RegExp(escapeRegExp(agentName), "i") });
  if ((await suggestions.count()) > 0) {
    throw new Error(`Agent '${agentName}' is still returned by the public agents search after deletion.`);
  }
}

async function createTag(page, runtime, label) {
  await signInToEdition(page, runtime);
  await page.goto(`${runtime.baseUrl}/edition/tags/new`, { waitUntil: "domcontentloaded" });
  await expectHealthyPage(page, "Create tag");
  await fillMarked(page.locator("input[name='label']"), label);
  await clickMarked(page.locator("input[type='submit'][value='Save']"));
  await page.waitForLoadState("domcontentloaded");
  await page.goto(`${runtime.baseUrl}/edition/tags`, { waitUntil: "domcontentloaded" });
  await page.locator("#SearchGrid .SearchBoxtag").filter({ hasText: label }).first().waitFor({
    state: "visible",
    timeout: 5000,
  });
}

async function editTag(page, runtime, currentLabel, newLabel) {
  await signInToEdition(page, runtime);
  await page.goto(`${runtime.baseUrl}/edition/tags`, { waitUntil: "domcontentloaded" });
  const row = page.locator("#SearchGrid .SearchBoxtag").filter({ hasText: currentLabel }).first();
  await row.waitFor({ state: "visible", timeout: 5000 });
  await clickMarked(row.locator("form[name='formEdit'] img"));
  await page.waitForLoadState("domcontentloaded");
  await fillMarked(page.locator("input[name='label']"), newLabel);
  await clickMarked(page.locator("input[type='submit'][value='Save']"));
  await page.waitForLoadState("domcontentloaded");
  await page.goto(`${runtime.baseUrl}/edition/tags`, { waitUntil: "domcontentloaded" });
  await page.locator("#SearchGrid .SearchBoxtag").filter({ hasText: newLabel }).first().waitFor({
    state: "visible",
    timeout: 5000,
  });
}

async function deleteTag(page, runtime, label) {
  await signInToEdition(page, runtime);
  await page.goto(`${runtime.baseUrl}/edition/tags`, { waitUntil: "domcontentloaded" });
  const row = page.locator("#SearchGrid .SearchBoxtag").filter({ hasText: label }).first();
  await row.waitFor({ state: "visible", timeout: 5000 });
  await clickMarked(row.locator(".removeTag"));
  await clickMarked(page.getByRole("button", { name: "Confirm Deletion", exact: true }));
  await page.waitForLoadState("domcontentloaded");
  const remaining = page.locator("#SearchGrid .SearchBoxtag").filter({ hasText: label });
  if ((await remaining.count()) > 0 && (await remaining.first().isVisible().catch(() => false))) {
    throw new Error(`Tag '${label}' is still visible after deletion.`);
  }
}

async function downloadFirstN3(page, testInfo, baseName, options = {}) {
  const link = page.locator("a[href$='.n3']").first();
  await link.waitFor({ state: "visible", timeout: 5000 });
  const href = normalizeText(await link.getAttribute("href"));
  const filePath = testInfo.outputPath(`${baseName}.n3`);
  let suggestedFilename = path.basename(href || `${baseName}.n3`) || `${baseName}.n3`;
  const strategy = normalizeText(options.strategy || "browser").toLowerCase();
  const resolvedDownload = resolvePublicDownloadUrl(page.url(), href, options.runtime);

  const requestDownload = async () => {
    if (!resolvedDownload.url) {
      throw new Error("The vocabulary exposes an .n3 link without a usable href.");
    }

    const response = await page.request.get(resolvedDownload.url, { timeout: 5000 });
    if (!response.ok()) {
      throw new Error(`The .n3 resource returned HTTP ${response.status()} for ${resolvedDownload.url}`);
    }

    const body = await response.text();
    fs.writeFileSync(filePath, body, "utf8");
    suggestedFilename = path.basename(new URL(resolvedDownload.url).pathname) || suggestedFilename;
  };

  try {
    if (strategy === "request" || resolvedDownload.rewritten) {
      await requestDownload();
    } else {
      const downloadPromise = page.waitForEvent("download", { timeout: 5000 });
      await clickMarked(link);
      const download = await downloadPromise;
      await download.saveAs(filePath);
      suggestedFilename = download.suggestedFilename();
    }
  } catch (error) {
    await requestDownload();
  }

  const stat = fs.statSync(filePath);
  const persistedPath = persistGeneratedArtifact(filePath, `${normalizeText(baseName)}.n3`, "n3");
  return {
    filePath,
    persistedPath,
    suggestedFilename,
    size: stat.size,
    href,
    resolvedUrl: resolvedDownload.url,
    rewrittenPublicUrl: resolvedDownload.rewritten,
  };
}

function resolvePublicDownloadUrl(pageUrl, href, runtime = {}) {
  if (!href) {
    return { url: "", rewritten: false };
  }

  const parsedHref = new URL(href, pageUrl);
  const runtimeBase = normalizeText(runtime.baseUrl);
  if (!runtimeBase) {
    return { url: parsedHref.toString(), rewritten: false };
  }

  const publicBase = new URL(runtimeBase);
  const samePublicHost = parsedHref.hostname === publicBase.hostname;
  const internalHost =
    parsedHref.hostname.endsWith(".components") ||
    parsedHref.hostname.includes(".svc") ||
    parsedHref.hostname.includes("ontology-hub");

  if (samePublicHost || !internalHost) {
    return { url: parsedHref.toString(), rewritten: false };
  }

  const publicPathPrefix = publicBase.pathname.replace(/\/+$/, "");
  const hrefPath = parsedHref.pathname.startsWith("/") ? parsedHref.pathname : `/${parsedHref.pathname}`;
  const rewritten = new URL(publicBase.toString());
  rewritten.pathname =
    publicPathPrefix && !hrefPath.startsWith(`${publicPathPrefix}/`)
      ? `${publicPathPrefix}${hrefPath}`
      : hrefPath;
  rewritten.search = parsedHref.search;
  rewritten.hash = "";

  return { url: rewritten.toString(), rewritten: true };
}

async function openVocabularyDetail(page, runtime, prefix, title = "") {
  const detailPage = new OntologyHubVocabDetailPage(page);
  await detailPage.goto(runtime.baseUrl, prefix);
  await detailPage.expectReady(prefix, title);
  return detailPage;
}

async function openVersionsPage(page, runtime, prefix) {
  await gotoEdition(page, runtime);
  await page.goto(`${runtime.baseUrl}/edition/vocabs/${encodeURIComponent(prefix)}/versions`, {
    waitUntil: "domcontentloaded",
  });
  await expectHealthyPage(page, "Vocabulary versions");
  await page
    .locator(".editionIndexBoxHeader .title")
    .filter({ hasText: /versions/i })
    .first()
    .waitFor({ state: "visible", timeout: 5000 });
}

async function createVersion(page, version, filePath, options = {}) {
  await clickMarked(page.locator(".editionIndexBoxHeader .fieldReviewAddAction"));
  const dialog = page.locator("#dialogNewVersion");
  await dialog.waitFor({ state: "visible", timeout: 5000 });
  await fillMarked(dialog.locator("tr").filter({ hasText: /Version issued Date/i }).locator("input").first(), version.issued);
  await fillMarked(dialog.locator("tr").filter({ hasText: /Version Label/i }).locator("input, textarea").first(), version.name);
  await setInputFilesMarked(dialog.locator("input[type='file'], input[name='file']").first(), filePath);
  await dialog.locator("form#dialogNewVersionForm").evaluate((form) => form.submit());
  await page.waitForLoadState("domcontentloaded");

  const versionRow = page.locator(".editionBoxSugg").filter({
    hasText: new RegExp(`${escapeRegExp(version.issued)}|${escapeRegExp(version.name)}`, "i"),
  }).first();
  const unhealthyHeading = page.locator("h1").filter({ hasText: /50[0-9]|bad gateway|oops/i }).first();
  try {
    const outcome = await Promise.race([
      versionRow.waitFor({ state: "visible", timeout: 5000 }).then(() => "row"),
      unhealthyHeading.waitFor({ state: "visible", timeout: 5000 }).then(() => "error-page").catch(() => null),
    ]);
    if (outcome === "error-page") {
      const headingText = normalizeText(await safeTextContent(unhealthyHeading));
      throw new Error(`Ontology Hub returned an unhealthy page after version submit: ${headingText || "unknown error page"}`);
    }
  } catch (error) {
    if (options.runtime && options.prefix) {
      const recovery = await waitForRecoveredVersionRow(
        page,
        options.runtime,
        options.prefix,
        version,
        options.recoveryTimeoutMs || Math.max(readyTimeoutMs * 4, 180000),
      );
      if (recovery.recovered) {
        return recovery;
      }
    }
    const dialogText = normalizeText(await safeTextContent(dialog));
    const formErrors = normalizeText(await safeTextContent(page.locator("#formErrors, #dialogNewVersionFormErrors")));
    throw new Error(
      `${error.message || `Version creation did not complete within 15000ms for '${version.name}'.`} ` +
        `Dialog: ${dialogText || "no diagnostic text"}. ` +
        `Form errors: ${formErrors || "none"}`,
    );
  }
}

function versionRowPattern(version) {
  return new RegExp(`${escapeRegExp(version.issued)}|${escapeRegExp(version.name)}`, "i");
}

async function waitForRecoveredVersionRow(page, runtime, prefix, updatedVersion, timeoutMs = Math.max(readyTimeoutMs * 4, 180000)) {
  const versionsUrl = `${runtime.baseUrl}/edition/vocabs/${encodeURIComponent(prefix)}/versions`;
  const deadline = Date.now() + timeoutMs;
  const updatedRow = page.locator(".editionBoxSugg").filter({
    hasText: versionRowPattern(updatedVersion),
  }).first();
  let lastSignal = "";

  while (Date.now() < deadline) {
    await page.waitForTimeout(5000);
    await signInToEdition(page, runtime, {
      recoveryTimeoutMs: 15000,
    }).catch((error) => {
      lastSignal = error && error.message ? error.message : String(error);
    });
    try {
      await page.goto(versionsUrl, {
        waitUntil: "domcontentloaded",
        timeout: navigationTimeoutMs,
      });
    } catch (error) {
      lastSignal = error && error.message ? error.message : String(error);
      continue;
    }

    lastSignal = normalizeText(await safeTextContent(page.locator("h1").first()));
    if (await pageShowsTransientAvailabilityFailure(page)) {
      continue;
    }

    try {
      await expectHealthyPage(page, "Vocabulary versions");
      await page
        .locator(".editionIndexBoxHeader .title")
        .filter({ hasText: /versions/i })
        .first()
        .waitFor({ state: "visible", timeout: 5000 });
      await updatedRow.waitFor({ state: "visible", timeout: 5000 });
      return {
        recovered: true,
        versionsUrl,
        finalUrl: page.url(),
        lastSignal,
      };
    } catch (error) {
      lastSignal = error && error.message ? error.message : lastSignal;
    }
  }

  return {
    recovered: false,
    versionsUrl,
    finalUrl: page.url(),
    lastSignal: lastSignal || "Ontology Hub did not recover the versions page in time.",
  };
}

async function editVersion(page, runtime, prefix, currentVersionName, updatedVersion, options = {}) {
  const versionRow = page.locator(".editionBoxSugg").filter({ hasText: currentVersionName }).first();
  await versionRow.waitFor({ state: "visible", timeout: 5000 });
  await clickMarked(versionRow.locator(".imageVersionActionEdit"));
  const dialog = page.locator("#dialogEditVersion");
  await dialog.waitFor({ state: "visible", timeout: 5000 });
  await fillMarked(
    dialog.locator("tr").filter({ hasText: /Version issued Date/i }).locator("input, textarea").first(),
    updatedVersion.issued,
  );
  await fillMarked(
    dialog.locator("tr").filter({ hasText: /Version Label/i }).locator("input, textarea").first(),
    updatedVersion.name,
  );
  await dialog.locator("form#dialogEditVersionForm").evaluate((form) => form.submit());
  await page.waitForLoadState("domcontentloaded");

  const updatedRow = page.locator(".editionBoxSugg").filter({
    hasText: versionRowPattern(updatedVersion),
  }).first();
  const unhealthyHeading = page.locator("h1").filter({ hasText: /50[0-9]|bad gateway|oops/i }).first();
  try {
    const outcome = await Promise.race([
      updatedRow.waitFor({ state: "visible", timeout: 5000 }).then(() => "row"),
      unhealthyHeading.waitFor({ state: "visible", timeout: 5000 }).then(() => "error-page").catch(() => null),
    ]);
    if (outcome === "error-page") {
      const headingText = normalizeText(await safeTextContent(unhealthyHeading));
      throw new Error(
        `Ontology Hub returned an unhealthy page after version edit submit: ${headingText || "unknown error page"}`,
      );
    }
    return {
      recoveredFromTransientFailure: false,
      finalUrl: page.url(),
    };
  } catch (error) {
    const transientFailure = await pageShowsTransientAvailabilityFailure(page);
    if (runtime && prefix) {
      const recovery = await waitForRecoveredVersionRow(
        page,
        runtime,
        prefix,
        updatedVersion,
        options.recoveryTimeoutMs,
      );
      if (recovery.recovered) {
        return {
          recoveredAfterDelayedVersionIndexing: !transientFailure,
          recoveredFromTransientFailure: transientFailure,
          ...recovery,
        };
      }
    }

    const dialogText = normalizeText(await safeTextContent(dialog));
    const formErrors = normalizeText(await safeTextContent(page.locator("#formErrors, #dialogEditVersionformErrors")));
    throw new Error(
      `${error.message || `Version edit did not complete within 15000ms for '${updatedVersion.name}'.`} ` +
        `Dialog: ${dialogText || "no diagnostic text"}. ` +
        `Form errors: ${formErrors || "none"}`,
    );
  }
}

async function deleteVersion(page, versionName) {
  const versionRow = page.locator(".editionBoxSugg").filter({ hasText: versionName }).first();
  await versionRow.waitFor({ state: "visible", timeout: 5000 });
  await clickMarked(versionRow.locator(".imageVersionActionRemove"));
  await clickMarked(page.getByRole("button", { name: "Confirm Deletion", exact: true }));
  await page.waitForLoadState("domcontentloaded");
  const remaining = page.locator(".editionBoxSugg").filter({ hasText: versionName });
  if ((await remaining.count()) > 0 && (await remaining.first().isVisible().catch(() => false))) {
    throw new Error(`Version '${versionName}' is still visible after deletion.`);
  }
}

async function deleteVocabulary(page, runtime, prefix, options = {}) {
  await signInToEdition(page, runtime, {
    recoveryTimeoutMs: options.recoveryTimeoutMs,
  });
  await page.goto(`${runtime.baseUrl}/dataset/vocabs/${encodeURIComponent(prefix)}`, {
    waitUntil: "domcontentloaded",
  });
  await expectHealthyPage(page, "Vocabulary detail");
  await clickMarked(page.locator("#vocabDelete"));
  await clickMarked(page.getByRole("button", { name: "Confirm Deletion", exact: true }));
  await page.waitForLoadState("domcontentloaded");
  const deadline = Date.now() + 60000;
  while (true) {
    await page.goto(`${runtime.baseUrl}/dataset/vocabs?q=${encodeURIComponent(prefix)}`, {
      waitUntil: "domcontentloaded",
    });
    const remaining = page.locator("#SearchGrid").getByText(prefix, { exact: false });
    const stillVisible = (await remaining.count()) > 0 && (await remaining.first().isVisible().catch(() => false));
    if (!stillVisible) {
      break;
    }
    if (Date.now() >= deadline) {
      throw new Error(`Vocabulary '${prefix}' is still visible in the catalog after deletion.`);
    }
    await page.waitForTimeout(3000);
  }
}

async function updateVocabularyMetadata(page, runtime, prefix, patch) {
  await signInToEdition(page, runtime);
  const formPage = new OntologyHubVocabFormPage(page);
  await formPage.gotoEdit(runtime.baseUrl, prefix);
  await formPage.expectReady(prefix);

  if (patch.title) {
    await formPage.ensureTitles("en", "es", patch.title, `${patch.title} ES`);
  }
  if (patch.description) {
    await formPage.ensureDescriptions("en", "es", patch.description, `${patch.description} ES`);
  }
  if (patch.review) {
    await formPage.setReview(patch.review);
  }
  if (patch.tag) {
    await ensureTagSelected(page, patch.tag);
  }

  await saveVocabulary(page, runtime, prefix, patch.title || runtime.expectedVocabularyTitle || runtime.creationTitle);
  await openVocabularyDetail(page, runtime, prefix, patch.title || "");
}

async function saveTextArtifact(testInfo, name, content) {
  const filePath = testInfo.outputPath(name);
  fs.writeFileSync(filePath, content, "utf8");
  return filePath;
}

async function resolveThemisSource(page) {
  return page.locator("#themisVocabContainer").evaluate((node) => ({
    uri: node.getAttribute("data-uri") || "",
    sourceUrl: node.getAttribute("data-source-url") || "",
    prefix: node.getAttribute("data-vocab-prefix") || "",
  }));
}

async function waitForThemisPanel(page) {
  await page.waitForFunction(
    () => {
      const tab = document.querySelector(".ontology-tab[data-onto-target='themis']");
      const textTab = Array.from(document.querySelectorAll("[role='tab'], .ontology-tab, button, a")).find((node) =>
        /themis/i.test(String(node.textContent || "")),
      );
      const panel = document.querySelector(".ontology-tab-panel[data-onto-panel='themis']");
      const container = document.querySelector("#themisVocabContainer");
      const executeButton = document.querySelector("#executeThemisButton");
      const automaticRadio = document.querySelector("#themisModeAutomatic");
      const manualRadio = document.querySelector("#themisModeManual");
      const headings = Array.from(document.querySelectorAll("h1, h2, h3"));
      const isVisible = (node) =>
        Boolean(node) && Boolean(node.offsetWidth || node.offsetHeight || node.getClientRects().length);
      const themisHeadingVisible = headings.some(
        (node) => isVisible(node) && /themis validator/i.test(String(node.textContent || "")),
      );
      const tabActive =
        (tab instanceof HTMLElement && tab.getAttribute("aria-selected") === "true") ||
        (textTab instanceof HTMLElement && textTab.getAttribute("aria-selected") === "true") ||
        (panel instanceof HTMLElement && panel.classList.contains("is-active"));
      const themisUiVisible =
        isVisible(executeButton) ||
        isVisible(automaticRadio) ||
        isVisible(manualRadio) ||
        themisHeadingVisible;
      const themisMetadataReady =
        container instanceof HTMLElement &&
        Boolean(
          container.getAttribute("data-source-url") ||
            container.getAttribute("data-uri") ||
            container.getAttribute("data-vocab-prefix"),
        );

      return (tabActive || themisUiVisible) && themisUiVisible && themisMetadataReady;
    },
    { timeout: readyTimeoutMs },
  );
  await page.locator("#themisModeManual").waitFor({ state: "visible", timeout: readyTimeoutMs });
}

async function openThemisPanel(page) {
  const toolToggle = page.locator("#normal-button").first();
  if (await toolToggle.isVisible().catch(() => false)) {
    await clickMarked(toolToggle).catch(async () => {
      await clickMarked(toolToggle, { force: true });
    });
  }

  await page
    .waitForFunction(
      () =>
        Array.from(document.querySelectorAll("[role='tab'], .ontology-tab, button, a, li")).some((node) =>
          /^themis$/i.test(String(node.textContent || "").trim()),
        ) ||
        Boolean(document.querySelector("#user-options img[src='/img/themis.png']")) ||
        Boolean(document.querySelector(".tool-item.gradient img[src='/img/themis.png']")),
      { timeout: readyTimeoutMs },
    )
    .catch(() => {});

  const entrypoints = [
    {
      name: "visible-tool-item",
      locator: page.locator(".tool-item.gradient img[src='/img/themis.png']").first(),
    },
    {
      name: "themis-tab",
      locator: page.locator(".ontology-tab[data-onto-target='themis']").first(),
    },
    {
      name: "legacy-user-options",
      locator: page.locator("#user-options img[src='/img/themis.png']").first(),
    },
  ];
  if (typeof page.getByRole === "function") {
    entrypoints.splice(1, 0, {
      name: "accessible-themis-tab",
      locator: page.getByRole("tab", { name: /themis/i }).first(),
    });
  }
  let textTabLocator = null;
  try {
    textTabLocator = page.locator("[role='tab'], .ontology-tab, button, a");
  } catch (_error) {
    textTabLocator = null;
  }
  if (textTabLocator && typeof textTabLocator.filter === "function") {
    entrypoints.splice(2, 0, {
      name: "text-themis-tab",
      locator: textTabLocator.filter({ hasText: /themis/i }).first(),
    });
  }
  if (typeof page.getByText === "function") {
    entrypoints.splice(3, 0, {
      name: "visible-themis-text",
      locator: page.getByText(/^Themis$/i).first(),
    });
  }
  const attempts = [];
  let lastError = null;

  for (const entrypoint of entrypoints) {
    const count = await entrypoint.locator.count().catch(() => 0);
    if (count === 0) {
      attempts.push({
        name: entrypoint.name,
        present: false,
        visible: false,
      });
      continue;
    }

    const visible = await entrypoint.locator.isVisible().catch(() => false);
    attempts.push({
      name: entrypoint.name,
      present: true,
      visible,
    });
    if (!visible) {
      continue;
    }

    try {
      await entrypoint.locator.scrollIntoViewIfNeeded().catch(() => {});
      await clickMarked(entrypoint.locator);
      await waitForThemisPanel(page);
      return {
        entrypoint: entrypoint.name,
        attempts,
        fallback: false,
      };
    } catch (error) {
      lastError = error;
    }
  }

  const fallbackActivated = await page
    .evaluate(() => {
      if (typeof window.activateOntologyTab === "function") {
        window.activateOntologyTab("themis");
        return true;
      }

      const tab = document.querySelector(".ontology-tab[data-onto-target='themis']");
      if (tab instanceof HTMLElement) {
        tab.click();
        return true;
      }

      const textTab = Array.from(document.querySelectorAll("[role='tab'], .ontology-tab, button, a")).find((node) =>
        /themis/i.test(String(node.textContent || "")),
      );
      if (textTab instanceof HTMLElement) {
        textTab.click();
        return true;
      }

      const visibleText = Array.from(document.querySelectorAll("button, a, li, span, div")).find((node) =>
        /^themis$/i.test(String(node.textContent || "").trim()),
      );
      if (visibleText instanceof HTMLElement) {
        visibleText.click();
        return true;
      }

      return false;
    })
    .catch(() => false);
  if (!fallbackActivated) {
    const detail = JSON.stringify(attempts);
    throw new Error(
      `Themis entrypoint is not reachable from the vocabulary detail page. Attempts: ${detail}`,
    );
  }

  try {
    await waitForThemisPanel(page);
    return {
      entrypoint: "script-fallback",
      attempts,
      fallback: true,
    };
  } catch (error) {
    const detail = JSON.stringify(attempts);
    throw new Error(
      `Themis panel did not become visible after fallback activation. Attempts: ${detail}. ` +
        `Last error: ${String((lastError && lastError.message) || error.message || error)}`,
    );
  }
}

async function buildThemisExampleFile(page, runtime, sourceUrl, testInfo) {
  const response = await page.request.post(`${runtime.baseUrl}/dataset/api/v2/validators/themis/example`, {
    data: {
      sourceUrl,
    },
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json, text/plain;q=0.9, */*;q=0.8",
    },
  });

  if (!response.ok()) {
    throw new Error(`Themis example generation failed with HTTP ${response.status()}.`);
  }

  const body = await response.text();
  if (!normalizeText(body)) {
    throw new Error("Themis example generation returned an empty payload.");
  }

  return saveTextArtifact(testInfo, "test_cases.txt", body);
}

function resolveThemisTestFile() {
  const explicitPath = normalizeText(process.env.ONTOLOGY_HUB_THEMIS_TEST_FILE);
  const candidates = [
    explicitPath,
    path.resolve(__dirname, "../fixtures/themis/test_cases.txt"),
    path.resolve(__dirname, "../fixtures/themis/test_cases_2_cases.txt"),
  ].filter(Boolean);

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }

  throw new Error(
    "Themis requires the agreed test case file with the two validation cases. " +
      "Set ONTOLOGY_HUB_THEMIS_TEST_FILE or place it at " +
      "'validation/components/ontology_hub/functional/fixtures/themis/test_cases.txt'.",
  );
}

function listZipEntries(filePath) {
  try {
    const output = execFileSync("unzip", ["-l", filePath], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });
    return output
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => /\S/.test(line) && !/^Archive:/.test(line))
      .filter((line) => /[A-Za-z0-9_.-]+\.[A-Za-z0-9]+$/.test(line))
      .map((line) => line.split(/\s+/).pop());
  } catch (error) {
    return [];
  }
}

module.exports = {
  DEFAULT_REPOSITORY_URI,
  DEFAULT_URI,
  buildVocabularyRuntime,
  buildExcelRepositoryVocabularyRuntime,
  buildExcelUriVocabularyRuntime,
  buildThemisExampleFile,
  deleteRunState,
  createAgent,
  createTag,
  createUserForAgent,
  createVersion,
  createVocabularyByUri,
  createVocabularyFromRepository,
  deleteAgentFromPublicDetail,
  deleteUserByEmail,
  deleteTag,
  deleteVersion,
  deleteVocabulary,
  downloadFirstN3,
  editAgentFromPublicDetail,
  editTag,
  editVersion,
  expectHealthyPage,
  listZipEntries,
  loadRunState,
  normalizeText,
  openVocabularyDetail,
  openThemisPanel,
  openVersionsPage,
  promoteUserToAdmin,
  persistGeneratedArtifact,
  reopenVocabularyEditionAndSave,
  resolveThemisTestFile,
  REPOSITORY_VOCAB_STATE_KEY,
  resolveThemisSource,
  reviewPendingUser,
  runIndexAllFromEdition,
  runtimeFromCreatedVocabulary,
  saveRunState,
  saveTextArtifact,
  signInToEdition,
  signOut,
  assertCreateUserControl,
  updateVocabularyMetadata,
  VISUALIZATION_N3_STATE_KEY,
  URI_VOCAB_STATE_KEY,
  VERSION_VOCAB_STATE_KEY,
  VERSION_STATE_KEY,
  waitForThemisPanel,
  waitForRecoveredVersionRow,
};
