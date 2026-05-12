/**
 * Environment health tests
 * Used by:
 * 01_environment_health.json
 */
(function() {
const requestName = pm.info.requestName
const status = pm.response.code

if (requestName === "Provider Login" || requestName === "Consumer Login") {
    const body = parseJsonResponse()
    assertStatus200()
    if (!body) {
        return
    }
    assertFieldExists(body, "access_token")
    if (requestName === "Provider Login") {
        saveCollectionVar("provider_jwt", body.access_token)
    } else {
        saveCollectionVar("consumer_jwt", body.access_token)
    }
    return
}

if (requestName === "Provider Management API Health" || requestName === "Consumer Management API Health") {
    if (status !== 200) {
        pm.test(`${requestName} authenticates successfully`, function () {
            pm.expect.fail(`${requestName} returned HTTP ${status}: ${responseText()}`)
        })
        return
    }

    const body = parseJsonResponse()
    assertStatus200()
    pm.test(`${requestName} returns a query result list`, function () {
        pm.expect(Array.isArray(body)).to.equal(true)
    })
    return
}

if (requestName === "Provider DSP Catalog Endpoint" || requestName === "Consumer DSP Catalog Endpoint") {
    if (status === 401 || status === 403) {
        pm.test(`${requestName} should not reject the configured connector credentials`, function () {
            pm.expect.fail(`${requestName} returned HTTP ${status}: ${responseText()}`)
        })
        return
    }

    pm.test(`${requestName} is reachable`, function () {
        pm.expect(status).to.be.oneOf([200, 400, 405])
    })
}
})(); // End of IIFE
