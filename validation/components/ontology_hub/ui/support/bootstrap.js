const fs = require("fs");
const { checkMarked, clickMarked, fillMarked, selectOptionMarked } = require("./live-marker");
const path = require("path");
const { resolveOntologyHubTimeouts } = require("../runtime");

const {
  probeTermSearchApi,
  probeTermsPage,
  probeVocabularyAutocomplete,
  probeVocabularyDetail,
} = require("./capabilities");

const bootstrapCache = new Map();
const { readyTimeoutMs, navigationTimeoutMs } = resolveOntologyHubTimeouts();

function normalizeText(value) {
  return String(value || "").trim();
}

function textShowsTransientAvailabilityFailure(value) {
  const normalized = normalizeText(value).toLowerCase();
  if (!normalized) {
    return false;
  }

  return (
    /\b502\b/.test(normalized) ||
    /\b503\b/.test(normalized) ||
    normalized.includes("service temporarily unavailable") ||
    normalized.includes("bad gateway")
  );
}

function normalizeRepositoryUri(value) {
  const candidate = normalizeText(value);
  if (!candidate) {
    return "";
  }

  try {
    const parsed = new URL(candidate);
    let pathname = parsed.pathname.replace(/\/+$/, "");
    if (
      ["github.com", "www.github.com", "gitlab.com", "www.gitlab.com"].includes(
        parsed.hostname.toLowerCase(),
      ) &&
      pathname.toLowerCase().endsWith(".git")
    ) {
      pathname = pathname.slice(0, -4);
    }
    parsed.pathname = pathname;
    return parsed.toString().replace(/\/$/, "");
  } catch (error) {
    return candidate.replace(/\/$/, "");
  }
}

function escapeRegExp(value) {
  return normalizeText(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function isEditionLoginUrl(url) {
  return /\/edition(?:\/lov)?\/login\/?$/.test(String(url || ""));
}

function isEditionUrl(url) {
  return /\/edition(?:\/lov)?\/?$/.test(String(url || ""));
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

async function readPageSignalText(page) {
  const heading = await readPrimaryHeading(page);
  if (heading) {
    return heading;
  }

  const title = normalizeText(await page.title().catch(() => ""));
  if (title) {
    return title;
  }

  const body = normalizeText(
    await page
      .locator("body")
      .evaluate((node) => (node.textContent || "").replace(/\s+/g, " ").trim())
      .catch(() => ""),
  );
  return body ? body.slice(0, 240) : "";
}

async function pageShowsTransientAvailabilityFailure(page) {
  const signalText = await readPageSignalText(page);
  return textShowsTransientAvailabilityFailure(signalText);
}

function loginErrorHint(runtime) {
  return (
    `Revisa ONTOLOGY_HUB_ADMIN_EMAIL y ONTOLOGY_HUB_ADMIN_PASSWORD. ` +
    `Usuario actual: ${runtime.adminEmail}`
  );
}

function stateFilePath() {
  const explicit =
    process.env.ONTOLOGY_HUB_INTEGRATION_STATE_FILE || process.env.ONTOLOGY_HUB_BOOTSTRAP_STATE_FILE;
  if (explicit) {
    return explicit;
  }

  return path.resolve(__dirname, "../../integration/state/ontology-hub-bootstrap.json");
}

function readStateFile(filePath) {
  if (!fs.existsSync(filePath)) {
    return null;
  }

  try {
    const payload = JSON.parse(fs.readFileSync(filePath, "utf8"));
    return payload && typeof payload === "object" ? payload : null;
  } catch (error) {
    return null;
  }
}

function writeStateFile(filePath, payload) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(payload, null, 2), "utf8");
}

function mergeBootstrapState(current, patch) {
  const base = current && typeof current === "object" ? current : {};
  const next = patch && typeof patch === "object" ? patch : {};
  return {
    ...base,
    ...next,
    workflow: {
      ...(base.workflow && typeof base.workflow === "object" ? base.workflow : {}),
      ...(next.workflow && typeof next.workflow === "object" ? next.workflow : {}),
    },
    editOutcome: {
      ...(base.editOutcome && typeof base.editOutcome === "object" ? base.editOutcome : {}),
      ...(next.editOutcome && typeof next.editOutcome === "object" ? next.editOutcome : {}),
    },
  };
}

async function readResponseJson(response) {
  if (!response) {
    return {
      body: "",
      payload: null,
    };
  }

  const body = await response.text().catch(() => "");
  try {
    return {
      body,
      payload: JSON.parse(body),
    };
  } catch (error) {
    return {
      body,
      payload: null,
    };
  }
}

async function currentFormErrors(page) {
  const content = await page
    .evaluate(() => document.querySelector("#formErrors")?.textContent || "")
    .catch(() => "");
  return normalizeText(content).replace(/\s+/g, " ");
}

async function hasSelectedTag(page, tagLabel) {
  const expected = normalizeText(tagLabel).toLowerCase();
  if (!expected) {
    return false;
  }

  const selectedTags = await page
    .locator("#tagsUl input[name='tags[]']")
    .evaluateAll((nodes) =>
      nodes
        .map((node) => String(node.value || "").trim().toLowerCase())
        .filter(Boolean),
    )
    .catch(() => []);
  return selectedTags.includes(expected);
}

async function waitForSelectedTag(page, tagLabel) {
  const expected = normalizeText(tagLabel).toLowerCase();
  await page.waitForFunction(
    (expectedTag) =>
      Array.from(document.querySelectorAll('#tagsUl input[name="tags[]"]')).some(
        (node) => String(node.value || "").trim().toLowerCase() === expectedTag,
      ),
    expected,
    { timeout: readyTimeoutMs },
  );
}

async function ensureVocabularyTag(page, runtime) {
  const tagLabel = normalizeText(runtime.creationTag);
  if (!tagLabel) {
    return {
      selected: false,
      created: false,
    };
  }

  if (await hasSelectedTag(page, tagLabel)) {
    return {
      selected: true,
      created: false,
    };
  }

  await clickMarked(page.locator(".fieldTagsAddAction"));
  await page.locator("#listOfTags").waitFor({ state: "visible", timeout: readyTimeoutMs });

  const tagPattern = new RegExp(`^\\s*${escapeRegExp(tagLabel)}\\s*$`, "i");
  let tagOption = page.locator("#tagsPickerList .tagFromList").filter({ hasText: tagPattern }).first();
  let created = false;

  if ((await tagOption.count()) === 0) {
    const createResponsePromise = page
      .waitForResponse(
        (response) => {
          if (response.request().method() !== "POST") {
            return false;
          }
          return /\/edition\/tags\/?$/.test(new URL(response.url()).pathname);
        },
        { timeout: readyTimeoutMs },
      )
      .catch(() => null);

    await clickMarked(page.locator("#toggleCreateTag"));
    await fillMarked(page.locator("#newTagLabel"), tagLabel);
    await clickMarked(page.locator("#btnCreateTag"));

    const createResponse = await createResponsePromise;
    const createError = normalizeText(
      await page
        .locator("#newTagError")
        .textContent()
        .catch(() => ""),
    );
    if (createError) {
      throw new Error(`No se pudo crear la etiqueta '${tagLabel}' en Ontology Hub: ${createError}`);
    }
    if (createResponse && !createResponse.ok()) {
      throw new Error(
        `La creacion de la etiqueta '${tagLabel}' devolvio HTTP ${createResponse.status()}.`,
      );
    }

    tagOption = page.locator("#tagsPickerList .tagFromList").filter({ hasText: tagPattern }).first();
    await tagOption.waitFor({ state: "visible", timeout: readyTimeoutMs });
    created = true;
  }

  if (!(await hasSelectedTag(page, tagLabel))) {
    await clickMarked(tagOption);
  }
  await waitForSelectedTag(page, tagLabel);

  if (await page.locator("#listOfTags").isVisible().catch(() => false)) {
    await page.keyboard.press("Escape").catch(() => {});
  }

  return {
    selected: true,
    created,
  };
}

async function ensureTextareaLanguages(page, fieldName, primaryLanguage, secondaryLanguage) {
  const selectLocator = page.locator(`select[name^='${fieldName}']`);
  const total = await selectLocator.count();
  const primary = normalizeText(primaryLanguage).toLowerCase();
  const secondary = normalizeText(secondaryLanguage).toLowerCase();

  if (primary && total > 0) {
    try {
      await selectOptionMarked(selectLocator.first(), primary);
    } catch (error) {
      throw new Error(`No se pudo seleccionar el idioma '${primary}' para ${fieldName}.`);
    }
  }

  if (secondary && total > 1) {
    try {
      await selectOptionMarked(selectLocator.nth(1), secondary);
    } catch (error) {
      throw new Error(`No se pudo seleccionar el idioma '${secondary}' para ${fieldName}.`);
    }
  }
}

async function submitVocabularyMetadata(page, runtime) {
  const saveResponsePromise = page
    .waitForResponse(
      (response) => {
        if (response.request().method() !== "POST") {
          return false;
        }
        return /^\/edition\/vocabs(?:\/[^/]+)?\/?$/.test(new URL(response.url()).pathname);
      },
      { timeout: navigationTimeoutMs },
    )
    .catch(() => null);
  const redirectPromise = page
    .waitForURL(/\/dataset\/vocabs\/[^/]+\/?$/, { timeout: navigationTimeoutMs })
    .then(() => true)
    .catch(() => false);

  await clickMarked(page.locator(".editionSaveButtonRight"));

  const saveResponse = await saveResponsePromise;
  const { body, payload } = await readResponseJson(saveResponse);
  const redirectTarget = normalizeText(payload && payload.redirect);

  if (saveResponse && !saveResponse.ok()) {
    throw new Error(
      `El guardado del vocabulario devolvio HTTP ${saveResponse.status()}.${
        body ? ` Respuesta: ${normalizeText(body).slice(0, 240)}` : ""
      }`,
    );
  }

  let redirected = await redirectPromise;
  if (!redirected && redirectTarget) {
    await page.goto(new URL(redirectTarget, runtime.baseUrl).toString(), {
      waitUntil: "domcontentloaded",
    });
    redirected = true;
  } else if (redirected) {
    await page.waitForLoadState("domcontentloaded").catch(() => {});
  }

  const stillOnCreationForm = await page
    .getByRole("heading", { name: "Create a new Vocabulary", exact: true })
    .isVisible()
    .catch(() => false);
  const formErrors = await currentFormErrors(page);
  if (stillOnCreationForm || formErrors) {
    return {
      created: false,
      duplicateByPrefix: /prefix .* already used/i.test(formErrors),
      url: page.url(),
      responseStatus: saveResponse ? saveResponse.status() : 0,
      redirectTarget,
      errorMessage: formErrors || normalizeText(body) || normalizeText(payload && payload.err),
    };
  }

  return {
    created: redirected || /\/dataset\/vocabs\/[^/]+\/?$/.test(page.url()),
    duplicateByPrefix: false,
    url: page.url(),
    responseStatus: saveResponse ? saveResponse.status() : 0,
    redirectTarget,
    errorMessage: normalizeText(payload && payload.err),
  };
}

function buildRetryRuntime(runtime) {
  const seed = `${Date.now()}${Math.floor(Math.random() * 10000)
    .toString()
    .padStart(4, "0")}`;
  const basePrefix = normalizeText(runtime.creationPrefix || runtime.expectedVocabularyPrefix || "ontologyhub");
  const retryPrefix = `${basePrefix}-${seed}`.toLowerCase();

  return {
    ...runtime,
    expectedVocabularyPrefix: retryPrefix,
    creationPrefix: retryPrefix,
    listingSearchTerm: retryPrefix,
  };
}

function isRepositoryAccessError(message) {
  const normalized = normalizeText(message).toLowerCase();
  return (
    normalized.includes("can not access the repository") ||
    normalized.includes("cannot access the repository") ||
    normalized.includes("check the if the url is correct") ||
    normalized.includes("repository is public")
  );
}

async function gotoEdition(page, runtime) {
  let lastError = null;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      await page.goto(`${runtime.baseUrl}/edition`, { waitUntil: "domcontentloaded" });

      if (isEditionLoginUrl(page.url())) {
        await fillMarked(page.getByPlaceholder("Email"), runtime.adminEmail);
        await fillMarked(page.getByPlaceholder("Password"), runtime.adminPassword);
        await clickMarked(page.getByRole("button", { name: /log in it!?/i }));
        await page.waitForLoadState("domcontentloaded").catch(() => {});

        const invalidCredentials = page.getByText("Invalid email or password.", { exact: true });
        const invalidCredentialsVisible = await invalidCredentials
          .waitFor({ state: "visible", timeout: 1000 })
          .then(() => true)
          .catch(() => false);
        if (invalidCredentialsVisible) {
          throw new Error(
            `El login de Ontology Hub fue rechazado por el entorno actual. ${loginErrorHint(runtime)}`,
          );
        }
      }

      if (!isEditionUrl(page.url())) {
        const editionLink = page.getByRole("link", { name: /edition/i }).first();
        if ((await editionLink.count()) > 0) {
          await clickMarked(editionLink);
          await page.waitForLoadState("domcontentloaded");
        }
      }

      await page.locator(".createVocab").waitFor({ state: "visible", timeout: readyTimeoutMs });
      return;
    } catch (error) {
      lastError = error;
      const formErrors = await page.locator("#formErrors").textContent().catch(() => "");
      const pageSignal = await readPageSignalText(page);
      const transientFailure = await pageShowsTransientAvailabilityFailure(page);
      if (!transientFailure || attempt >= 3) {
        throw new Error(
          `No se pudo acceder al area de edicion de Ontology Hub desde ${page.url()}. ` +
            `${String(formErrors || "").trim() || pageSignal || "No se detectaron errores visibles."}`,
        );
      }
      await page.waitForTimeout(2000);
    }
  }

  throw lastError || new Error("Ontology Hub edition navigation did not stabilize.");
}

async function ensurePublicDetail(page, runtime, prefix, title) {
  const detailUrl = `${runtime.baseUrl}/dataset/vocabs/${encodeURIComponent(prefix)}`;
  let lastReason = `La vista detalle publica de '${prefix}' no estuvo lista a tiempo.`;
  const maxAttempts = 30;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const detailProbe = await probeVocabularyDetail(page.request, runtime, prefix, {
      refresh: attempt > 1,
    });
    if (detailProbe.available) {
      await page.goto(detailUrl, {
        waitUntil: "domcontentloaded",
      });

      const metadata = page.locator("section#posts").getByText("Metadata", { exact: true });
      await metadata.waitFor({ state: "visible", timeout: readyTimeoutMs });

      if (title) {
        await page.locator("section#post").getByText(title, { exact: false }).first().waitFor({
          state: "visible",
          timeout: readyTimeoutMs,
        });
      }
      return;
    }

    lastReason = detailProbe.reason || lastReason;
    if (attempt < maxAttempts) {
      await page.waitForTimeout(2000);
    }
  }

  throw new Error(lastReason);
}

async function openCreateVocabularyDialog(page, runtime) {
  await gotoEdition(page, runtime);

  await clickMarked(page.locator(".createVocab"));
  await page.locator("#dialogCreateVocab").waitFor({ state: "visible" });
}

async function fillVocabularyMetadataForm(page, runtime, options = {}) {
  const fillUri = options.fillUri !== false;
  const fillNamespace = options.fillNamespace !== false;
  const createHeader = page.getByRole("heading", { name: "Create a new Vocabulary", exact: true });

  if (!(await createHeader.isVisible())) {
    return null;
  }

  const resolvedCreationUri = normalizeText(
    await page.locator("#inputVocabUri").inputValue().catch(() => runtime.creationUri || ""),
  );
  const resolvedCreationNamespace = normalizeText(
    await page.locator("#inputVocabNsp").inputValue().catch(() => runtime.creationNamespace || ""),
  );

  if (fillUri && normalizeText(runtime.creationUri)) {
    await fillMarked(page.locator("#inputVocabUri"), runtime.creationUri);
  }
  if (fillNamespace && normalizeText(runtime.creationNamespace)) {
    await fillMarked(page.locator("#inputVocabNsp"), runtime.creationNamespace);
  }
  if (normalizeText(runtime.creationPrefix)) {
    await fillMarked(page.locator("#inputVocabPrefix"), runtime.creationPrefix);
  }

  if ((await page.locator("textarea[name^='titles']").count()) === 0) {
    await clickMarked(page.locator(".fieldWithLangAddActionTitle"));
  }
  if ((await page.locator("textarea[name^='titles']").count()) < 2) {
    await clickMarked(page.locator(".fieldWithLangAddActionTitle"));
  }
  const titleFields = page.locator("textarea[name^='titles']");
  await fillMarked(titleFields.first(), runtime.creationTitle);
  if ((await titleFields.count()) > 1) {
    await fillMarked(titleFields.nth(1), `${runtime.creationTitle} ES`);
  }
  await ensureTextareaLanguages(
    page,
    "titles",
    runtime.creationPrimaryLanguage,
    runtime.creationSecondaryLanguage,
  );

  if ((await page.locator("textarea[name^='descriptions']").count()) === 0) {
    await clickMarked(page.locator(".fieldWithLangAddActionDescription"));
  }
  if ((await page.locator("textarea[name^='descriptions']").count()) < 2) {
    await clickMarked(page.locator(".fieldWithLangAddActionDescription"));
  }
  const descriptionFields = page.locator("textarea[name^='descriptions']");
  await fillMarked(descriptionFields.first(), runtime.creationDescription);
  if ((await descriptionFields.count()) > 1) {
    await fillMarked(descriptionFields.nth(1), `${runtime.creationDescription} ES`);
  }
  await ensureTextareaLanguages(
    page,
    "descriptions",
    runtime.creationPrimaryLanguage,
    runtime.creationSecondaryLanguage,
  );

  if ((await page.locator("#tagsUl input[name='tags[]']").count()) === 0) {
    await ensureVocabularyTag(page, runtime);
  }

  if ((await page.locator("textarea[name^='reviews']").count()) === 0) {
    await clickMarked(page.locator(".fieldReviewAddAction"));
  }
  await fillMarked(page.locator("textarea[name^='reviews']").first(), runtime.creationReview);

  return {
    creationUri: resolvedCreationUri || normalizeText(runtime.creationUri),
    creationNamespace: resolvedCreationNamespace || normalizeText(runtime.creationNamespace),
  };
}

async function createVocabularyFromUri(page, runtime) {
  await openCreateVocabularyDialog(page, runtime);
  await page.getByText("Create Vocabulary by URI", { exact: true }).waitFor({ state: "visible" });
  await fillMarked(page.locator("#formDialogCreateVocabFromURI input[name='uri']"), runtime.creationUri);
  await clickMarked(page.getByRole("button", { name: "Confirm", exact: true }));
  await page.waitForLoadState("domcontentloaded");

  const duplicateError = page.locator(".alert-error").filter({
    hasText: "This vocabulary already exists",
  });
  const metadataContext = await fillVocabularyMetadataForm(page, runtime, {
    fillUri: true,
    fillNamespace: true,
  });

  if (metadataContext) {
    const saveOutcome = await submitVocabularyMetadata(page, runtime);
    if (saveOutcome.created) {
      return {
        ...saveOutcome,
        ...metadataContext,
        method: "uri",
      };
    }

    if (saveOutcome.duplicateByPrefix) {
      return {
        ...saveOutcome,
        ...metadataContext,
        method: "uri",
      };
    }

    throw new Error(
      `No se pudo guardar el vocabulario '${runtime.creationPrefix}' en Ontology Hub. ${
        saveOutcome.errorMessage || "No se recibio confirmacion valida del guardado."
      }`,
    );
  }

  await duplicateError.waitFor({ state: "visible", timeout: readyTimeoutMs });
  return {
    created: false,
    duplicateByPrefix: true,
    duplicateByUri: true,
    url: page.url(),
    method: "uri",
  };
}

async function createVocabularyFromRepository(page, runtime) {
  const repositoryUri = normalizeRepositoryUri(runtime.creationRepositoryUri);
  await openCreateVocabularyDialog(page, runtime);
  await page.getByText("Create Vocabulary from Ontology Repository", { exact: true }).waitFor({
    state: "visible",
  });
  await fillMarked(page
    .locator("#formDialogCreateVocabFromOntologyDevelopmentRepository input[name='repositoryUri']"), repositoryUri);
  await clickMarked(page.getByRole("button", { name: "Confirm", exact: true }));
  await page.waitForLoadState("domcontentloaded");

  const metadataContext = await fillVocabularyMetadataForm(page, runtime, {
    fillUri: false,
    fillNamespace: false,
  });
  if (metadataContext) {
    const saveOutcome = await submitVocabularyMetadata(page, runtime);
    return {
      ...saveOutcome,
      ...metadataContext,
      repositoryUri,
      method: "repository",
    };
  }

  const visibleError = normalizeText(
    await page.locator(".alert-error, #formErrors, #dialogCreateVocabError").first().textContent().catch(() => ""),
  );
  if (visibleError) {
    return {
      created: false,
      duplicateByPrefix: /prefix .* already used/i.test(visibleError),
      duplicateByUri: /already exists/i.test(visibleError),
      repositoryAccessFailed: isRepositoryAccessError(visibleError),
      url: page.url(),
      errorMessage: visibleError,
      repositoryUri,
      method: "repository",
    };
  }

  throw new Error(
    `No se pudo crear un vocabulario desde el repositorio '${repositoryUri}'. ` +
      "Ontology Hub no mostro el formulario de creacion esperado ni un error visible.",
  );
}

async function resolveExistingVocabularyContext(page, runtime, prefix, title, options = {}) {
  const includeFallbackExpected = options.includeFallbackExpected !== false;
  const candidates = [];
  const seen = new Set();
  const requestedPrefix = normalizeText(prefix).toLowerCase();

  function addCandidate(candidatePrefix, candidateTitle) {
    const normalizedPrefix = normalizeText(candidatePrefix);
    if (!normalizedPrefix || seen.has(normalizedPrefix)) {
      return;
    }
    seen.add(normalizedPrefix);
    candidates.push({
      prefix: normalizedPrefix,
      title: normalizeText(candidateTitle) || normalizeText(title),
    });
  }

  addCandidate(prefix, title);
  if (includeFallbackExpected) {
    addCandidate(runtime.expectedVocabularyPrefix, runtime.expectedVocabularyTitle);
    addCandidate(runtime.listingSearchTerm, runtime.expectedVocabularyTitle);
  }

  for (const candidate of candidates) {
    const detailProbe = await probeVocabularyDetail(page.request, runtime, candidate.prefix, {
      refresh: true,
    });
    if (detailProbe.available) {
      return candidate;
    }
  }

  const catalogQueries = [
    title,
    runtime.creationTitle,
    runtime.expectedVocabularyTitle,
    runtime.listingSearchTerm,
  ]
    .map((value) => normalizeText(value))
    .filter(Boolean);

  for (const query of catalogQueries) {
    const response = await page.request
      .get(`${runtime.baseUrl}/dataset/vocabs?q=${encodeURIComponent(query)}`)
      .catch(() => null);
    if (!response || !response.ok()) {
      continue;
    }

    const body = await response.text().catch(() => "");
    const matches = body.matchAll(/\/dataset\/vocabs\/([^"'?#/<>\s]+)/g);
    for (const match of matches) {
      const candidatePrefix = normalizeText(match[1]);
      if (!/^[a-z0-9][a-z0-9._:-]*$/i.test(candidatePrefix)) {
        continue;
      }
      addCandidate(candidatePrefix, title);
    }
  }

  candidates.sort((left, right) => {
    const leftPrefix = normalizeText(left.prefix).toLowerCase();
    const rightPrefix = normalizeText(right.prefix).toLowerCase();

    const score = (candidatePrefix) => {
      if (!requestedPrefix) {
        return 0;
      }
      if (candidatePrefix === requestedPrefix) {
        return 0;
      }
      if (candidatePrefix.startsWith(requestedPrefix)) {
        return 1;
      }
      if (candidatePrefix.includes(requestedPrefix)) {
        return 2;
      }
      return 3;
    };

    const scoreDelta = score(leftPrefix) - score(rightPrefix);
    if (scoreDelta !== 0) {
      return scoreDelta;
    }
    return leftPrefix.localeCompare(rightPrefix);
  });

  for (const candidate of candidates) {
    const detailProbe = await probeVocabularyDetail(page.request, runtime, candidate.prefix, {
      refresh: true,
    });
    if (detailProbe.available) {
      return candidate;
    }
  }

  return null;
}

async function gatherBootstrapCapabilities(page, runtime, context, options = {}) {
  const detailProbe = await probeVocabularyDetail(page.request, runtime, context.prefix, options);
  const termsProbe = await probeTermsPage(page.request, runtime);
  const autocompleteProbe = await probeVocabularyAutocomplete(page.request, {
    ...runtime,
    expectedVocabularyPrefix: context.prefix,
    expectedVocabularyTitle: context.title,
    listingSearchTerm: context.prefix,
  }, options);
  const termApiProbe = await probeTermSearchApi(page.request, {
    ...runtime,
    expectedVocabularyPrefix: context.prefix,
    expectedVocabularyTitle: context.title,
  }, options);

  return {
    publicVocabularyDetail: detailProbe.available,
    publicVocabularyDetailReason: detailProbe.reason || "",
    publicVocabularyVersionHistory: Boolean(detailProbe.versionHistory),
    publicVocabularyStatistics: Boolean(detailProbe.statistics),
    publicTermsPage: termsProbe.available,
    publicTermsPageReason: termsProbe.reason || "",
    publicVocabularyAutocomplete: autocompleteProbe.available,
    publicVocabularyAutocompleteReason: autocompleteProbe.reason || "",
    publicTermSearchApi: termApiProbe.available,
    publicTermSearchApiReason: termApiProbe.reason || "",
    detailProbe,
    termsProbe,
    autocompleteProbe,
    termApiProbe,
  };
}

async function waitForBootstrapCapabilities(page, runtime, context) {
  let capabilities = await gatherBootstrapCapabilities(page, runtime, context);
  const maxAttempts = 10;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    if (
      capabilities.publicVocabularyDetail &&
      capabilities.publicVocabularyAutocomplete &&
      capabilities.publicTermSearchApi
    ) {
      return capabilities;
    }

    if (attempt < maxAttempts) {
      await page.waitForTimeout(2000);
      capabilities = await gatherBootstrapCapabilities(page, runtime, context, { refresh: true });
    }
  }

  return capabilities;
}

function isFrameworkManagedVocabulary(runtime, context, capabilities) {
  const managedPrefix = normalizeText(runtime.creationPrefix).toLowerCase();
  const expectedPrefix = normalizeText(runtime.expectedVocabularyPrefix).toLowerCase();
  const currentPrefix = normalizeText(context && context.prefix).toLowerCase();

  if (!managedPrefix || !currentPrefix) {
    return false;
  }

  if (currentPrefix !== managedPrefix || currentPrefix === expectedPrefix) {
    return false;
  }

  return Boolean(
    capabilities &&
      capabilities.publicVocabularyDetail &&
      capabilities.publicVocabularyVersionHistory &&
      capabilities.publicVocabularyStatistics,
  );
}

async function validatePersistedBootstrapContext(page, runtime, persisted) {
  if (!persisted || normalizeText(persisted.baseUrl) !== runtime.baseUrl) {
    return null;
  }

  const prefix = normalizeText(persisted.prefix);
  if (!prefix) {
    return null;
  }

  const title =
    normalizeText(persisted.title) ||
    normalizeText(runtime.creationTitle) ||
    normalizeText(runtime.expectedVocabularyTitle);
  const detailProbe = await probeVocabularyDetail(page.request, runtime, prefix, { refresh: true });
  if (!detailProbe.available) {
    return null;
  }

  const capabilities = await waitForBootstrapCapabilities(page, runtime, { prefix, title });
  const managedVocabulary = isFrameworkManagedVocabulary(runtime, { prefix, title }, capabilities);
  return {
    ...persisted,
    prefix,
    title,
    managedVocabulary,
    capabilities,
    workflow: {
      ...(persisted.workflow && typeof persisted.workflow === "object" ? persisted.workflow : {}),
      created:
        Boolean(
          persisted.workflow &&
            typeof persisted.workflow === "object" &&
            persisted.workflow.created,
        ) || managedVocabulary,
    },
  };
}

async function buildBootstrapContext(page, runtime) {
  const initialRuntime = runtime;
  let creationRuntime = runtime;
  let prefix = runtime.creationPrefix || runtime.expectedVocabularyPrefix;
  let title = runtime.creationTitle || runtime.expectedVocabularyTitle;
  let creationMethod = "uri";

  let outcome = {
    created: false,
    duplicateByPrefix: false,
    duplicateByUri: false,
    url: "",
  };
  let source = "existing";

  const publicDetailProbe = await probeVocabularyDetail(page.request, creationRuntime, prefix);
  if (!publicDetailProbe.available) {
    if (normalizeText(creationRuntime.creationUri)) {
      outcome = await createVocabularyFromUri(page, creationRuntime);
      creationMethod = outcome.method || "uri";
    } else if (normalizeText(creationRuntime.creationRepositoryUri)) {
      outcome = await createVocabularyFromRepository(page, creationRuntime);
      creationMethod = outcome.method || "repository";
    } else {
      throw new Error(
        "No hay configuracion de creacion disponible para Ontology Hub. " +
          "Define creationUri o creationRepositoryUri en la configuracion del chart.",
      );
    }
    source = outcome.created ? "created" : "reused";

    if (!outcome.created && outcome.duplicateByUri) {
      if (normalizeText(runtime.creationRepositoryUri)) {
        creationRuntime = buildRetryRuntime({
          ...runtime,
          creationUri: "",
        });
        prefix = creationRuntime.creationPrefix;
        title = creationRuntime.creationTitle || title;
        outcome = await createVocabularyFromRepository(page, creationRuntime);
        creationMethod = outcome.method || "repository";
        source = outcome.created ? "created" : "reused";
      }

      if (!outcome.created && outcome.repositoryAccessFailed) {
        const existingVocabulary = await resolveExistingVocabularyContext(
          page,
          initialRuntime,
          initialRuntime.expectedVocabularyPrefix || prefix,
          initialRuntime.expectedVocabularyTitle || title,
        );
        if (existingVocabulary) {
          creationRuntime = initialRuntime;
          prefix = existingVocabulary.prefix;
          title = existingVocabulary.title || title;
          source = "reused";
        } else {
          throw new Error(
            `Ontology Hub no pudo acceder al repositorio '${normalizeRepositoryUri(runtime.creationRepositoryUri)}', ` +
              "y tampoco se pudo resolver un vocabulario publico reutilizable para continuar el flujo.",
          );
        }
      }

      if (!outcome.created && outcome.duplicateByUri) {
        const existingVocabulary = await resolveExistingVocabularyContext(
          page,
          initialRuntime,
          initialRuntime.creationPrefix || initialRuntime.expectedVocabularyPrefix || prefix,
          initialRuntime.creationTitle || initialRuntime.expectedVocabularyTitle || title,
          { includeFallbackExpected: false },
        );
        if (existingVocabulary) {
          creationRuntime = {
            ...initialRuntime,
            creationUri: "",
          };
          prefix = existingVocabulary.prefix;
          title = existingVocabulary.title || title;
          outcome = {
            ...outcome,
            reusedExistingImport: true,
          };
        } else {
          throw new Error(
            `La URI '${creationRuntime.creationUri}' ya existe en Ontology Hub, ` +
              "pero no se pudo resolver el vocabulario publico reutilizable.",
          );
        }
      }
    } else if (!outcome.created && outcome.duplicateByPrefix) {
      try {
        await ensurePublicDetail(page, creationRuntime, prefix, title);
      } catch (error) {
        creationRuntime = buildRetryRuntime(runtime);
        prefix = creationRuntime.creationPrefix;
        if (creationMethod === "repository" && normalizeText(creationRuntime.creationRepositoryUri)) {
          outcome = await createVocabularyFromRepository(page, creationRuntime);
        } else {
          outcome = await createVocabularyFromUri(page, creationRuntime);
        }
        title = creationRuntime.creationTitle || title;
        creationMethod = outcome.method || creationMethod;
        source = outcome.created ? "created" : "reused";

        if (!outcome.created && outcome.duplicateByUri) {
          const existingVocabulary = await resolveExistingVocabularyContext(
            page,
            creationRuntime,
            prefix,
            title,
          );
          if (existingVocabulary) {
            prefix = existingVocabulary.prefix;
            title = existingVocabulary.title || title;
          }
        }
      }
    }
  }

  await ensurePublicDetail(page, creationRuntime, prefix, title);

  const capabilities = await waitForBootstrapCapabilities(page, creationRuntime, { prefix, title });
  const managedVocabulary = isFrameworkManagedVocabulary(
    creationRuntime,
    { prefix, title },
    capabilities,
  );
  return {
    prefix,
    title,
    source,
    creationMethod,
    creationUri: outcome.creationUri || creationRuntime.creationUri,
    creationRepositoryUri: normalizeRepositoryUri(creationRuntime.creationRepositoryUri),
    creationNamespace: outcome.creationNamespace || creationRuntime.creationNamespace,
    creationPrimaryLanguage: creationRuntime.creationPrimaryLanguage,
    creationSecondaryLanguage: creationRuntime.creationSecondaryLanguage,
    creationTag: creationRuntime.creationTag,
    creationOutcome: outcome,
    editUrl: `${creationRuntime.baseUrl}/edition/vocabs/${encodeURIComponent(prefix)}`,
    managedVocabulary,
    workflow: {
      created: source === "created" || managedVocabulary,
      editCompleted: false,
      edited: false,
    },
    capabilities,
  };
}

async function ensureOntologyHubBootstrap(page, runtime) {
  const cacheKey = runtime.baseUrl;
  const cached = bootstrapCache.get(cacheKey);
  if (cached) {
    return cached;
  }

  const filePath = stateFilePath();
  const persisted = readStateFile(filePath);
  if (persisted && persisted.prefix) {
    const validatedPersisted = await validatePersistedBootstrapContext(page, runtime, persisted);
    if (validatedPersisted) {
      bootstrapCache.set(cacheKey, validatedPersisted);
      return validatedPersisted;
    }
  }

  const promise = buildBootstrapContext(page, runtime).then((context) => {
    const persistedContext = {
      ...context,
      baseUrl: runtime.baseUrl,
      createdAt: new Date().toISOString(),
    };
    writeStateFile(filePath, persistedContext);
    return persistedContext;
  });

  bootstrapCache.set(cacheKey, promise);
  try {
    const resolved = await promise;
    bootstrapCache.set(cacheKey, resolved);
    return resolved;
  } catch (error) {
    bootstrapCache.delete(cacheKey);
    throw error;
  }
}

function updateOntologyHubBootstrapState(runtime, patch) {
  const cacheKey = runtime.baseUrl;
  const filePath = stateFilePath();
  const cached = bootstrapCache.get(cacheKey);
  const persisted = readStateFile(filePath);
  const current =
    cached && typeof cached === "object" && typeof cached.then !== "function"
      ? cached
      : persisted && typeof persisted === "object"
        ? persisted
        : {};
  const merged = mergeBootstrapState(current, patch);
  bootstrapCache.set(cacheKey, merged);
  writeStateFile(filePath, merged);
  return merged;
}

module.exports = {
  ensureOntologyHubBootstrap,
  gotoEdition,
  pageShowsTransientAvailabilityFailure,
  textShowsTransientAvailabilityFailure,
  updateOntologyHubBootstrapState,
};
