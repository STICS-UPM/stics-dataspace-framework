import { Page } from "@playwright/test";

import { KeycloakLoginPage } from "../../components/auth/keycloak-login.page";
import { ConnectorShellPage } from "../../components/shell/connector-shell.page";
import { test as evidenceTest, expect } from "./evidence.fixture";

type AuthFixtures = {
  loginPage: KeycloakLoginPage;
  shellPage: ConnectorShellPage;
  ensureLoggedIn: (page?: Page) => Promise<void>;
};

export const test = evidenceTest.extend<AuthFixtures>({
  loginPage: async ({ page, portalUser, portalPassword, portalSkipLogin }, use) => {
    await use(
      new KeycloakLoginPage(page, {
        portalUser,
        portalPassword,
        skipLogin: portalSkipLogin,
      }),
    );
  },

  shellPage: async ({ page }, use) => {
    await use(new ConnectorShellPage(page));
  },

  ensureLoggedIn: async ({ loginPage, shellPage, portalBaseUrl }, use) => {
    await use(async () => {
      await loginPage.open(portalBaseUrl);
      await loginPage.loginIfNeeded();
      await shellPage.expectReady();
    });
  },
});

export { expect } from "./evidence.fixture";
