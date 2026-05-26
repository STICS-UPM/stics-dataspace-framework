const { clickMarked, fillMarked, selectOptionMarked } = require("../support/live-marker");
const { resolveOntologyHubTimeouts } = require("../runtime");

const { readyTimeoutMs, navigationTimeoutMs } = resolveOntologyHubTimeouts();

class OntologyHubVocabFormPage {
  constructor(page) {
    this.page = page;
    this.form = page.locator("#TheForm");
    this.formErrors = page.locator("#formErrors");
    this.saveButton = page.locator(".editionSaveButtonRight");
  }

  async gotoEdit(baseUrl, prefix) {
    await this.page.goto(`${baseUrl}/edition/vocabs/${encodeURIComponent(prefix)}`, {
      waitUntil: "domcontentloaded",
    });
  }

  async expectReady(prefix = "") {
    const prefixInput = this.page.locator("#inputVocabPrefix");
    await prefixInput.waitFor({ state: "visible", timeout: readyTimeoutMs });
    await this.titleFields().first().waitFor({ state: "visible", timeout: readyTimeoutMs });
    if (prefix) {
      const currentPrefix = ((await prefixInput.inputValue().catch(() => "")) || "").trim();
      if (currentPrefix && currentPrefix !== prefix) {
        throw new Error(
          `Expected to edit vocabulary '${prefix}', but the form loaded '${currentPrefix}'.`,
        );
      }
    }
  }

  titleFields() {
    return this.page.locator("textarea[name^='titles']");
  }

  descriptionFields() {
    return this.page.locator("textarea[name^='descriptions']");
  }

  titleLanguageSelects() {
    return this.page.locator("select[name^='titles']");
  }

  descriptionLanguageSelects() {
    return this.page.locator("select[name^='descriptions']");
  }

  async ensureMultilingualFields(fieldKind, primaryLanguage, secondaryLanguage) {
    const addButton =
      fieldKind === "titles"
        ? this.page.locator(".fieldWithLangAddActionTitle")
        : this.page.locator(".fieldWithLangAddActionDescription");
    const selects =
      fieldKind === "titles" ? this.titleLanguageSelects() : this.descriptionLanguageSelects();

    if ((await selects.count()) === 0) {
      await clickMarked(addButton);
    }
    if ((await selects.count()) < 2) {
      await clickMarked(addButton);
    }

    const primary = String(primaryLanguage || "").trim().toLowerCase();
    const secondary = String(secondaryLanguage || "").trim().toLowerCase();

    if (primary) {
      await selectOptionMarked(selects.first(), primary);
    }
    if (secondary && (await selects.count()) > 1) {
      await selectOptionMarked(selects.nth(1), secondary);
    }
  }

  async ensureTitles(primaryLanguage, secondaryLanguage, primaryValue, secondaryValue) {
    await this.ensureMultilingualFields("titles", primaryLanguage, secondaryLanguage);
    await fillMarked(this.titleFields().first(), primaryValue);
    if ((await this.titleFields().count()) > 1 && secondaryValue) {
      await fillMarked(this.titleFields().nth(1), secondaryValue);
    }
  }

  async ensureDescriptions(primaryLanguage, secondaryLanguage, primaryValue, secondaryValue) {
    await this.ensureMultilingualFields("descriptions", primaryLanguage, secondaryLanguage);
    await fillMarked(this.descriptionFields().first(), primaryValue);
    if ((await this.descriptionFields().count()) > 1 && secondaryValue) {
      await fillMarked(this.descriptionFields().nth(1), secondaryValue);
    }
  }

  async setReview(reviewText) {
    const reviews = this.page.locator("textarea[name^='reviews']");
    if ((await reviews.count()) === 0) {
      await clickMarked(this.page.locator(".fieldReviewAddAction"));
    }
    await fillMarked(this.page.locator("textarea[name^='reviews']").first(), reviewText);
  }

  async currentTitleLanguages() {
    return this.titleLanguageSelects().evaluateAll((nodes) =>
      nodes
        .map((node) => String(node.value || "").trim().toLowerCase())
        .filter(Boolean),
    );
  }

  async currentDescriptionLanguages() {
    return this.descriptionLanguageSelects().evaluateAll((nodes) =>
      nodes
        .map((node) => String(node.value || "").trim().toLowerCase())
        .filter(Boolean),
    );
  }

  async save() {
    const signalTimeoutMs = 60000;
    const responsePromise = this.page
      .waitForResponse(
        (response) =>
          ["POST", "PUT"].includes(response.request().method()) &&
          /\/edition\/vocabs\/[^/]+\/?$/.test(new URL(response.url()).pathname),
        { timeout: signalTimeoutMs },
      )
      .catch(() => null);
    const redirectPromise = this.page
      .waitForURL(/\/dataset\/vocabs\/[^/]+\/?$/, { timeout: signalTimeoutMs })
      .then(() => true)
      .catch(() => false);

    await clickMarked(this.saveButton);

    const response = await Promise.race([
      responsePromise,
      redirectPromise.then(() => null),
    ]);
    const responseBody = response ? await response.text().catch(() => "") : "";
    let responsePayload = null;
    try {
      responsePayload = responseBody ? JSON.parse(responseBody) : null;
    } catch (error) {
      responsePayload = null;
    }

    if (response && response.status() === 404 && this.#isVocabularyEditionTarget(response.url())) {
      const fallbackOutcome = await this.#saveWithPutFallback();
      return {
        ...fallbackOutcome,
        primaryResponseStatus: response.status(),
        primaryResponseBody: responseBody,
        fallbackUsed: true,
      };
    }

    let redirected = await Promise.race([
      redirectPromise,
      this.page.waitForTimeout(1500).then(() => false),
    ]);
    const redirectTarget =
      responsePayload && typeof responsePayload === "object"
        ? String(responsePayload.redirect || "").trim()
        : "";
    if (!redirected && redirectTarget && !/^500$/i.test(redirectTarget)) {
      await this.page.goto(new URL(redirectTarget, this.page.url()).toString(), {
        waitUntil: "domcontentloaded",
      });
      redirected = true;
    } else if (!redirected) {
      const stillProcessing = await this.page
        .locator("#loading-div-background")
        .isVisible()
        .catch(() => false);
      if (stillProcessing) {
        await this.page
          .locator("#loading-div-background")
          .waitFor({ state: "hidden", timeout: 45000 })
          .catch(() => {});
        redirected = await this.page
          .waitForURL(/\/dataset\/vocabs\/[^/]+\/?$/, { timeout: navigationTimeoutMs })
          .then(() => true)
          .catch(() => false);
      }
    }

    return {
      redirected,
      responseStatus: response ? response.status() : 0,
      responseBody,
      redirectTarget,
      finalUrl: this.page.url(),
    };
  }

  #isVocabularyEditionTarget(url) {
    try {
      return /\/edition\/vocabs\/[^/]+\/?$/.test(new URL(url).pathname);
    } catch (error) {
      return false;
    }
  }

  async #formUrlEncodedPayload() {
    const entries = await this.form.evaluate((form) => {
      const formData = new FormData(form);
      return Array.from(formData.entries())
        .filter(([, value]) => typeof value === "string")
        .map(([name, value]) => [String(name), String(value)]);
    });
    const payload = new URLSearchParams();
    for (const [name, value] of entries) {
      if (name === "_method" || name === "_csrf" || name === "payload") {
        continue;
      }
      payload.append(name, value);
    }
    return payload.toString();
  }

  async #saveWithPutFallback() {
    const action = (await this.form.getAttribute("action")) || this.page.url();
    const targetUrl = new URL(action, this.page.url()).toString();
    const response = await this.page.request.put(targetUrl, {
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
      },
      data: await this.#formUrlEncodedPayload(),
    });
    const responseBody = await response.text().catch(() => "");
    let responsePayload = null;
    try {
      responsePayload = responseBody ? JSON.parse(responseBody) : null;
    } catch (error) {
      responsePayload = null;
    }

    const redirectTarget =
      responsePayload && typeof responsePayload === "object"
        ? String(responsePayload.redirect || "").trim()
        : "";
    let redirected = false;
    if (redirectTarget && !/^500$/i.test(redirectTarget)) {
      await this.page.goto(new URL(redirectTarget, this.page.url()).toString(), {
        waitUntil: "domcontentloaded",
      });
      redirected = true;
    } else if (response.ok()) {
      await this.page.waitForLoadState("domcontentloaded", { timeout: navigationTimeoutMs }).catch(() => {});
    }

    return {
      redirected,
      responseStatus: response.status(),
      responseBody,
      redirectTarget,
      finalUrl: this.page.url(),
    };
  }

  async readFormErrors() {
    const content = await this.page
      .evaluate(() => document.querySelector("#formErrors")?.textContent || "")
      .catch(() => "");
    return String(content).replace(/\s+/g, " ").trim();
  }
}

module.exports = {
  OntologyHubVocabFormPage,
};
