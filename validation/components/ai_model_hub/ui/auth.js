const fs = require("fs");
const path = require("path");

function projectRoot() {
  return path.resolve(__dirname, "../../../..");
}

function findConnectorCredentialsFile(dataspace, connectorId) {
  const adapter = (process.env.UI_ADAPTER || "inesdata").trim().toLowerCase() || "inesdata";
  const deploymentsRoot = path.join(projectRoot(), "deployers", adapter, "deployments");
  if (!fs.existsSync(deploymentsRoot)) {
    throw new Error(`Deployments directory not found: ${deploymentsRoot}`);
  }

  for (const environmentDir of fs.readdirSync(deploymentsRoot)) {
    const candidate = path.join(
      deploymentsRoot,
      environmentDir,
      dataspace,
      `credentials-connector-${connectorId}.json`,
    );
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }

  throw new Error(`Connector credentials not found for ${connectorId} in dataspace ${dataspace}`);
}

function loadConnectorUserCredentials(dataspace, connectorId) {
  const credentialsFile = findConnectorCredentialsFile(dataspace, connectorId);
  const payload = JSON.parse(fs.readFileSync(credentialsFile, "utf8"));
  const connectorUser = payload.connector_user || {};
  if (!connectorUser.user || !connectorUser.passwd) {
    throw new Error(`connector_user credentials missing in ${credentialsFile}`);
  }
  return connectorUser;
}

async function requestConnectorManagementToken(runtime, connectorId) {
  const connectorUser = loadConnectorUserCredentials(runtime.dataspace, connectorId);
  const tokenEndpoint = `${runtime.keycloakBaseUrl}/realms/${runtime.dataspace}/protocol/openid-connect/token`;

  const body = new URLSearchParams({
    grant_type: "password",
    client_id: "dataspace-users",
    username: connectorUser.user,
    password: connectorUser.passwd,
    scope: "openid profile email",
  });

  const response = await fetch(tokenEndpoint, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: body.toString(),
  });

  if (!response.ok) {
    throw new Error(`Token request failed for ${connectorId}: HTTP ${response.status}`);
  }

  const payload = await response.json();
  if (!payload.access_token) {
    throw new Error(`Token response for ${connectorId} does not contain access_token`);
  }

  return payload.access_token;
}

async function buildManagementAuthorizationHeaders(runtime) {
  const [providerToken, consumerToken] = await Promise.all([
    requestConnectorManagementToken(runtime, runtime.providerConnectorId),
    requestConnectorManagementToken(runtime, runtime.consumerConnectorId),
  ]);

  return {
    [runtime.providerConnectorId]: `Bearer ${providerToken}`,
    [runtime.consumerConnectorId]: `Bearer ${consumerToken}`,
  };
}

async function attachManagementAuthorizationRoutes(page, runtime) {
  const authorizationByConnector = await buildManagementAuthorizationHeaders(runtime);

  await page.route("**/management/**", async (route) => {
    const request = route.request();
    const requestUrl = new URL(request.url());
    const authorization = Object.entries(authorizationByConnector).find(([connectorId]) =>
      requestUrl.hostname.startsWith(connectorId),
    );

    if (!authorization) {
      await route.continue();
      return;
    }

    await route.continue({
      headers: {
        ...request.headers(),
        authorization: authorization[1],
      },
    });
  });

  return authorizationByConnector;
}

module.exports = {
  attachManagementAuthorizationRoutes,
  requestConnectorManagementToken,
};
