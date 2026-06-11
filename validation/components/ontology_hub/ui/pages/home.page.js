const { clickMarked } = require("../support/live-marker");
const {
  buildOntologyHubUrl,
  inferOntologyHubBaseUrl,
  resolveOntologyHubTimeouts,
} = require("../runtime");

const { navigationTimeoutMs, readyTimeoutMs } = resolveOntologyHubTimeouts();

function isTransientNavigationError(error) {
  const message = String((error && error.message) || error || "");
  return /timeout|net::err|navigation failed|target closed/i.test(message);
}

function isPointerInterceptionError(error) {
  return /intercepts pointer events|element is not receiving pointer events/i.test(
    String((error && error.message) || error || ""),
  );
}

class OntologyHubHomePage {
  constructor(page) {
    this.page = page;
  }

  async goto(baseUrl) {
    const targetUrl = buildOntologyHubUrl(baseUrl, "dataset");
    const deadline = Date.now() + Math.max(navigationTimeoutMs * 2, readyTimeoutMs);
    let lastError = null;

    while (Date.now() < deadline) {
      try {
        await this.page.goto(targetUrl, {
          waitUntil: "commit",
          timeout: navigationTimeoutMs,
        });
        await this.page
          .waitForLoadState("domcontentloaded", { timeout: navigationTimeoutMs })
          .catch(() => {});
        return;
      } catch (error) {
        lastError = error;
        if (!isTransientNavigationError(error)) {
          throw error;
        }
        await this.page.waitForTimeout(2000);
      }
    }

    throw lastError || new Error("Ontology Hub home page did not load within the retry window.");
  }

  async expectReady() {
    await this.page.locator("header nav").waitFor({ state: "visible", timeout: readyTimeoutMs });
    await this.page.locator("#searchInput").waitFor({ state: "visible", timeout: readyTimeoutMs });
  }

  vocabularyBubble(prefix) {
    const escaped = String(prefix || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return this.page
      .locator("#vis svg g.node")
      .filter({
        has: this.page.locator("title", {
          hasText: new RegExp(`^\\s*${escaped}(?:\\s*-.*)?$`, "i"),
        }),
      })
      .first();
  }

  async openVocabularyBubble(prefix) {
    const bubble = this.vocabularyBubble(prefix);
    await bubble.waitFor({ state: "visible", timeout: readyTimeoutMs });
    const circle = bubble.locator("circle").first();
    const clickAttempts = [];

    if ((await circle.count()) > 0) {
      clickAttempts.push(() => clickMarked(circle));
      clickAttempts.push(() => clickMarked(circle, { force: true }));
    }

    clickAttempts.push(() => clickMarked(bubble));
    clickAttempts.push(() => clickMarked(bubble, { force: true }));

    let lastError = null;
    for (const attempt of clickAttempts) {
      try {
        await attempt();
        return;
      } catch (error) {
        lastError = error;
        if (!isPointerInterceptionError(error)) {
          throw error;
        }
      }
    }

    throw lastError;
  }

  navLink(label) {
    return this.page.locator("header nav a").filter({ hasText: label }).first();
  }

  async gotoApiDocs(baseUrl = "") {
    const resolvedBaseUrl = baseUrl || inferOntologyHubBaseUrl(this.page.url());
    await this.page.goto(buildOntologyHubUrl(resolvedBaseUrl, "dataset/api"), {
      waitUntil: "domcontentloaded",
      timeout: navigationTimeoutMs,
    });
  }
}

module.exports = {
  OntologyHubHomePage,
};
