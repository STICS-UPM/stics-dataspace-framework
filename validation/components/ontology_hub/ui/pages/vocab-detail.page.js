const { clickMarked } = require("../support/live-marker");
const {
  buildOntologyHubUrl,
  resolveOntologyHubRedirectUrl,
  resolveOntologyHubTimeouts,
} = require("../runtime");

const {
  readyTimeoutMs,
  navigationTimeoutMs,
} = resolveOntologyHubTimeouts();
const optionalMarkerTimeoutMs = Math.min(readyTimeoutMs, 5000);

async function visibleText(locator, timeout = readyTimeoutMs) {
  try {
    await locator.waitFor({ state: "visible", timeout });
    return ((await locator.textContent().catch(() => "")) || "").trim();
  } catch (error) {
    return "";
  }
}

class OntologyHubVocabDetailPage {
  constructor(page) {
    this.page = page;
  }

  async goto(baseUrl, prefix) {
    await this.page.goto(buildOntologyHubUrl(baseUrl, `dataset/vocabs/${prefix}`), {
      waitUntil: "commit",
      timeout: navigationTimeoutMs,
    });
    await this.page.waitForLoadState("domcontentloaded", { timeout: navigationTimeoutMs }).catch(() => {});
  }

  async expectReady(prefix, titleText = "") {
    const roleHeading = this.page.getByRole("heading", { level: 1 }).first();
    const domHeading = this.page.locator("section#title h1, h1[itemprop='name'], h1").first();
    const headingText =
      (await visibleText(roleHeading, optionalMarkerTimeoutMs)) ||
      (await visibleText(domHeading));
    const bodyText = ((await this.page.locator("body").evaluate((node) => node.textContent || "").catch(() => "")) || "")
      .replace(/\s+/g, " ")
      .trim();

    const expectedMarkers = [prefix, titleText].filter(Boolean);
    if (expectedMarkers.length > 0) {
      const combinedText = `${headingText} ${bodyText}`.toLowerCase();
      const hasMarker = expectedMarkers.some((marker) =>
        combinedText.includes(String(marker).toLowerCase()),
      );

      if (!hasMarker) {
        const detail = headingText || bodyText.slice(0, 320) || "No additional diagnostics could be collected.";
        throw new Error(`Vocabulary detail page is not ready for '${prefix}': ${detail}`);
      }
    }

    await this.page
      .getByRole("heading", { name: "Metadata", level: 2 })
      .waitFor({ state: "visible", timeout: readyTimeoutMs })
      .catch(() => {});

    const prefixLocator = this.page.locator("section#post").getByText(prefix, { exact: false }).first();
    if (await prefixLocator.isVisible().catch(() => false)) {
      await prefixLocator.waitFor({ state: "visible" });
    } else {
      await this.page.getByText(prefix, { exact: false }).first().waitFor({ state: "visible" });
    }
    if (titleText) {
      const titleLocator = this.page.locator("section#post").getByText(titleText, { exact: false }).first();
      if (await titleLocator.isVisible().catch(() => false)) {
        await titleLocator.waitFor({ state: "visible" });
      } else {
        await this.page.getByText(titleText, { exact: false }).first().waitFor({ state: "visible" });
      }
    }
  }

  async expectMetadataMarkers() {
    await this.page.getByText("URI", { exact: true }).waitFor({ state: "visible" });
    await this.page.getByText("Description", { exact: true }).waitFor({ state: "visible" });
    await this.page
      .getByRole("heading", { name: "Tags", exact: true })
      .waitFor({ state: "visible", timeout: optionalMarkerTimeoutMs })
      .catch(() => {});
  }

  async expectStatisticsMarkers() {
    await this.page.getByText("Statistics", { exact: true }).waitFor({ state: "visible" });
    await this.page.locator("#chartElements").waitFor({ state: "visible" });
    const html = (await this.page.content()).toLowerCase();
    const requiredMarkers = [
      '"label":"classes"',
      '"label":"properties"',
      '"label":"datatypes"',
      '"label":"instances"',
    ];

    const missingMarkers = requiredMarkers.filter((marker) => !html.includes(marker));
    if (missingMarkers.length > 0) {
      throw new Error(
        `Vocabulary statistics payload is incomplete. Missing markers: ${missingMarkers.join(", ")}`,
      );
    }
  }

  async expectVersionHistoryMarkers() {
    const versionTab = this.page.locator(".ontology-tab").filter({ hasText: "Version History" }).first();
    const tabVisible = await versionTab.isVisible({ timeout: 5000 }).catch(() => false);
    if (tabVisible) {
      await clickMarked(versionTab);
    }
    await this.page.getByText("Vocabulary Version History", { exact: true }).waitFor({
      state: "visible",
    });

    const timeline = this.page.locator("#timeline");
    if (await timeline.isVisible().catch(() => false)) {
      return;
    }

    const pageHtml = await this.page.content();
    const hasEmbeddedVersionHistory =
      /\/dataset\/vocabs\/[^/]+\/versions\/\d{4}-\d{2}-\d{2}\.n3/.test(pageHtml) ||
      /v\d{4}-\d{2}-\d{2}/.test(pageHtml);

    if (!hasEmbeddedVersionHistory) {
      throw new Error(
        "Vocabulary version history markers are not visible and no version resources were embedded in the detail page.",
      );
    }
  }

  versionDownloadLink(dateString) {
    return this.page
      .locator("[data-onto-panel='version-history'].is-active")
      .getByRole("link", { name: `Download ${dateString}.n3`, exact: true })
      .first();
  }

  async exposedVersionResourceUrls(baseUrl, prefix) {
    const hrefUrls = await this.page
      .locator(`a[href*="/dataset/vocabs/${prefix}/versions/"][href$=".n3"]`)
      .evaluateAll((nodes) =>
        nodes
          .map((node) => node.getAttribute("href") || "")
          .filter(Boolean),
      );
    const dataSourceUrls = await this.page
      .locator("[data-source-url]")
      .evaluateAll((nodes) =>
        nodes
          .map((node) => node.getAttribute("data-source-url") || "")
          .filter(Boolean),
      );
    return Array.from(
      new Set(
        [...hrefUrls, ...dataSourceUrls]
          .filter((value) => value.includes(`/dataset/vocabs/${prefix}/versions/`))
          .map((value) => resolveOntologyHubRedirectUrl(baseUrl, value)),
      ),
    );
  }
}

module.exports = {
  OntologyHubVocabDetailPage,
};
