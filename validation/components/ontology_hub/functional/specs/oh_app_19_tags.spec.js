// Excel traceability: Ontology Hub cases 19, 20 and 21.
const { test } = require("../../ui/fixtures");
const { createTag, deleteTag, editTag, signOut } = require("../support/excel-flows");

function buildTagNames(testInfo) {
  const suffix = `${Date.now().toString(36)}-${String(testInfo.parallelIndex || 0)}`.slice(-10);
  const safeSuffix = suffix.replace(/[^a-z0-9-]/g, "");
  return {
    initial: `MiTag-${safeSuffix}`,
    updated: `MiTagPrueba-${safeSuffix}`,
  };
}

test("OH-APP-19: create tag", async ({
  page,
  ontologyHubRuntime,
  captureStep,
  attachJson,
}, testInfo) => {
  const tags = buildTagNames(testInfo);
  await createTag(page, ontologyHubRuntime, tags.initial);
  await captureStep(page, "19-tag-created");
  await signOut(page, ontologyHubRuntime);

  await attachJson("19-create-tag-report", {
    label: tags.initial,
  });
});

test("OH-APP-20: edit tag", async ({
  page,
  ontologyHubRuntime,
  captureStep,
  attachJson,
}, testInfo) => {
  const tags = buildTagNames(testInfo);
  await createTag(page, ontologyHubRuntime, tags.initial);
  await editTag(page, ontologyHubRuntime, tags.initial, tags.updated);
  await captureStep(page, "20-tag-edited");
  await signOut(page, ontologyHubRuntime);

  await attachJson("20-edit-tag-report", {
    initial: tags.initial,
    updated: tags.updated,
  });
});

test("OH-APP-21: delete tag", async ({
  page,
  ontologyHubRuntime,
  captureStep,
  attachJson,
}, testInfo) => {
  const tags = buildTagNames(testInfo);
  await createTag(page, ontologyHubRuntime, tags.updated);
  await deleteTag(page, ontologyHubRuntime, tags.updated);
  await captureStep(page, "21-tag-deleted");
  await signOut(page, ontologyHubRuntime);

  await attachJson("21-delete-tag-report", {
    deleted: tags.updated,
  });
});
