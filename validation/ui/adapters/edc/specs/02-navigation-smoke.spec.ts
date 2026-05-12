import { KeycloakLoginPage } from "../../../components/auth/keycloak-login.page";
import { test } from "../../../shared/fixtures/dataspace.fixture";
import { EdcDashboardPage, EdcPageProbe } from "../components/edc-dashboard.page";

type NavigationExpectation = {
  section: string;
  path: string;
  probes: EdcPageProbe[];
};

const providerSections: NavigationExpectation[] = [
  {
    section: "Assets",
    path: "/edc-dashboard/assets",
    probes: [
      { description: "asset create button", selector: "button:has-text('Create')" },
      { description: "asset card", selector: "lib-asset-card" },
    ],
  },
  {
    section: "Policy Definitions",
    path: "/edc-dashboard/policies",
    probes: [
      { description: "policy create button", selector: "button:has-text('Create')" },
      { description: "policy card", selector: "lib-policy-card" },
    ],
  },
  {
    section: "Contract Definitions",
    path: "/edc-dashboard/contract-definitions",
    probes: [
      { description: "contract definition create button", selector: "button:has-text('Create')" },
      { description: "contract definition card", selector: "lib-contract-definition-card" },
    ],
  },
];

const consumerSections: NavigationExpectation[] = [
  {
    section: "Catalog",
    path: "/edc-dashboard/catalog",
    probes: [
      { description: "catalog request widget", selector: "lib-catalog-request" },
      { description: "catalog dataset card", selector: "lib-catalog-card" },
      { description: "catalog empty state", text: /catalog/i },
    ],
  },
  {
    section: "Contracts",
    path: "/edc-dashboard/contracts",
    probes: [
      { description: "contract switch", selector: "lib-consumer-provider-switch" },
      { description: "contract card", selector: "lib-contract-agreement-card" },
      { description: "contracts empty state", text: /no contracts yet/i },
    ],
  },
  {
    section: "Transfer History",
    path: "/edc-dashboard/transfer-history",
    probes: [
      { description: "transfer history table", selector: "lib-transfer-history-table" },
      {
        description: "transfer history columns",
        text: /Transfer ID|State Changed|Transfer Type|Asset ID|Contract ID/i,
      },
      { description: "transfer type switch", selector: "lib-consumer-provider-switch" },
      { description: "transfer empty state", text: /no data transfer initiated yet/i },
    ],
  },
];

test("02 edc navigation smoke: provider and consumer sections are reachable", async ({
  browser,
  dataspaceRuntime,
  captureStep,
}) => {
  const providerContext = await browser.newContext({ ignoreHTTPSErrors: true });
  const providerPage = await providerContext.newPage();
  const consumerContext = await browser.newContext({ ignoreHTTPSErrors: true });
  const consumerPage = await consumerContext.newPage();

  try {
    const providerLoginPage = new KeycloakLoginPage(providerPage, {
      portalUser: dataspaceRuntime.provider.username,
      portalPassword: dataspaceRuntime.provider.password,
      skipLogin: false,
    });
    const providerDashboard = new EdcDashboardPage(providerPage);

    await providerLoginPage.open(dataspaceRuntime.provider.portalBaseUrl);
    await providerLoginPage.loginIfNeeded();
    await providerDashboard.expectShellReady();

    for (const entry of providerSections) {
      await providerDashboard.navigateToSection(entry.section, entry.path);
      await providerDashboard.expectNoServerErrorBanner(`Provider ${entry.section}`);
      await providerDashboard.expectPageMarkers(entry.probes, `Provider ${entry.section}`);
      await captureStep(providerPage, `provider-${slugify(entry.section)}`);
    }

    const consumerLoginPage = new KeycloakLoginPage(consumerPage, {
      portalUser: dataspaceRuntime.consumer.username,
      portalPassword: dataspaceRuntime.consumer.password,
      skipLogin: false,
    });
    const consumerDashboard = new EdcDashboardPage(consumerPage);

    await consumerLoginPage.open(dataspaceRuntime.consumer.portalBaseUrl);
    await consumerLoginPage.loginIfNeeded();
    await consumerDashboard.expectShellReady();

    for (const entry of consumerSections) {
      await consumerDashboard.navigateToSection(entry.section, entry.path);
      await consumerDashboard.expectNoServerErrorBanner(`Consumer ${entry.section}`);
      await consumerDashboard.expectPageMarkers(entry.probes, `Consumer ${entry.section}`);
      await captureStep(consumerPage, `consumer-${slugify(entry.section)}`);
    }
  } finally {
    await providerContext.close().catch(() => undefined);
    await consumerContext.close().catch(() => undefined);
  }
});

function slugify(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-");
}
