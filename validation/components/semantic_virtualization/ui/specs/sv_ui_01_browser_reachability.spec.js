const { test, expect } = require("../fixtures");
const { joinUrl } = require("../runtime");

async function bodyText(page) {
  return page
    .locator("body")
    .evaluate((node) => String(node.textContent || "").replace(/\s+/g, " ").trim())
    .catch(() => "");
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function requestJsonWithRetry(request, url, attempts = 8, delayMs = 750) {
  let last = {
    status: 0,
    contentType: "",
    body: "",
    payload: null,
  };

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const response = await request.get(url, {
      headers: {
        Accept: "application/json",
        "Cache-Control": "no-store",
      },
    });
    const body = await response.text();
    const contentType = response.headers()["content-type"] || "";
    last = {
      status: response.status(),
      contentType,
      body,
      payload: null,
    };

    if (response.status() === 200 && contentType.toLowerCase().includes("application/json")) {
      try {
        last.payload = JSON.parse(body);
        return last;
      } catch (error) {
        last.parseError = error.message;
      }
    }

    if (attempt < attempts - 1) {
      await delay(delayMs);
    }
  }

  return last;
}

test("SV-UI-01: semantic virtualization root is reachable from a browser", async ({
  page,
  semanticVirtualizationRuntime,
  captureStep,
  attachJson,
}) => {
  const url = joinUrl(semanticVirtualizationRuntime.baseUrl, semanticVirtualizationRuntime.rootPath);
  const response = await page.goto(url, { waitUntil: "domcontentloaded" });
  const status = response ? response.status() : 0;

  expect(response, `Expected browser navigation response from ${url}`).not.toBeNull();
  expect(status).toBe(200);

  await captureStep(page, "sv-ui-01-root");
  await attachJson("sv-ui-01-state", {
    url,
    status,
    title: await page.title().catch(() => ""),
    bodyExcerpt: (await bodyText(page)).slice(0, 500),
  });
});

test("SV-UI-02: semantic virtualization OpenAPI document is available", async ({
  request,
  semanticVirtualizationRuntime,
  attachJson,
}) => {
  const url = joinUrl(
    semanticVirtualizationRuntime.baseUrl,
    semanticVirtualizationRuntime.capabilitiesPath,
  );
  const result = await requestJsonWithRetry(request, url);

  expect(result.status).toBe(200);
  expect(result.contentType.toLowerCase()).toContain("application/json");
  expect(result.payload, `Expected valid OpenAPI JSON from ${url}; received: ${result.body.slice(0, 160)}`).toBeTruthy();
  const payload = result.payload;
  expect(String(payload.openapi || "")).toBeTruthy();
  expect(JSON.stringify(payload.paths || {})).toContain("/openapi.json");

  await attachJson("sv-ui-02-state", {
    url,
    status: result.status,
    contentType: result.contentType,
    bodyExcerpt: result.body.slice(0, 500),
  });
});

test("SV-UI-03: semantic virtualization query endpoint is reachable from Playwright", async ({
  request,
  semanticVirtualizationRuntime,
  attachJson,
}) => {
  const url = joinUrl(semanticVirtualizationRuntime.baseUrl, semanticVirtualizationRuntime.queryPath);
  const response = await request.get(url, {
    headers: {
      Accept: "application/sparql-results+json",
      "Cache-Control": "no-store",
    },
  });
  const body = await response.text();

  expect(response.status()).toBe(200);
  await attachJson("sv-ui-03-state", {
    url,
    status: response.status(),
    contentType: response.headers()["content-type"] || "",
    bodyExcerpt: body.slice(0, 500),
  });
});
