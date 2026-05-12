import { expect, Page, Route } from "@playwright/test";

import { checkMarked, clickMarked, fillMarked } from "../../../shared/utils/live-marker";
import {
  waitForEventualConsistencyPoll,
  waitForInputValue,
  waitForUiTransition,
} from "../../../shared/utils/waiting";

export class EdcCatalogPage {
  constructor(private readonly page: Page) {}

  async goto(baseUrl: string): Promise<void> {
    await this.page.goto(`${baseUrl.replace(/\/$/, "")}/catalog`, {
      waitUntil: "domcontentloaded",
    });
  }

  async expectReady(): Promise<void> {
    await expect(this.page).toHaveURL(/\/edc-dashboard\/catalog(?:\/)?(?:\?.*)?$/);
    await expect(this.page.locator("lib-catalog-request").first()).toBeVisible({
      timeout: 30_000,
    });
  }

  async requestCatalogManually(
    counterPartyAddress: string,
    counterPartyId?: string,
    catalogResponseBody?: unknown,
  ): Promise<void> {
    const routePattern = "**/management/v3/catalog/request*";
    const routeHandler = async (route: Route) => {
      if (catalogResponseBody !== undefined) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(catalogResponseBody),
        });
        return;
      }

      const originalRequest = route.request();
      const payload = JSON.parse(originalRequest.postData() || "{}");
      payload["@context"] = payload["@context"] || {
        "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
      };
      payload["@type"] = payload["@type"] || "CatalogRequest";
      payload.counterPartyAddress = counterPartyAddress;
      payload.protocol = payload.protocol || "dataspace-protocol-http";
      payload.querySpec = payload.querySpec || {
        offset: 0,
        limit: 100,
        filterExpression: [],
      };
      if (counterPartyId) {
        payload.counterPartyId = counterPartyId;
      }

      await route.continue({
        postData: JSON.stringify(payload),
        headers: {
          ...originalRequest.headers(),
          "content-type": "application/json",
        },
      });
    };

    await this.page.route(routePattern, routeHandler);
    const responsePromise = this.page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url().includes("/management/v3/catalog/request"),
      { timeout: 45_000 },
    );

    try {
      await clickMarked(
        this.page.locator("lib-catalog-request .btn").filter({ hasText: /request manually/i }).first(),
      );
      const dialog = this.openDialog();
      await expect(dialog.getByRole("button", { name: /request catalog/i })).toBeVisible({
        timeout: 30_000,
      });
      await fillMarked(dialog.locator('input[name="counterPartyAddress"]'), counterPartyAddress);
      await clickMarked(dialog.getByRole("button", { name: /request catalog/i }));

      const response = await responsePromise;
      expect(
        response.ok(),
        `Catalog request returned HTTP ${response.status()} for counterPartyAddress ${counterPartyAddress}`,
      ).toBeTruthy();
      await waitForUiTransition(this.page);
    } finally {
      await this.page.unroute(routePattern, routeHandler);
    }
  }

  async waitForAssetVisible(
    counterPartyAddress: string,
    assetId: string,
    timeoutMs = 90_000,
    counterPartyId?: string,
    catalogResponseBody?: unknown,
  ): Promise<void> {
    const startedAt = Date.now();

    while (Date.now() - startedAt < timeoutMs) {
      await this.requestCatalogManually(counterPartyAddress, counterPartyId, catalogResponseBody);
      await this.filterByAssetId(assetId);
      if ((await this.catalogCard(assetId).count().catch(() => 0)) > 0) {
        await expect(this.catalogCard(assetId)).toBeVisible({ timeout: 15_000 });
        return;
      }
      await waitForEventualConsistencyPoll(this.page);
    }

    throw new Error(`Asset ${assetId} did not appear in the EDC catalog within ${timeoutMs}ms`);
  }

  async negotiateAsset(assetId: string, timeoutMs = 60_000): Promise<void> {
    const card = this.catalogCard(assetId);
    await expect(card, `Catalog asset card for ${assetId} is not visible`).toBeVisible({
      timeout: 30_000,
    });

    const negotiateButton = card
      .locator(".card-actions button:not(.btn-circle)")
      .filter({ hasText: /\bnegotiate\b/i })
      .first();
    await expect(
      negotiateButton,
      `Negotiation button for catalog asset ${assetId} is not visible inside the card actions`,
    ).toBeVisible({
      timeout: 15_000,
    });
    await clickMarked(negotiateButton);

    const dialog = this.openDialog();
    await expect(dialog.getByText(/select an offer/i)).toBeVisible({
      timeout: 30_000,
    });
    const submitNegotiationButton = dialog.getByRole("button", { name: /negotiate/i }).last();

    const firstOffer = dialog.locator('input[type="radio"][name="radioGroup"]').first();
    await firstOffer.scrollIntoViewIfNeeded();
    await expect(firstOffer, "No offer is available in the negotiation dialog").toBeVisible({
      timeout: 30_000,
    });
    await checkMarked(firstOffer);
    await submitNegotiationButton.scrollIntoViewIfNeeded();
    await expect(submitNegotiationButton).toBeVisible({
      timeout: 30_000,
    });

    const negotiateResponse = this.page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url().includes("/management/v3/contractnegotiations"),
      { timeout: 30_000 },
    );

    await clickMarked(submitNegotiationButton);
    const response = await negotiateResponse;
    expect(response.ok(), `Negotiation request returned HTTP ${response.status()}`).toBeTruthy();

    const goToContractsButton = dialog.getByRole("button", { name: /go to contracts/i });
    await expect(goToContractsButton).toBeVisible({ timeout: timeoutMs });
    await clickMarked(goToContractsButton);
    await expect(this.page).toHaveURL(/\/edc-dashboard\/contracts(?:\/)?(?:\?.*)?$/, {
      timeout: 30_000,
    });
  }

  private catalogCard(assetId: string) {
    return this.page.locator("lib-catalog-card").filter({ hasText: assetId }).first();
  }

  private async filterByAssetId(assetId: string): Promise<void> {
    const filterInput = this.page
      .locator('input[placeholder*="Filter for Asset ID"], input[placeholder*="Filter for"]')
      .first();
    if ((await filterInput.count().catch(() => 0)) === 0) {
      return;
    }

    await fillMarked(filterInput, assetId);
    await waitForInputValue(filterInput, assetId);
  }

  private openDialog() {
    return this.page.locator("dialog[open]#dashboard-dialog").first();
  }
}
