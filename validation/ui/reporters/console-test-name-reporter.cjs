class ConsoleTestNameReporter {
  constructor() {
    this.pendingLine = false;
    this.interactive = Boolean(process.stdout.isTTY);
    this.colors = this._supportsColor();
    this.groupCounts = new Map();
    this.groupHeadersByTest = new WeakMap();
    this.printGroupHeaders = false;
    this.printedGroupHeaderTests = new WeakSet();
  }

  _supportsColor() {
    if (process.env.NO_COLOR) {
      return false;
    }
    return Boolean(process.stdout.isTTY || process.env.FORCE_COLOR);
  }

  _color(value, code) {
    if (!this.colors) {
      return value;
    }
    return `\u001b[${code}m${value}\u001b[0m`;
  }

  _suiteName() {
    const explicit = (process.env.PIONERA_PLAYWRIGHT_SUITE_NAME || "").trim();
    if (explicit) {
      return explicit;
    }
    const adapter = (process.env.UI_ADAPTER || "").trim().toLowerCase();
    if (adapter === "inesdata") {
      return "INESData integration";
    }
    if (adapter === "edc") {
      return "EDC Playwright";
    }
    if (adapter) {
      return `${adapter} Playwright`;
    }
    return "";
  }

  _suiteTestCount(suite) {
    if (!suite || typeof suite.allTests !== "function") {
      return null;
    }
    const tests = suite.allTests();
    if (!Array.isArray(tests)) {
      return null;
    }
    return tests.length;
  }

  _suiteLabel(suiteName, testCount) {
    if (!Number.isInteger(testCount)) {
      return suiteName;
    }
    const suffix = testCount === 1 ? "test" : "tests";
    return `${suiteName} (${testCount} ${suffix})`;
  }

  _normalizedPath(value) {
    return String(value || "").replace(/\\/g, "/").replace(/_/g, "-").toLowerCase();
  }

  _testFile(test) {
    return this._normalizedPath((test && test.location && test.location.file) || "");
  }

  _testGroup(test) {
    const file = this._testFile(test);
    if (!file) {
      return "";
    }
    if (file.includes("08-ontology-hub-inesdata-readonly.spec")) {
      return "Ontology Hub";
    }
    if (
      file.includes("09-ai-model-hub-httpdata.spec") ||
      file.includes("10-ai-model-observer.spec") ||
      file.includes("11-ai-model-browser.spec") ||
      file.includes("12-ai-model-execution.spec") ||
      file.includes("13-ai-model-benchmarking.spec") ||
      file.includes("14-ai-model-daimo-vocabulary.spec") ||
      file.includes("15-ai-model-external-execution.spec") ||
      file.includes("16-ai-model-observer-participant-summary.spec")
    ) {
      return "AI Model Hub";
    }
    if (file.includes("07-semantic-virtualization-httpdata.spec")) {
      return "Semantic Virtualization";
    }
    if (
      file.includes("/ui/inesdata/") ||
      file.includes("validation/ui/adapters/inesdata/specs/") ||
      file.includes("validation/ui/core/") ||
      file.startsWith("core/") ||
      file.startsWith("adapters/inesdata/specs/")
    ) {
      return "Core";
    }
    if (file.includes("components/ontology-hub/functional/")) {
      return "Functional";
    }
    if (file.includes("components/ontology-hub/integration/")) {
      return "API integration";
    }
    if (file.includes("components/ai-model-hub/inesdata-ui/")) {
      return "AI Model Hub";
    }
    if (
      file.includes("components/ai-model-hub/ui/specs/pt5-mh-03") ||
      file.includes("components/ai-model-hub/ui/specs/pt5-mh-08")
    ) {
      return "AI Model Hub";
    }
    if (file.includes("components/ai-model-hub/")) {
      return "Functional";
    }
    if (file.includes("components/semantic-virtualization/")) {
      return "Functional";
    }
    return "";
  }

  _prepareGroupCounts(suite) {
    this.groupCounts = new Map();
    this.groupHeadersByTest = new WeakMap();
    this.printGroupHeaders = false;
    this.printedGroupHeaderTests = new WeakSet();
    const tests = suite && typeof suite.allTests === "function" ? suite.allTests() : [];
    if (!Array.isArray(tests)) {
      return;
    }
    const groups = tests.map((test) => this._testGroup(test));
    const uniqueGroups = new Set(groups.filter(Boolean));
    this.printGroupHeaders = uniqueGroups.size > 1;
    if (!this.printGroupHeaders) {
      return;
    }

    let index = 0;
    while (index < tests.length) {
      const group = groups[index] || "";
      let nextIndex = index + 1;
      while (nextIndex < tests.length && (groups[nextIndex] || "") === group) {
        nextIndex += 1;
      }

      if (group) {
        const count = nextIndex - index;
        this.groupCounts.set(group, (this.groupCounts.get(group) || 0) + count);
        this.groupHeadersByTest.set(tests[index], { group, count });
      }

      index = nextIndex;
    }
  }

  _printGroupHeader(test) {
    if (!this.printGroupHeaders) {
      return;
    }
    const header = this.groupHeadersByTest.get(test);
    if (!header || this.printedGroupHeaderTests.has(test)) {
      return;
    }
    this.printedGroupHeaderTests.add(test);
    const { group, count } = header;
    const suffix = count === 1 ? "test" : "tests";
    const label = Number.isInteger(count) ? `${group} (${count} ${suffix})` : group;
    console.log(this._color(`Group: ${label}`, "36"));
  }

  onBegin(_config, suite) {
    const suiteName = this._suiteName();
    this._prepareGroupCounts(suite);
    if (suiteName) {
      const suiteLabel = this._suiteLabel(suiteName, this._suiteTestCount(suite));
      console.log(this._color(`Suite: ${suiteLabel}`, "36;1"));
    }
  }

  onTestBegin(test) {
    if (!this.interactive) {
      return;
    }
    this._printGroupHeader(test);
    process.stdout.write(`${this._color("›", "36")} ${test.title}`);
    this.pendingLine = true;
  }

  onTestEnd(test, result) {
    if (this.pendingLine) {
      process.stdout.write("\r\u001b[2K");
      this.pendingLine = false;
    }

    this._printGroupHeader(test);
    const status = result.status || "unknown";
    if (status === "passed") {
      console.log(`${this._color("✓", "32")} ${test.title}`);
      return;
    }
    if (status === "skipped") {
      console.log(`${this._color("-", "33")} ${test.title}`);
      return;
    }
    console.log(this._color(`✗ ${test.title}`, "31"));
  }
}

module.exports = ConsoleTestNameReporter;
