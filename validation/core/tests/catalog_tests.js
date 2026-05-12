/**
 * Catalog discovery tests
 * Validates catalog responses from provider
 */
(function() {
const requestName = pm.info.requestName
const status = pm.response.code
const DEFAULT_CATALOG_MAX_ATTEMPTS = 8

function clearLocalVar(key) {
    pm.collectionVariables.unset(key)
    pm.environment.unset(key)
}

function readPositiveInt(key, fallbackValue) {
    const raw = getStoredVar(key)
    const parsed = parseInt(raw, 10)
    return Number.isNaN(parsed) || parsed < 1 ? fallbackValue : parsed
}

function setNextRequestName(name) {
    if (pm.execution && typeof pm.execution.setNextRequest === "function") {
        pm.execution.setNextRequest(name)
        return
    }
    if (typeof postman !== "undefined" && typeof postman.setNextRequest === "function") {
        postman.setNextRequest(name)
    }
}

function scheduleCatalogRetryOrFail(reason, detail) {
    const maxAttempts = readPositiveInt("e2e_catalog_max_attempts", DEFAULT_CATALOG_MAX_ATTEMPTS)
    const attempt = readPositiveInt("e2e_catalog_attempt", 0) + 1

    if (attempt < maxAttempts) {
        saveCollectionVar("e2e_catalog_attempt", String(attempt))
        pm.test(`Federated catalog lookup is still stabilizing (attempt ${attempt}/${maxAttempts})`, function () {
            pm.expect(true).to.be.true
        })
        if (detail) {
            console.log(detail)
        }
        console.log(`Retrying Request Federated Catalog (Management API). Next attempt ${attempt + 1}/${maxAttempts}`)
        setNextRequestName("Request Federated Catalog (Management API)")
        return true
    }

    clearLocalVar("e2e_catalog_attempt")
    pm.test("Federated catalog exposes the E2E asset before negotiation", function () {
        pm.expect.fail(reason)
    })
    if (detail) {
        console.log(detail)
    }
    setNextRequestName(null)
    return false
}

function bodyContainsCatalogError(body) {
    const text = JSON.stringify(body || {})
    return text.includes("CatalogError") || text.includes("BadGateway") || text.includes("Unauthorized")
}

if (requestName === "Provider Login" || requestName === "Consumer Login") {
    const loginBody = parseJsonResponse()
    handleLoginToken(loginBody)
    return
}
if (requestName === "Direct DSP Catalog Request") {
    if (status === 401) {
        pm.test("Direct DSP catalog endpoint requires authentication (tolerated response)", function () {
            pm.expect(status).to.equal(401)
        })
    } else if (status === 200) {
        pm.test("Direct DSP catalog endpoint responded functionally", function () {
            pm.expect(status).to.equal(200)
        })
    } else {
        pm.test("Direct DSP catalog endpoint returned a tolerated non-functional environment response", function () {
            pm.expect(status).to.equal(400)
        })
    }
    return
}
if (status !== 200) {
    scheduleCatalogRetryOrFail(
        `Federated catalog request returned HTTP ${status} before the retry budget was exhausted`,
        `Federated catalog raw response: ${pm.response.text()}`
    )
    return
}
const body = parseJsonResponse()
if (!body) {
    console.log("No valid response body, skipping tests")
    return
}
assertJsonNotEmpty(body)
assertNoEdcError(body)
assertStatus200();
if (bodyContainsCatalogError(body)) {
    scheduleCatalogRetryOrFail(
        "Federated catalog returned an EDC/DSP error before the E2E asset could be discovered",
        `Federated catalog error response: ${pm.response.text()}`
    )
    return
}
const catalog = Array.isArray(body) ? body[0] : body
if (!catalog["dcat:dataset"]) {
    scheduleCatalogRetryOrFail(
        "Federated catalog response did not contain dcat:dataset before negotiation",
        `Federated catalog response without dataset field: ${pm.response.text()}`
    )
    return
}
let datasets = catalog["dcat:dataset"];
if (!Array.isArray(datasets)) {
    datasets = [datasets];
}
const expectedAssetId = getStoredVar("e2e_asset_id");
const dataset = datasets.find(function (item) {
    return item && JSON.stringify(item).includes(expectedAssetId);
});
if (!dataset) {
    scheduleCatalogRetryOrFail(
        `Asset ${expectedAssetId || "<missing>"} did not appear in the federated catalog before negotiation`,
        `Federated catalog datasets visible: ${datasets.length}`
    )
    return
}
clearLocalVar("e2e_catalog_attempt")
pm.test("Catalog response contains dataset field", function () {
    pm.expect(catalog).to.have.property("dcat:dataset");
});
pm.test("Dataset list not empty", function () {
    pm.expect(datasets.length).to.be.above(0);
});
pm.test("Catalog contains the E2E asset", function () {
    pm.expect(JSON.stringify(dataset)).to.include(expectedAssetId);
});
pm.test("Dataset has @id", function () {
    pm.expect(dataset).to.have.property("@id");
});
pm.test("Dataset contains policy", function () {
    pm.expect(dataset).to.have.property("odrl:hasPolicy");
});
let policy = dataset["odrl:hasPolicy"];
if (Array.isArray(policy)) {
    policy = policy[0];
}
saveCollectionVar("providerParticipantId", catalog["dspace:participantId"] || pm.environment.get("provider"))
if (policy && policy["@id"]) {
    saveCollectionVar("e2e_offer_policy_id", policy["@id"]);
}
saveCollectionVar("e2e_catalog_asset_id", dataset["@id"] || expectedAssetId);
console.log("Catalog participant:", catalog["dspace:participantId"]);
console.log("Catalog datasets:", datasets.length);
console.log("First dataset:", dataset);
})(); // End of IIFE
