// Excel traceability: Ontology Hub cases 10, 11, 12, 13 and 14.
const { test } = require("../../ui/fixtures");
const {
  createVersion,
  deleteRunState,
  deleteVersion,
  deleteVocabulary,
  downloadFirstN3,
  editVersion,
  loadRunState,
  openVocabularyDetail,
  openVersionsPage,
  REPOSITORY_VOCAB_STATE_KEY,
  runtimeFromCreatedVocabulary,
  saveRunState,
  signInToEdition,
  signOut,
  updateVocabularyMetadata,
  URI_VOCAB_STATE_KEY,
  VISUALIZATION_N3_STATE_KEY,
  VERSION_STATE_KEY,
} = require("../support/excel-flows");

function versionForCase(label, issued) {
  return {
    name: label,
    issued,
  };
}

const POST_VERSION_CRASH_RECOVERY_TIMEOUT_MS = 360000;
const POST_VERSION_CRASH_TEST_TIMEOUT_MS = POST_VERSION_CRASH_RECOVERY_TIMEOUT_MS + 60000;

function normalizeText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

async function waitForVocabularyDetailText(page, runtime, prefix, expectedTexts, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;
  let missing = [];

  while (Date.now() < deadline) {
    const bodyText = normalizeText(await page.locator("body").innerText().catch(() => ""));
    const normalizedBody = bodyText.toLowerCase();
    missing = expectedTexts.filter((text) => !normalizedBody.includes(normalizeText(text).toLowerCase()));
    if (missing.length === 0) {
      return;
    }

    await page.waitForTimeout(3000);
    await page
      .goto(`${runtime.baseUrl}/dataset/vocabs/${encodeURIComponent(prefix)}`, {
        waitUntil: "domcontentloaded",
      })
      .catch(() => {});
  }

  throw new Error(
    `Ontology Hub did not expose the updated vocabulary metadata after ${timeoutMs}ms. Missing text: ${missing.join(", ")}`,
  );
}

function resolveVersionSourceDownload() {
  try {
    const downloaded = loadRunState(VISUALIZATION_N3_STATE_KEY);
    const candidate = downloaded.persistedPath || downloaded.filePath || "";
    if (candidate) {
      return {
        ...downloaded,
        filePath: candidate,
        source: "oh-app-05",
      };
    }
  } catch (error) {
    // Fall back to an inline download to keep the suite runnable when OH-05 has not run.
  }

  return null;
}

test("OH-APP-10: edit ontology metadata and tags", async ({
  page,
  ontologyHubRuntime,
  captureStep,
  attachJson,
}) => {
  test.setTimeout(180000);
  const created = loadRunState(URI_VOCAB_STATE_KEY);
  const runtime = runtimeFromCreatedVocabulary(ontologyHubRuntime, created);
  const updatedReview = "ADMIN TEST";
  const updatedTag = "Vocabularies";

  await updateVocabularyMetadata(page, runtime, created.prefix, {
    review: updatedReview,
    tag: updatedTag,
  });
  await waitForVocabularyDetailText(page, runtime, created.prefix, [updatedTag, updatedReview]);
  await captureStep(page, "10-vocab-edited");
  await signOut(page, runtime);

  await attachJson("10-vocab-edit-report", {
    prefix: created.prefix,
    title: created.title,
    updatedReview,
    updatedTag,
  });
});

test("OH-APP-11: add a new ontology version", async ({
  page,
  ontologyHubRuntime,
  captureStep,
  attachJson,
}, testInfo) => {
  test.setTimeout(180000);
  const created = loadRunState(REPOSITORY_VOCAB_STATE_KEY);
  const runtime = runtimeFromCreatedVocabulary(ontologyHubRuntime, created);
  let downloadInfo = resolveVersionSourceDownload();
  if (!downloadInfo) {
    await openVocabularyDetail(page, runtime, created.prefix, created.title || "");
    downloadInfo = await downloadFirstN3(page, testInfo, "11-source-version", {
      strategy: "request",
    });
  }

  await signInToEdition(page, runtime);
  await openVersionsPage(page, runtime, created.prefix);
  const newVersion = versionForCase("1.0", "2026-03-31");
  await createVersion(page, newVersion, downloadInfo.filePath);
  await captureStep(page, "11-version-created");
  await signOut(page, runtime);
  saveRunState(VERSION_STATE_KEY, newVersion);

  await attachJson("11-version-create-report", {
    prefix: created.prefix,
    downloadInfo,
    newVersion,
  });
});

test("OH-APP-12: edit an ontology version", async ({
  page,
  ontologyHubRuntime,
  captureStep,
  attachJson,
}) => {
  test.setTimeout(180000);
  const created = loadRunState(REPOSITORY_VOCAB_STATE_KEY);
  const runtime = runtimeFromCreatedVocabulary(ontologyHubRuntime, created);
  const initialVersion = loadRunState(VERSION_STATE_KEY);
  await signInToEdition(page, runtime);
  await openVersionsPage(page, runtime, created.prefix);
  const updatedVersion = versionForCase("v2026-01-01", "2026-01-01");
  const editOutcome = await editVersion(page, runtime, created.prefix, initialVersion.name, updatedVersion);
  await captureStep(page, "12-version-edited");
  await signOut(page, runtime);
  saveRunState(VERSION_STATE_KEY, updatedVersion);

  await attachJson("12-version-edit-report", {
    prefix: created.prefix,
    initialVersion,
    updatedVersion,
    editOutcome,
  });
});

test("OH-APP-13: delete an ontology version", async ({
  page,
  ontologyHubRuntime,
  captureStep,
  attachJson,
}) => {
  test.setTimeout(POST_VERSION_CRASH_TEST_TIMEOUT_MS);
  const created = loadRunState(REPOSITORY_VOCAB_STATE_KEY);
  const runtime = runtimeFromCreatedVocabulary(ontologyHubRuntime, created);
  const version = loadRunState(VERSION_STATE_KEY);
  const fallbackVersion = versionForCase("v2026-01-01", "2026-01-01");
  const candidateVersions = [version, fallbackVersion].filter(
    (candidate, index, candidates) =>
      candidate && candidate.name && candidates.findIndex((other) => other.name === candidate.name) === index,
  );

  await signInToEdition(page, runtime, { recoveryTimeoutMs: POST_VERSION_CRASH_RECOVERY_TIMEOUT_MS });
  await openVersionsPage(page, runtime, created.prefix);
  let deletedVersion = null;
  let lastDeleteError = null;
  for (const candidateVersion of candidateVersions) {
    try {
      await deleteVersion(page, candidateVersion.name);
      deletedVersion = candidateVersion;
      break;
    } catch (error) {
      lastDeleteError = error;
    }
  }
  if (!deletedVersion) {
    throw new Error(
      `Could not delete any known version for '${created.prefix}'. ` +
        `Candidates: ${candidateVersions.map((candidate) => candidate.name).join(", ")}. ` +
        `Last error: ${lastDeleteError?.message || "none"}`,
    );
  }
  await captureStep(page, "13-version-deleted");
  await signOut(page, runtime);
  deleteRunState(VERSION_STATE_KEY);

  await attachJson("13-version-delete-report", {
    prefix: created.prefix,
    version,
    deletedVersion,
    candidateVersions,
  });
});

test("OH-APP-14: delete an ontology", async ({
  page,
  ontologyHubRuntime,
  captureStep,
  attachJson,
}) => {
  test.setTimeout(POST_VERSION_CRASH_TEST_TIMEOUT_MS);
  const created = loadRunState(REPOSITORY_VOCAB_STATE_KEY);
  const runtime = runtimeFromCreatedVocabulary(ontologyHubRuntime, created);
  await deleteVocabulary(page, runtime, created.prefix, {
    recoveryTimeoutMs: POST_VERSION_CRASH_RECOVERY_TIMEOUT_MS,
  });
  await captureStep(page, "14-vocabulary-deleted");
  await signOut(page, runtime);
  deleteRunState(REPOSITORY_VOCAB_STATE_KEY);

  await attachJson("14-vocabulary-delete-report", {
    prefix: created.prefix,
  });
});
