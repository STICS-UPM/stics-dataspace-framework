/**
 * Provider setup tests
 * Used by:
 * 03_provider_setup.json
 */
(function() {
const requestName = pm.info.requestName
const status = pm.response.code
const body = parseJsonResponse()
const DEFAULT_PROVIDER_AUTH_MAX_ATTEMPTS = 3

function safeIdentifier(value, fallback) {
    const raw = String(value || fallback || "unknown")
    const safe = raw
        .toLowerCase()
        .replace(/[^a-z0-9._-]+/g, "-")
        .replace(/-+/g, "-")
        .replace(/^[._-]+|[._-]+$/g, "")
    return safe || fallback || "unknown"
}

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

function providerAuthAttemptVar(name) {
    return `e2e_provider_auth_attempt_${safeIdentifier(name, "request")}`
}

function isAuthenticationStatus(code) {
    return [401, 403].includes(code)
}

function scheduleProviderLoginThenRetry(requestToRepeat) {
    const attemptVar = providerAuthAttemptVar(requestToRepeat)
    const maxAttempts = readPositiveInt("e2e_provider_auth_max_attempts", DEFAULT_PROVIDER_AUTH_MAX_ATTEMPTS)
    const attempt = readPositiveInt(attemptVar, 0) + 1

    if (attempt < maxAttempts) {
        saveCollectionVar(attemptVar, String(attempt))
        saveCollectionVar("e2e_after_provider_login_request", requestToRepeat)
        pm.test(`Provider authentication is being renewed (attempt ${attempt}/${maxAttempts})`, function () {
            pm.expect(true).to.be.true
        })
        console.log(`${requestToRepeat} returned HTTP ${status}; refreshing the provider token before retrying.`)
        setNextRequestName("Provider Login")
        return true
    }

    clearLocalVar(attemptVar)
    clearLocalVar("e2e_after_provider_login_request")
    pm.test(`${requestToRepeat} could not authenticate after repeated provider token refreshes`, function () {
        pm.expect.fail(`${requestToRepeat} kept returning HTTP ${status} after refreshing the provider token`)
    })
    setNextRequestName(null)
    return false
}

if (requestName === "Provider Login") {
    assertStatus200()
    if (!body) {
        return
    }
    assertFieldExists(body, "access_token")
    saveCollectionVar("provider_jwt", body.access_token)

    if (!getStoredVar("e2e_suffix")) {
        const suffix = String(Date.now())
        const runScope = safeIdentifier(
            getStoredVar("e2e_run_scope"),
            `${getStoredVar("provider") || "provider"}-${getStoredVar("consumer") || "consumer"}`
        )
        saveCollectionVar("e2e_suffix", suffix)
        saveCollectionVar("e2e_asset_id", `asset-e2e-${suffix}`)
        saveCollectionVar("e2e_policy_id", `policy-e2e-${suffix}`)
        saveCollectionVar("e2e_contract_definition_id", `contract-e2e-${suffix}`)
        saveCollectionVar("e2e_source_object_name", `todos-${runScope}-${suffix}.json`)
    }

    const nextRequest = getStoredVar("e2e_after_provider_login_request")
    if (nextRequest) {
        clearLocalVar("e2e_after_provider_login_request")
        setNextRequestName(nextRequest)
    }
    return
}

if (isAuthenticationStatus(status)) {
    scheduleProviderLoginThenRetry(requestName)
    return
}

if (!body) {
    console.log("No valid response body, skipping tests")
    return
}

clearLocalVar(providerAuthAttemptVar(requestName))
assertNoEdcError(body)

if (requestName === "Create E2E Asset") {
    assertCreated()
    extractAtId(body, "e2e_asset_id")
    return
}

if (requestName === "List E2E Assets") {
    assertStatus200()
    const assetId = pm.collectionVariables.get("e2e_asset_id")
    assertNotEmpty(assetId, "e2e_asset_id")
    pm.test("E2E asset appears in asset lookup result", function () {
        pm.expect(Array.isArray(body)).to.equal(true)
        pm.expect(body.some((asset) => asset && asset["@id"] === assetId)).to.equal(true)
    })
    return
}

if (requestName === "Create E2E Policy") {
    assertCreated()
    extractAtId(body, "e2e_policy_id")
    return
}

if (requestName === "List E2E Policies") {
    assertStatus200()
    const policyId = pm.collectionVariables.get("e2e_policy_id")
    assertNotEmpty(policyId, "e2e_policy_id")
    pm.test("E2E policy appears in policy lookup result", function () {
        pm.expect(Array.isArray(body)).to.equal(true)
        pm.expect(body.some((policy) => policy && policy["@id"] === policyId)).to.equal(true)
    })
    return
}

if (requestName === "Create E2E Contract Definition") {
    assertCreated()
    extractAtId(body, "e2e_contract_definition_id")
    return
}

if (requestName === "List E2E Contract Definitions") {
    assertStatus200()
    const contractId = pm.collectionVariables.get("e2e_contract_definition_id")
    assertNotEmpty(contractId, "e2e_contract_definition_id")
    pm.test("E2E contract definition appears in lookup result", function () {
        pm.expect(Array.isArray(body)).to.equal(true)
        pm.expect(body.some((contract) => contract && contract["@id"] === contractId)).to.equal(true)
    })
}
})(); // End of IIFE
