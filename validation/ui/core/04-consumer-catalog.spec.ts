import { test, expect } from "../shared/fixtures/dataspace.fixture";

import { KeycloakLoginPage } from "../components/auth/keycloak-login.page";
import { ConnectorShellPage } from "../components/shell/connector-shell.page";
import { CatalogPage } from "../components/consumer/catalog.page";
import { collectBrowserDiagnostics } from "../shared/utils/browser-diagnostics";
import {
  bootstrapProviderNegotiationArtifacts,
  probeConsumerCatalogDatasetReadiness,
} from "../shared/utils/provider-bootstrap";
import { EVENTUAL_UI_RETRY_INTERVALS } from "../shared/utils/waiting";

test("04 consumer catalog: listing and detail without access errors", async ({
  page,
  request,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  const suffix = `${Date.now()}`;
  const assetId = `qa-ui-catalog-${suffix}`;
  const loginPage = new KeycloakLoginPage(page, {
    portalUser: dataspaceRuntime.consumer.username,
    portalPassword: dataspaceRuntime.consumer.password,
    skipLogin: false,
  });
  const shellPage = new ConnectorShellPage(page);
  const catalogPage = new CatalogPage(page);
  const browserDiagnostics = collectBrowserDiagnostics(page);
  const errorResponses: { url: string; status: number }[] = [];
  let toleratedErrorResponses: { url: string; status: number }[] = [];
  let fatalErrorResponses: { url: string; status: number }[] = [];
  const startedAt = new Date().toISOString();

  const isTolerableCatalogRetry = (url: string, status: number): boolean =>
    (status === 401 || status === 503) &&
    (url.includes("/management/pagination/count?type=federatedCatalog") ||
      url.includes("/management/federatedcatalog/request"));

  page.on("response", (response) => {
    const url = response.url();
    if (
      response.status() >= 400 &&
      (url.includes("/management/") || url.includes("/federatedcatalog"))
    ) {
      errorResponses.push({ url, status: response.status() });
    }
  });

  try {
    const providerBootstrap = await bootstrapProviderNegotiationArtifacts(
      request,
      dataspaceRuntime,
      assetId,
      suffix,
    );
    await attachJson("consumer-catalog-bootstrap", providerBootstrap);
    await attachJson(
      "consumer-catalog-api-readiness",
      await probeConsumerCatalogDatasetReadiness(request, dataspaceRuntime, assetId),
    );

    await loginPage.open(dataspaceRuntime.consumer.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await shellPage.expectReady();
    await captureStep(page, "01-catalog-after-login");

    await expect(async () => {
      await catalogPage.goto(dataspaceRuntime.consumer.portalBaseUrl);
      await shellPage.assertNoGateway403("Catalog page");
      await shellPage.assertNoServerErrorBanner("Catalog page");
      await catalogPage.expectReady();

      let detailOpened = await catalogPage.openDetailsForAsset(assetId);
      while (!detailOpened && (await catalogPage.goToNextPage())) {
        detailOpened = await catalogPage.openDetailsForAsset(assetId);
      }

      expect(detailOpened, `Asset ${assetId} is not visible in the consumer catalog yet`).toBeTruthy();
    }).toPass({
      timeout: 90_000,
      intervals: EVENTUAL_UI_RETRY_INTERVALS,
    });

    await captureStep(page, "02-catalog-list");

    await catalogPage.expectDetailsVisible({
      assetId,
      attachJson,
      context: "consumer-catalog-detail",
    });
    await shellPage.assertNoServerErrorBanner("Catalog detail");
    await captureStep(page, "03-catalog-detail");

    toleratedErrorResponses = errorResponses.filter(({ url, status }) =>
      isTolerableCatalogRetry(url, status),
    );
    fatalErrorResponses = errorResponses.filter(
      ({ url, status }) => !isTolerableCatalogRetry(url, status),
    );
    expect(
      fatalErrorResponses,
      `API calls returned fatal errors: ${JSON.stringify(fatalErrorResponses)} (tolerated transient catalog errors: ${JSON.stringify(toleratedErrorResponses)})`,
    ).toHaveLength(0);
  } finally {
    const browserDiagnosticsSnapshot = browserDiagnostics.snapshot();
    browserDiagnostics.dispose();
    await attachJson("consumer-catalog-browser-diagnostics", browserDiagnosticsSnapshot);
    await attachJson("consumer-catalog-report", {
      startedAt,
      providerConnector: dataspaceRuntime.provider.connectorName,
      consumerConnector: dataspaceRuntime.consumer.connectorName,
      assetId,
      finishedAt: new Date().toISOString(),
      errorResponses,
      toleratedErrorResponses,
      fatalErrorResponses,
      browserDiagnostics: {
        eventCount: browserDiagnosticsSnapshot.eventCount,
        droppedEventCount: browserDiagnosticsSnapshot.droppedEventCount,
      },
    });
  }
});
