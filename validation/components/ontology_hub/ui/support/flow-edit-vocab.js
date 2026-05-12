const { OntologyHubVocabFormPage } = require("../pages/vocab-form.page");
const { gotoEdition } = require("./bootstrap");

function normalizeText(value) {
  return String(value || "").trim();
}

function escapeRegExp(value) {
  return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function formatDateYmd(date = new Date()) {
  return date.toISOString().slice(0, 10);
}

function extractInputValue(html, name) {
  const escapedName = escapeRegExp(name);
  const patterns = [
    new RegExp(`name=["']${escapedName}["'][^>]*value=["']([^"']*)["']`, "i"),
    new RegExp(`value=["']([^"']*)["'][^>]*name=["']${escapedName}["']`, "i"),
  ];
  for (const pattern of patterns) {
    const match = String(html || "").match(pattern);
    if (match && match[1] != null) {
      return normalizeText(match[1]);
    }
  }
  return "";
}

function extractAllInputValues(html, name) {
  const escapedName = escapeRegExp(name);
  const patterns = [
    new RegExp(`name=["']${escapedName}["'][^>]*value=["']([^"']*)["']`, "gi"),
    new RegExp(`value=["']([^"']*)["'][^>]*name=["']${escapedName}["']`, "gi"),
  ];
  const values = [];
  for (const pattern of patterns) {
    let match;
    while ((match = pattern.exec(String(html || ""))) !== null) {
      const value = normalizeText(match[1]);
      if (value && !values.includes(value)) {
        values.push(value);
      }
    }
  }
  return values;
}

async function publicDetailHasMarkers(page, prefix, title, reviewNeedle) {
  const bodyText = normalizeText(
    await page.locator("body").textContent().catch(() => ""),
  ).replace(/\s+/g, " ");
  const hasMetadata = bodyText.includes("Metadata");
  const hasPrefix = bodyText.includes(prefix);
  const hasTitle = !title || bodyText.includes(title);
  const hasReview = !reviewNeedle || bodyText.includes(reviewNeedle);

  return {
    ok: hasMetadata && hasPrefix && hasTitle && hasReview,
    bodyText: bodyText.slice(0, 320),
    hasMetadata,
    hasPrefix,
    hasTitle,
    hasReview,
  };
}

function publicDetailHasMarkersInHtml(html, prefix, title, reviewNeedle) {
  const bodyText = normalizeText(String(html || "")).replace(/\s+/g, " ");
  const hasMetadata = bodyText.includes("Metadata");
  const hasPrefix = bodyText.includes(prefix);
  const hasTitle = !title || bodyText.includes(title);
  const hasReview = !reviewNeedle || bodyText.includes(reviewNeedle);

  return {
    ok: hasMetadata && hasPrefix && hasTitle && hasReview,
    bodyText: bodyText.slice(0, 320),
    hasMetadata,
    hasPrefix,
    hasTitle,
    hasReview,
  };
}

async function loginEditionRequestContext(request, runtime) {
  const loginUrl = new URL("/edition/login", runtime.baseUrl).toString();
  const loginPageResponse = await request.get(loginUrl, {
    failOnStatusCode: false,
  });
  const loginPageBody = await loginPageResponse.text().catch(() => "");
  const csrfToken = extractInputValue(loginPageBody, "_csrf");
  if (!csrfToken) {
    throw new Error("No se pudo resolver el token CSRF del login de Ontology Hub.");
  }

  const sessionResponse = await request.post(new URL("/edition/session", runtime.baseUrl).toString(), {
    failOnStatusCode: false,
    form: {
      _csrf: csrfToken,
      email: runtime.adminEmail,
      password: runtime.adminPassword,
    },
  });
  const sessionBody = await sessionResponse.text().catch(() => "");
  if (
    sessionResponse.status() >= 400 ||
    /invalid email or password/i.test(sessionBody) ||
    /\/edition\/login\/?$/.test(sessionResponse.url())
  ) {
    throw new Error(
      `El login HTTP de Ontology Hub fue rechazado para '${runtime.adminEmail}'.`,
    );
  }
}

async function editVocabularyForWorkflowHttp(request, runtime, bootstrapContext) {
  const prefix = normalizeText(bootstrapContext.prefix);
  if (!prefix) {
    throw new Error("No hay un vocabulario bootstrap valido para editar.");
  }

  await loginEditionRequestContext(request, runtime);

  const editUrl = new URL(`/edition/vocabs/${encodeURIComponent(prefix)}`, runtime.baseUrl).toString();
  const editResponse = await request.get(editUrl, {
    failOnStatusCode: false,
  });
  const editHtml = await editResponse.text().catch(() => "");
  if (editResponse.status() >= 400 || /<h1>\s*Log in\s*<\/h1>/i.test(editHtml)) {
    throw new Error(`No se pudo abrir por HTTP el formulario de edicion para '${prefix}'.`);
  }

  const primaryLanguage = bootstrapContext.creationPrimaryLanguage || runtime.creationPrimaryLanguage || "en";
  const secondaryLanguage =
    bootstrapContext.creationSecondaryLanguage || runtime.creationSecondaryLanguage || "es";
  const title = bootstrapContext.title || runtime.creationTitle || prefix;
  const description = runtime.creationDescription || "Vocabulary edited through the Ontology Hub workflow.";
  const reviewText =
    `${runtime.creationReview || "Validated through the Playwright ontology flow."} ` +
    `[edit:${new Date().toISOString()}]`;

  const csrfToken = extractInputValue(editHtml, "_csrf");
  if (!csrfToken) {
    throw new Error(`No se pudo resolver el token CSRF del formulario de edicion para '${prefix}'.`);
  }

  const creatorIds = extractAllInputValues(editHtml, "creatorIds[]");
  const contributorIds = extractAllInputValues(editHtml, "contributorIds[]");
  const publisherIds = extractAllInputValues(editHtml, "publisherIds[]");
  const tags = extractAllInputValues(editHtml, "tags[]");
  const reviewAgentId = extractInputValue(editHtml, "reviews[0].agentId") || "000000000000000000000000";
  const reviewCreatedAt = extractInputValue(editHtml, "reviews[0].createdAt") || formatDateYmd();
  const optionalFields = [
    "ontologyPath",
    "requirements",
    "conceptualization",
    "shapes",
    "examples",
    "tests",
    "repositoryUri",
  ];
  const payload = {
    _csrf: csrfToken,
    _method: "PUT",
    lastModifiedInLOVAt: formatDateYmd(),
    uri: runtime.creationUri || bootstrapContext.creationUri || "",
    isDefinedBy: runtime.creationNamespace || bootstrapContext.creationNamespace || "",
    nsp: runtime.creationNamespace || bootstrapContext.creationNamespace || "",
    prefix,
    titles: [
      { value: title, lang: primaryLanguage },
      { value: `${title} ES`, lang: secondaryLanguage },
    ],
    descriptions: [
      { value: description, lang: primaryLanguage },
      { value: `${description} ES`, lang: secondaryLanguage },
    ],
    issuedAt: runtime.previousVersionDate || formatDateYmd(),
    homepage: runtime.creationNamespace || bootstrapContext.creationNamespace || "",
    creatorIds,
    contributorIds,
    publisherIds,
    tags: tags.length > 0 ? tags : [runtime.creationTag || bootstrapContext.creationTag].filter(Boolean),
    reviews: [
      {
        body: reviewText,
        agentId: reviewAgentId,
        createdAt: reviewCreatedAt,
      },
    ],
  };

  for (const field of optionalFields) {
    const value = extractInputValue(editHtml, field);
    if (value) {
      payload[field] = value;
    }
  }

  const saveResponse = await request.post(editUrl, {
    failOnStatusCode: false,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
    },
    data: JSON.stringify(payload),
  });
  const saveBody = await saveResponse.text().catch(() => "");
  let savePayload = null;
  try {
    savePayload = saveBody ? JSON.parse(saveBody) : null;
  } catch (error) {
    savePayload = null;
  }

  if (saveResponse.status() >= 400) {
    throw new Error(
      `La edicion HTTP del vocabulario '${prefix}' devolvio HTTP ${saveResponse.status()}. ${
        normalizeText(saveBody).slice(0, 240)
      }`,
    );
  }

  const publicUrl = new URL(
    (savePayload && savePayload.redirect) || `/dataset/vocabs/${prefix}`,
    runtime.baseUrl,
  ).toString();
  const detailResponse = await request.get(publicUrl, {
    failOnStatusCode: false,
  });
  const detailHtml = await detailResponse.text().catch(() => "");
  const reviewNeedle = normalizeText(reviewText).split("[edit:")[0].trim();
  const detailCheck = publicDetailHasMarkersInHtml(detailHtml, prefix, title, reviewNeedle);

  return {
    edited: true,
    prefix,
    title,
    publicUrl,
    titleLanguages: [primaryLanguage, secondaryLanguage],
    descriptionLanguages: [primaryLanguage, secondaryLanguage],
    reviewText,
    saveOutcome: {
      redirected: Boolean(savePayload && savePayload.redirect),
      responseStatus: saveResponse.status(),
      responseBody: saveBody,
      redirectTarget: normalizeText(savePayload && savePayload.redirect),
      finalUrl: publicUrl,
    },
    detailCheck,
  };
}

async function editVocabularyForWorkflow(page, runtime, bootstrapContext) {
  const prefix = normalizeText(bootstrapContext.prefix);
  if (!prefix) {
    throw new Error("No hay un vocabulario bootstrap valido para editar.");
  }

  await gotoEdition(page, runtime);

  const formPage = new OntologyHubVocabFormPage(page);
  await formPage.gotoEdit(runtime.baseUrl, prefix);
  await formPage.expectReady(prefix);

  const primaryLanguage = bootstrapContext.creationPrimaryLanguage || runtime.creationPrimaryLanguage || "en";
  const secondaryLanguage =
    bootstrapContext.creationSecondaryLanguage || runtime.creationSecondaryLanguage || "es";
  const title = bootstrapContext.title || runtime.creationTitle || prefix;
  const description = runtime.creationDescription || "Vocabulary edited through the Ontology Hub workflow.";
  const managedVocabulary = Boolean(bootstrapContext.managedVocabulary);
  const reviewText =
    `${runtime.creationReview || "Validated through the Playwright ontology flow."} ` +
    `[edit:${new Date().toISOString()}]`;

  if (!managedVocabulary) {
    await formPage.ensureTitles(
      primaryLanguage,
      secondaryLanguage,
      title,
      `${title} ES`,
    );
    await formPage.ensureDescriptions(
      primaryLanguage,
      secondaryLanguage,
      description,
      `${description} ES`,
    );
  }
  await formPage.setReview(reviewText);

  const titleLanguages = await formPage.currentTitleLanguages();
  const descriptionLanguages = await formPage.currentDescriptionLanguages();
  const saveOutcome = await formPage.save();
  const formErrors = await formPage.readFormErrors();

  if (formErrors) {
    throw new Error(`La edicion del vocabulario '${prefix}' mostro errores: ${formErrors}`);
  }
  if (saveOutcome.responseStatus && saveOutcome.responseStatus >= 400) {
    throw new Error(
      `La edicion del vocabulario '${prefix}' devolvio HTTP ${saveOutcome.responseStatus}. ${
        normalizeText(saveOutcome.responseBody).slice(0, 240)
      }`,
    );
  }
  if (!saveOutcome.redirected && !/\/dataset\/vocabs\/[^/]+\/?$/.test(saveOutcome.finalUrl)) {
    throw new Error(
      `La edicion del vocabulario '${prefix}' no redirigio a la vista publica esperada. URL final: ${saveOutcome.finalUrl}`,
    );
  }

  const publicUrl = /\/dataset\/vocabs\/[^/]+\/?$/.test(saveOutcome.finalUrl)
    ? saveOutcome.finalUrl
    : new URL(saveOutcome.redirectTarget || `/dataset/vocabs/${prefix}`, runtime.baseUrl).toString();

  const reviewNeedle = normalizeText(reviewText).split("[edit:")[0].trim();
  if (!page.isClosed() && page.url() !== publicUrl) {
    await page.goto(publicUrl, {
      waitUntil: "domcontentloaded",
    });
  }

  let detail = "";
  let lastDetailState = null;
  for (let attempt = 1; attempt <= 6; attempt += 1) {
    const currentUrl = page.url();
    if (currentUrl !== publicUrl && !page.isClosed()) {
      await page.goto(publicUrl, {
        waitUntil: "domcontentloaded",
      });
    }

    const detailState = await publicDetailHasMarkers(page, prefix, title, reviewNeedle);
    lastDetailState = detailState;
    detail = detailState.bodyText;
    if (detailState.ok) {
      return {
        edited: true,
        prefix,
        title,
        publicUrl,
        titleLanguages,
        descriptionLanguages,
        reviewText,
        saveOutcome,
        detailCheck: detailState,
      };
    }

    if (attempt < 6 && !page.isClosed()) {
      await page.waitForTimeout(1500);
    }
  }

  return {
    edited: true,
    prefix,
    title,
    publicUrl,
    titleLanguages,
    descriptionLanguages,
    reviewText,
    saveOutcome,
    detailCheck:
      lastDetailState || {
        ok: false,
        bodyText: detail,
        hasMetadata: false,
        hasPrefix: false,
        hasTitle: false,
        hasReview: false,
      },
  };
}

module.exports = {
  editVocabularyForWorkflow,
  editVocabularyForWorkflowHttp,
};
