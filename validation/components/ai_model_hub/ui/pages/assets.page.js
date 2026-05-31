const { expect } = require("../fixtures");
const { checkMarked, clickMarked, fillMarked, selectOptionMarked } = require("../support/live-marker");
const { gotoDashboardRoute } = require("./navigation");

class AssetCreateDialog {
  constructor(page) {
    this.page = page;
    this.root = page.locator("lib-asset-create");
    this.idInput = this.root.locator("input[name='id']");
    this.nameInput = this.root.locator("input[placeholder='Name']");
    this.contentTypeInput = this.root.locator("input[name='contenttype']");
    this.dataTypeSelect = this.root.locator("select[name='dataType']");
    this.baseUrlInput = this.root.locator("input[name='baseUrl']");
    this.enableMlMetadataToggle = this.root.locator("input[formcontrolname='mlEnabled']");
    this.mlDescriptionTextarea = this.root.locator("textarea[formcontrolname='mlDescription']");
    this.mlVersionInput = this.root.locator("input[formcontrolname='mlVersion']");
    this.mlAssetKindSelect = this.root.locator("select[formcontrolname='mlAssetKind']");
    this.mlTaskSelect = this.root.locator("select[formcontrolname='mlTask']");
    this.mlLicenseSelect = this.root.locator("select[formcontrolname='mlLicense']");
    this.mlMaturitySelect = this.root.locator("select[formcontrolname='mlMaturity']");
    this.mlArchitectureInput = this.root.locator("input[formcontrolname='mlArchitecture']");
    this.mlBaseModelInput = this.root.locator("input[formcontrolname='mlBaseModel']");
    this.mlParameterCountInput = this.root.locator("input[formcontrolname='mlParameterCount']");
    this.mlArtifactSizeInput = this.root.locator("input[formcontrolname='mlArtifactSize']");
    this.mlQuantizationSelect = this.root.locator("select[formcontrolname='mlQuantization']");
    this.mlPerformanceMetricSelect = this.root.locator("select[formcontrolname='mlPerformanceMetric']");
    this.mlPerformanceDatasetSelect = this.root.locator("select[formcontrolname='mlPerformanceDataset']");
    this.mlPerformanceReportInput = this.root.locator("input[formcontrolname='mlPerformanceReport']");
    this.mlFormatSelect = this.root.locator("select[formcontrolname='mlFormat']");
    this.mlInferencePathSelect = this.root.locator("select[formcontrolname='mlInferencePath']");
    this.mlInputSchemaDraftSelect = this.root.locator("select[formcontrolname='mlInputSchemaDraft']");
    this.mlInputSchemaTextarea = this.root.locator("textarea[formcontrolname='mlInputSchema']");
    this.mlInputExampleTextarea = this.root.locator("textarea[formcontrolname='mlInputExample']");
    this.mlIntendedUseTextarea = this.root.locator("textarea[formcontrolname='mlIntendedUse']");
    this.mlLimitationsTextarea = this.root.locator("textarea[formcontrolname='mlLimitations']");
    this.mlPiiSafeCheckbox = this.root.locator("input[formcontrolname='mlPiiSafe']");
    this.mlRegulatedDomainCheckbox = this.root.locator("input[formcontrolname='mlRegulatedDomain']");
    this.mlHumanInLoopCheckbox = this.root.locator("input[formcontrolname='mlHumanInLoop']");
    this.mlLatencyP95Input = this.root.locator("input[formcontrolname='mlLatencyP95']");
    this.mlThroughputInput = this.root.locator("input[formcontrolname='mlThroughput']");
    this.mlRateLimitsInput = this.root.locator("input[formcontrolname='mlRateLimits']");
    this.mlAvailabilityTierSelect = this.root.locator("select[formcontrolname='mlAvailabilityTier']");
    this.advancedFields = this.root.locator("details").filter({ hasText: /Advanced Fields/i }).first();
    this.propertiesEditor = this.root.locator("lib-json-object-input").first();
    this.propertyKeyInput = this.propertiesEditor.locator("input[placeholder='Key']");
    this.propertyValueInput = this.propertiesEditor.locator("input[placeholder='Value']");
    this.propertyAddButton = this.propertiesEditor.locator("button").filter({ hasText: /^Add$/i }).first();
    this.createAssetButton = this.root.locator("button").filter({ hasText: /Create Asset/i }).first();
    this.errorLabel = this.root.locator(".text-error");
  }

  async waitUntilReady() {
    await expect(this.root).toBeVisible();
    await expect(this.dataTypeSelect).toBeVisible();
  }

  async fillCommonFields({ id, name, contentType }) {
    if (id) {
      await fillMarked(this.idInput, id);
    }
    if (name) {
      await fillMarked(this.nameInput, name);
    }
    if (contentType) {
      await fillMarked(this.contentTypeInput, contentType);
    }
  }

  async selectFirstDataType() {
    const options = await this.dataTypeSelect.locator("option").allTextContents();
    const normalizedOptions = options.map((option) => option.trim());
    if (normalizedOptions.includes("HttpData")) {
      await selectOptionMarked(this.dataTypeSelect, { label: "HttpData" });
    } else {
      await selectOptionMarked(this.dataTypeSelect, { index: 0 });
    }
    await expect(this.baseUrlInput).toBeVisible();
  }

  async fillBaseUrl(baseUrl) {
    await fillMarked(this.baseUrlInput, baseUrl);
  }

  async enableMlMetadataHelper() {
    await checkMarked(this.enableMlMetadataToggle, { force: true });
    await expect(this.mlDescriptionTextarea).toBeVisible();
    await expect(this.mlVersionInput).toBeVisible();
  }

  async fillMlMetadata({ description, version, assetKind, task }) {
    if (description) {
      await fillMarked(this.mlDescriptionTextarea, description);
    }
    if (version) {
      await fillMarked(this.mlVersionInput, version);
    }
    if (assetKind) {
      await selectOptionMarked(this.mlAssetKindSelect, assetKind);
    }
    if (task) {
      await selectOptionMarked(this.mlTaskSelect, task);
    }
  }

  async fillAdvancedMlMetadata({
    modalities = [],
    keywords = [],
    license,
    maturity,
    runtimes = [],
    languages = [],
    architecture,
    baseModel,
    parameterCount,
    artifactSize,
    quantization,
    performanceMetric,
    performanceDataset,
    performanceReport,
    format,
    inferencePath,
    inputSchemaDraft,
    inputSchema,
    inputExample,
    intendedUse,
    limitations,
    piiSafe,
    regulatedDomain,
    humanInLoop,
    latencyP95,
    throughput,
    rateLimits,
    availabilityTier,
  }) {
    const filledControls = {
      advancedFields: false,
      piiSafe: false,
      regulatedDomain: false,
      humanInLoop: false,
    };

    for (const modality of modalities) {
      await this.checkMlOption(modality);
    }
    for (const keyword of keywords) {
      await this.checkMlOption(keyword);
    }
    await this.selectIfVisible(this.mlLicenseSelect, license);
    await this.selectIfVisible(this.mlMaturitySelect, maturity);

    const hasAdvancedFields = await this.openAdvancedFields();
    if (!hasAdvancedFields) {
      return filledControls;
    }
    filledControls.advancedFields = true;

    for (const runtime of runtimes) {
      await this.checkMlOption(runtime);
    }
    for (const language of languages) {
      await this.checkMlOption(language);
    }
    await this.fillIfVisible(this.mlArchitectureInput, architecture);
    await this.fillIfVisible(this.mlBaseModelInput, baseModel);
    await this.fillIfVisible(this.mlParameterCountInput, parameterCount);
    await this.fillIfVisible(this.mlArtifactSizeInput, artifactSize);
    await this.selectIfVisible(this.mlQuantizationSelect, quantization);
    await this.selectIfVisible(this.mlPerformanceMetricSelect, performanceMetric);
    await this.selectIfVisible(this.mlPerformanceDatasetSelect, performanceDataset);
    await this.fillIfVisible(this.mlPerformanceReportInput, performanceReport);
    await this.selectIfVisible(this.mlFormatSelect, format);
    await this.selectIfVisible(this.mlInferencePathSelect, inferencePath);
    await this.selectIfVisible(this.mlInputSchemaDraftSelect, inputSchemaDraft);
    await this.fillJsonIfVisible(this.mlInputSchemaTextarea, inputSchema);
    await this.fillJsonIfVisible(this.mlInputExampleTextarea, inputExample);
    await this.fillIfVisible(this.mlIntendedUseTextarea, intendedUse);
    await this.fillIfVisible(this.mlLimitationsTextarea, limitations);
    filledControls.piiSafe = await this.checkIfRequested(this.mlPiiSafeCheckbox, piiSafe);
    filledControls.regulatedDomain = await this.checkIfRequested(this.mlRegulatedDomainCheckbox, regulatedDomain);
    filledControls.humanInLoop = await this.checkIfRequested(this.mlHumanInLoopCheckbox, humanInLoop);
    await this.fillIfVisible(this.mlLatencyP95Input, latencyP95);
    await this.fillIfVisible(this.mlThroughputInput, throughput);
    await this.fillIfVisible(this.mlRateLimitsInput, rateLimits);
    await this.selectIfVisible(this.mlAvailabilityTierSelect, availabilityTier);

    return filledControls;
  }

  async openAdvancedFields() {
    if ((await this.advancedFields.count()) === 0) {
      return false;
    }
    const isOpen = await this.advancedFields.evaluate((element) => element.open).catch(() => false);
    if (!isOpen) {
      await clickMarked(this.advancedFields.locator("summary").first());
    }
    return true;
  }

  async checkMlOption(label) {
    const optionLabel = this.root
      .locator("label")
      .filter({ hasText: new RegExp(`^\\s*${escapeRegExp(label)}\\s*$`, "i") })
      .first();
    if ((await optionLabel.count()) === 0) {
      await optionLabel.waitFor({ state: "attached", timeout: 1500 }).catch(() => undefined);
    }
    const checkbox = optionLabel.locator("input[type='checkbox']").first();
    if ((await checkbox.count()) === 0) {
      return;
    }
    await checkMarked(checkbox, { force: true });
  }

  async fillIfVisible(locator, value) {
    if (value === undefined || value === null || value === "") {
      return;
    }
    if ((await locator.count()) === 0) {
      return;
    }
    await fillMarked(locator.first(), String(value));
  }

  async fillJsonIfVisible(locator, value) {
    if (value === undefined || value === null || value === "") {
      return;
    }
    const serialized = typeof value === "string" ? value : JSON.stringify(value, null, 2);
    await this.fillIfVisible(locator, serialized);
  }

  async selectIfVisible(locator, value) {
    if (value === undefined || value === null || value === "") {
      return;
    }
    if ((await locator.count()) === 0) {
      return;
    }
    await selectOptionMarked(locator.first(), value);
  }

  async checkIfRequested(locator, enabled) {
    if (!enabled || (await locator.count()) === 0) {
      return false;
    }
    await checkMarked(locator.first(), { force: true });
    return true;
  }

  async addProperty(key, value) {
    await fillMarked(this.propertyKeyInput, key);
    await fillMarked(this.propertyValueInput, value);
    await clickMarked(this.propertyAddButton);
    await expect(this.propertyKeyInput).toHaveValue("");
    await expect(this.propertyValueInput).toHaveValue("");
  }

  async submit() {
    await clickMarked(this.createAssetButton);
  }
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

class AssetsPage {
  constructor(page, runtime) {
    this.page = page;
    this.runtime = runtime;
    this.searchInput = page.locator("lib-filter-input input");
    this.createButtons = page.locator("#router-content button").filter({ hasText: /Create/i });
    this.assetCards = page.locator("lib-asset-card");
    this.successAlert = page.locator(".alert-success");
    this.errorAlert = page.locator(".alert-error");
    this.connectorDropdownButton = page
      .locator(".navbar-center [role='button']")
      .filter({ hasText: /Provider|Consumer/i })
      .first();
  }

  async goto() {
    await gotoDashboardRoute(this.page, this.runtime, this.runtime.assetsPath, "Assets");
  }

  async waitUntilReady() {
    await expect(this.searchInput).toBeVisible();
    await expect(this.createButtons.first()).toBeVisible();
  }

  async switchToConnector(connectorName) {
    await clickMarked(this.connectorDropdownButton);
    const option = this.page.locator(
      `input[name='edc-config-dropdown'][aria-label='${connectorName}']`,
    );
    await clickMarked(option, { force: true });
    await expect(this.connectorDropdownButton).toContainText(connectorName);
  }

  async openCreateAssetDialog() {
    await clickMarked(this.createButtons.first());
    const dialog = new AssetCreateDialog(this.page);
    await dialog.waitUntilReady();
    return dialog;
  }
}

module.exports = {
  AssetsPage,
  AssetCreateDialog,
};
