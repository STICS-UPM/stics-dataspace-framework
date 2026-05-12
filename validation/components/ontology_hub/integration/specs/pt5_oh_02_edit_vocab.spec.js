// Excel traceability: Ontology Hub case 10 (Editar Ontologia), partial coverage.
const { test } = require("../../ui/fixtures");
const {
  editVocabularyForWorkflow,
  editVocabularyForWorkflowHttp,
} = require("../../ui/support/flow-edit-vocab");
const { updateOntologyHubBootstrapState } = require("../../ui/support/bootstrap");

test.use({
  video: "off",
  trace: "off",
});

test("PT5-OH-02: vocabulary metadata can be edited through the edition flow", async ({
  page,
  request,
  ontologyHubRuntime,
  ontologyHubBootstrap,
}) => {
  const reusableImportedVocabulary =
    ontologyHubBootstrap.creationOutcome?.reusedExistingImport &&
    ontologyHubBootstrap.prefix !== ontologyHubRuntime.expectedVocabularyPrefix;
  const frameworkManagedVocabulary = Boolean(ontologyHubBootstrap.managedVocabulary);

  test.skip(
    ontologyHubBootstrap.source !== "created" &&
      !reusableImportedVocabulary &&
      !frameworkManagedVocabulary,
    "PT5-OH-02 requiere un vocabulario temporal propio, importado reutilizable o un fixture editable gestionado por el framework.",
  );

  const editOutcome = frameworkManagedVocabulary
    ? await editVocabularyForWorkflowHttp(request, ontologyHubRuntime, ontologyHubBootstrap)
    : await editVocabularyForWorkflow(page, ontologyHubRuntime, ontologyHubBootstrap);

  updateOntologyHubBootstrapState(ontologyHubRuntime, {
    workflow: {
      created: true,
      edited: true,
      editCompleted: true,
    },
    editOutcome,
  });

  if (!frameworkManagedVocabulary) {
    await page.goto("about:blank").catch(() => {});
  }
});
