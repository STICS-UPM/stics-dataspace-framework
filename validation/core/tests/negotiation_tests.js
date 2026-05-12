/**
 * Contract negotiation tests
 * Used by:
 * 05_consumer_negotiation.json
 */
(function() {
const requestName = pm.info.requestName
const status = pm.response.code
const DEFAULT_NEGOTIATION_START_MAX_ATTEMPTS = 30
const DEFAULT_NEGOTIATION_STATUS_MAX_ATTEMPTS = 10

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

function scheduleRetryOrFail(requestToRepeat, attemptVar, maxAttemptsVar, defaultMaxAttempts, pendingTestName, failureTestName, failureReason, detail) {
    const maxAttempts = readPositiveInt(maxAttemptsVar, defaultMaxAttempts)
    const attempt = readPositiveInt(attemptVar, 0) + 1

    if (attempt < maxAttempts) {
        saveCollectionVar(attemptVar, String(attempt))
        pm.test(`${pendingTestName} (attempt ${attempt}/${maxAttempts})`, function () {
            pm.expect(true).to.be.true
        })
        if (detail) {
            console.log(detail)
        }
        console.log(`Retrying ${requestToRepeat}. Next attempt ${attempt + 1}/${maxAttempts}`)
        setNextRequestName(requestToRepeat)
        return true
    }

    clearLocalVar(attemptVar)
    pm.test(failureTestName, function () {
        pm.expect.fail(failureReason)
    })
    if (detail) {
        console.log(detail)
    }
    console.log(`Retry budget exhausted for ${requestToRepeat}: ${maxAttempts}/${maxAttempts}`)
    setNextRequestName(null)
    return false
}

function isTransientNegotiationStartStatus(code) {
    return [401, 403, 404, 409, 423, 429, 500, 502, 503, 504].includes(code)
}

function isTransientNegotiationStatusStatus(code) {
    return [401, 403, 404, 429, 500, 502, 503, 504].includes(code)
}

/**
 * Consumer authentication
 */
if (requestName === "Consumer Login") {
    const body = parseJsonResponse()
    if (!body) {
        return
    }
    assertFieldExists(body, "access_token")
    saveCollectionVar("consumer_jwt", body.access_token)
    return
}

if (requestName === "Start Contract Negotiation") {
    clearLocalVar("e2e_negotiation_id")
    clearLocalVar("e2e_agreement_id")
    clearLocalVar("e2e_negotiation_status_attempt")
    if (isTransientNegotiationStartStatus(status)) {
        scheduleRetryOrFail(
            "Start Contract Negotiation",
            "e2e_negotiation_start_attempt",
            "e2e_negotiation_start_max_attempts",
            DEFAULT_NEGOTIATION_START_MAX_ATTEMPTS,
            "Contract negotiation start is still stabilizing",
            "Contract negotiation could not be started after repeated checks",
            `Contract negotiation start kept returning HTTP ${status} before the retry budget was exhausted`,
            `Start Contract Negotiation returned HTTP ${status}: ${responseText()}`
        )
        return
    }
}

if (requestName === "Check Negotiation Status" && isTransientNegotiationStatusStatus(status)) {
    const negotiationId = getStoredVar("e2e_negotiation_id")
    scheduleRetryOrFail(
        "Check Negotiation Status",
        "e2e_negotiation_status_attempt",
        "e2e_negotiation_status_max_attempts",
        DEFAULT_NEGOTIATION_STATUS_MAX_ATTEMPTS,
        "Negotiation status endpoint is still stabilizing",
        "Negotiation status did not become available after repeated checks",
        `Negotiation ${negotiationId || "<unknown>"} kept returning HTTP ${status} before the retry budget was exhausted`,
        `Check Negotiation Status returned HTTP ${status}: ${responseText()}`
    )
    return
}

const body = parseJsonResponse()
if (!body) {
    console.log("No valid response body, skipping tests")
    return
}
assertNoEdcError(body)

/**
 * Contract negotiation start
 */
if (requestName === "Start Contract Negotiation") {
    clearLocalVar("e2e_negotiation_start_attempt")
    assertCreated()
    extractAtId(body, "e2e_negotiation_id")
    return
}
/**
 * Negotiation status check
 */
if (requestName === "Check Negotiation Status") {
    assertStatus200()
    const negotiationId = getStoredVar("e2e_negotiation_id")
    let negotiation = body
    if (Array.isArray(body)) {
        if (body.length === 0) {
            scheduleRetryOrFail(
                "Check Negotiation Status",
                "e2e_negotiation_status_attempt",
                "e2e_negotiation_status_max_attempts",
                DEFAULT_NEGOTIATION_STATUS_MAX_ATTEMPTS,
                "Current negotiation status is still pending because no negotiation entries are visible yet",
                "Negotiation status did not become visible after repeated checks",
                `Negotiation ${negotiationId || "<unknown>"} did not become visible in the status list before the retry budget was exhausted`,
                "Negotiation status list is empty"
            )
            return
        }
        negotiation = body.find(function (item) {
            return item && (item["@id"] === negotiationId || item.id === negotiationId)
        })
    }
    if (!negotiation) {
        scheduleRetryOrFail(
            "Check Negotiation Status",
            "e2e_negotiation_status_attempt",
            "e2e_negotiation_status_max_attempts",
            DEFAULT_NEGOTIATION_STATUS_MAX_ATTEMPTS,
            "Current negotiation status is still pending because the negotiation is not visible yet",
            "Negotiation status did not become visible after repeated checks",
            `Negotiation ${negotiationId || "<unknown>"} did not become visible in the status list before the retry budget was exhausted`,
            `Current negotiation status is pending for negotiation id: ${negotiationId || "<unknown>"}. Visible negotiation entries returned: ${Array.isArray(body) ? body.length : 1}`
        )
        return
    }
    assertFieldExists(negotiation, "state")
    const state = negotiation.state
    pm.test("Negotiation state is recognized by the framework", function () {
        pm.expect(state).to.be.oneOf([
            "INITIAL",
            "REQUESTED",
            "REQUESTING",
            "VERIFYING",
            "IN_PROGRESS",
            "AGREED",
            "VERIFIED",
            "FINALIZED",
            "TERMINATED"
        ])
    })
    if (state === "TERMINATED") {
        clearLocalVar("e2e_negotiation_status_attempt")
        const detailParts = [
            `Negotiation ${negotiationId || "<unknown>"} reached TERMINATED state`,
            `counterPartyId=${negotiation.counterPartyId || "<unknown>"}`,
            `counterPartyAddress=${negotiation.counterPartyAddress || "<unknown>"}`
        ]
        if (negotiation.errorDetail) {
            detailParts.push(`errorDetail=${negotiation.errorDetail}`)
        } else {
            detailParts.push("consumer-side errorDetail is empty; inspect provider-side negotiation detail")
        }
        pm.test("Negotiation did not end in a terminated state", function () {
            pm.expect.fail(detailParts.join("; "))
        })
        if (negotiation.errorDetail) {
            console.log("Negotiation error detail:", negotiation.errorDetail)
        } else {
            console.log("Negotiation terminated without consumer-side error detail. Provider-side diagnostics may contain the DSP error.")
        }
        setNextRequestName(null)
        return
    }
    const agreementId = negotiation.contractAgreementId
    if (agreementId) {
        clearLocalVar("e2e_negotiation_status_attempt")
        saveCollectionVar("e2e_agreement_id", agreementId)
        pm.test("Contract agreement generated", function () {
            pm.expect(agreementId).to.not.be.undefined
            pm.expect(agreementId).to.not.be.null
        })
    } else if (state === "FINALIZED") {
        scheduleRetryOrFail(
            "Check Negotiation Status",
            "e2e_negotiation_status_attempt",
            "e2e_negotiation_status_max_attempts",
            DEFAULT_NEGOTIATION_STATUS_MAX_ATTEMPTS,
            "Negotiation is finalized but the contract agreement is not visible yet",
            "Finalized negotiation did not expose a contract agreement after repeated checks",
            `Negotiation ${negotiationId || "<unknown>"} stayed FINALIZED without contractAgreementId before the retry budget was exhausted`,
            "Negotiation reached FINALIZED without contractAgreementId"
        )
    } else {
        scheduleRetryOrFail(
            "Check Negotiation Status",
            "e2e_negotiation_status_attempt",
            "e2e_negotiation_status_max_attempts",
            DEFAULT_NEGOTIATION_STATUS_MAX_ATTEMPTS,
            "Negotiation is still progressing and may not have produced a contract agreement yet",
            "Negotiation did not produce a contract agreement before the retry budget was exhausted",
            `Negotiation ${negotiationId || "<unknown>"} remained in state ${state || "unknown"} before the retry budget was exhausted`,
            `Negotiation is still progressing in state ${state || "unknown"}`
        )
        if (negotiation.errorDetail) {
            console.log("Negotiation error detail:", negotiation.errorDetail)
        }
    }
}
})(); // End of IIFE
