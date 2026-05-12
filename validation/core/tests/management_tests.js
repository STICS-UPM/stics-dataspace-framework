/**
 * Management API tests
 * Used by:
 * 02_connector_management_api.json
 */
(function() {
const requestName = pm.info.requestName
const isDeleteRequest = requestName.indexOf("Delete ") === 0
const body = isDeleteRequest ? null : parseJsonResponse()

if (requestName === "Provider Login") {
    assertStatus200()
    if (!body) {
        return
    }
    assertFieldExists(body, "access_token")
    saveCollectionVar("provider_jwt", body.access_token)

    const suffix = String(Date.now())
    saveCollectionVar("crud_suffix", suffix)
    saveCollectionVar("crud_asset_id", `asset-crud-${suffix}`)
    saveCollectionVar("crud_policy_id", `policy-crud-${suffix}`)
    saveCollectionVar("crud_contract_definition_id", `contract-crud-${suffix}`)
    return
}

if (!body && !isDeleteRequest) {
    console.log("No valid response body, skipping tests")
    return
}

assertNoEdcError(body)

if (requestName === "Create CRUD Asset") {
    assertCreated()
    extractAtId(body, "crud_asset_id")
    return
}

if (requestName === "List CRUD Assets") {
    assertStatus200()
    const assetId = pm.collectionVariables.get("crud_asset_id")
    assertNotEmpty(assetId, "crud_asset_id")
    pm.test("CRUD asset appears in asset lookup result", function () {
        pm.expect(Array.isArray(body)).to.equal(true)
        pm.expect(body.some((asset) => asset && asset["@id"] === assetId)).to.equal(true)
    })
    return
}

if (requestName === "Create CRUD Policy") {
    assertCreated()
    extractAtId(body, "crud_policy_id")
    return
}

if (requestName === "List CRUD Policies") {
    assertStatus200()
    const policyId = pm.collectionVariables.get("crud_policy_id")
    assertNotEmpty(policyId, "crud_policy_id")
    pm.test("CRUD policy appears in policy lookup result", function () {
        pm.expect(Array.isArray(body)).to.equal(true)
        pm.expect(body.some((policy) => policy && policy["@id"] === policyId)).to.equal(true)
    })
    return
}

if (requestName === "Create CRUD Contract Definition") {
    assertCreated()
    extractAtId(body, "crud_contract_definition_id")
    return
}

if (requestName === "List CRUD Contract Definitions") {
    assertStatus200()
    const contractId = pm.collectionVariables.get("crud_contract_definition_id")
    assertNotEmpty(contractId, "crud_contract_definition_id")
    pm.test("CRUD contract definition appears in lookup result", function () {
        pm.expect(Array.isArray(body)).to.equal(true)
        pm.expect(body.some((contract) => contract && contract["@id"] === contractId)).to.equal(true)
    })
    return
}

if (requestName === "Delete CRUD Contract Definition") {
    pm.test("CRUD contract definition deletion completed", function () {
        pm.expect(pm.response.code).to.be.oneOf([200, 204])
    })
    return
}

if (requestName === "Verify CRUD Contract Definition Deleted") {
    assertStatus200()
    const contractId = pm.collectionVariables.get("crud_contract_definition_id")
    assertNotEmpty(contractId, "crud_contract_definition_id")
    pm.test("CRUD contract definition no longer appears in lookup result", function () {
        pm.expect(Array.isArray(body)).to.equal(true)
        pm.expect(body.some((contract) => contract && contract["@id"] === contractId)).to.equal(false)
    })
    return
}

if (requestName === "Delete CRUD Policy") {
    pm.test("CRUD policy deletion completed", function () {
        pm.expect(pm.response.code).to.be.oneOf([200, 204])
    })
    return
}

if (requestName === "Verify CRUD Policy Deleted") {
    assertStatus200()
    const policyId = pm.collectionVariables.get("crud_policy_id")
    assertNotEmpty(policyId, "crud_policy_id")
    pm.test("CRUD policy no longer appears in lookup result", function () {
        pm.expect(Array.isArray(body)).to.equal(true)
        pm.expect(body.some((policy) => policy && policy["@id"] === policyId)).to.equal(false)
    })
    return
}

if (requestName === "Delete CRUD Asset") {
    pm.test("CRUD asset deletion completed", function () {
        pm.expect(pm.response.code).to.be.oneOf([200, 204])
    })
    return
}

if (requestName === "Verify CRUD Asset Deleted") {
    assertStatus200()
    const assetId = pm.collectionVariables.get("crud_asset_id")
    assertNotEmpty(assetId, "crud_asset_id")
    pm.test("CRUD asset no longer appears in lookup result", function () {
        pm.expect(Array.isArray(body)).to.equal(true)
        pm.expect(body.some((asset) => asset && asset["@id"] === assetId)).to.equal(false)
    })
    return
}
})(); // End of IIFE
