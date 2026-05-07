const { test, expect } = require("../fixtures");
const { joinUrl } = require("../runtime");

async function bodyText(page) {
  return page
    .locator("body")
    .evaluate((node) => String(node.textContent || "").replace(/\s+/g, " ").trim())
    .catch(() => "");
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

test("SV-UI-02: semantic virtualization OpenAPI document is visible", async ({
  page,
  semanticVirtualizationRuntime,
  captureStep,
  attachJson,
}) => {
  const url = joinUrl(
    semanticVirtualizationRuntime.baseUrl,
    semanticVirtualizationRuntime.capabilitiesPath,
  );
  const response = await page.goto(url, { waitUntil: "domcontentloaded" });
  const status = response ? response.status() : 0;

  expect(response, `Expected browser navigation response from ${url}`).not.toBeNull();
  expect(status).toBe(200);

  const text = await bodyText(page);
  expect(text.toLowerCase()).toContain("openapi");

  await captureStep(page, "sv-ui-02-openapi");
  await attachJson("sv-ui-02-state", {
    url,
    status,
    bodyExcerpt: text.slice(0, 500),
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
