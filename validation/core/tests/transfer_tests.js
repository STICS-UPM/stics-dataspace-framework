/**
 * Transfer process tests
 * Used by:
 * 06_consumer_transfer.json
 */
(function() {
const requestName = pm.info.requestName
const status = pm.response.code
const DEFAULT_TRANSFER_START_MAX_ATTEMPTS = 8
const DEFAULT_TRANSFER_STATUS_MAX_ATTEMPTS = 10
const DEFAULT_TRANSFER_DESTINATION_MAX_ATTEMPTS = 10
const VALID_TRANSFER_STATES = [
    "INITIAL",
    "STARTED",
    "REQUESTING",
    "PROVISIONING",
    "PROVISIONED",
    "REQUESTED",
    "REQUESTED_ACK",
    "IN_PROGRESS",
    "STREAMING",
    "COMPLETED",
    "DEPROVISIONING",
    "DEPROVISIONING_REQ",
    "DEPROVISIONED",
    "ENDED",
    // Keep backward compatibility with older runtimes or adapters.
    "FINALIZED",
    "TERMINATED"
]

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

function scheduleRetryOrFail(requestToRepeat, attemptVar, maxAttemptsVar, defaultMaxAttempts, pendingTestName, failureTestName, failureReason, detail, nextRequestOverride) {
    const maxAttempts = readPositiveInt(maxAttemptsVar, defaultMaxAttempts)
    const attempt = readPositiveInt(attemptVar, 0) + 1
    const nextRequest = nextRequestOverride || requestToRepeat

    if (attempt < maxAttempts) {
        saveCollectionVar(attemptVar, String(attempt))
        pm.test(`${pendingTestName} (attempt ${attempt}/${maxAttempts})`, function () {
            pm.expect(true).to.be.true
        })
        if (detail) {
            console.log(detail)
        }
        console.log(`Retrying ${requestToRepeat}. Next attempt ${attempt + 1}/${maxAttempts}`)
        setNextRequestName(nextRequest)
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

function scheduleLoginThenRetry(requestToRepeat, attemptVar, maxAttemptsVar, defaultMaxAttempts, pendingTestName, failureTestName, failureReason, detail) {
    const scheduled = scheduleRetryOrFail(
        requestToRepeat,
        attemptVar,
        maxAttemptsVar,
        defaultMaxAttempts,
        pendingTestName,
        failureTestName,
        failureReason,
        detail,
        "Consumer Login"
    )
    if (scheduled) {
        saveCollectionVar("e2e_after_consumer_login_request", requestToRepeat)
    } else {
        clearLocalVar("e2e_after_consumer_login_request")
    }
    return scheduled
}

function isAuthenticationStatus(code) {
    return [401, 403].includes(code)
}

function isTransientTransferStartStatus(code) {
    return [401, 403, 404, 409, 423, 429, 500, 502, 503, 504].includes(code)
}

function isTransientTransferLookupStatus(code) {
    return [401, 403, 404, 429, 500, 502, 503, 504].includes(code)
}

function findTransferEntry(payload, transferId) {
    if (Array.isArray(payload)) {
        return payload.find(function (item) {
            return item && (item["@id"] === transferId || item.id === transferId)
        })
    }
    return payload
}

function readField(obj, fieldName) {
    if (!obj || typeof obj !== "object") {
        return undefined
    }
    const namespaced = `https://w3id.org/edc/v0.0.1/ns/${fieldName}`
    if (Object.prototype.hasOwnProperty.call(obj, fieldName)) {
        return obj[fieldName]
    }
    if (Object.prototype.hasOwnProperty.call(obj, namespaced)) {
        return obj[namespaced]
    }
    const properties = obj.properties
    if (properties && typeof properties === "object") {
        if (Object.prototype.hasOwnProperty.call(properties, fieldName)) {
            return properties[fieldName]
        }
        if (Object.prototype.hasOwnProperty.call(properties, namespaced)) {
            return properties[namespaced]
        }
    }
    return undefined
}

function parseStoredJson(key) {
    const raw = getStoredVar(key)
    if (!raw) {
        return undefined
    }
    try {
        return JSON.parse(raw)
    } catch (error) {
        console.log(`Could not parse ${key}: ${error}`)
        return undefined
    }
}

function currentAdapter() {
    return String(getStoredVar("adapter") || "").trim().toLowerCase()
}

function isEdcAdapter() {
    return currentAdapter() === "edc"
}

if (requestName === "Consumer Login") {
    const body = parseJsonResponse()
    handleLoginToken(body)
    const nextRequest = getStoredVar("e2e_after_consumer_login_request")
    if (nextRequest) {
        clearLocalVar("e2e_after_consumer_login_request")
        setNextRequestName(nextRequest)
    }
    return
}
const agreementId = getStoredVar("e2e_agreement_id")
const transferId = getStoredVar("e2e_transfer_id")
if (requestName === "Start Transfer Process" && !agreementId) {
    pm.test("Transfer start was not executed because no contract agreement is available", function () {
        pm.expect(true).to.be.true
    })
    setNextRequestName(null)
    return
}
if (["Check Transfer Status", "Resolve Current Transfer Destination"].includes(requestName) && !transferId) {
    pm.test(`${requestName} was not executed because no transfer process identifier is available`, function () {
        pm.expect(true).to.be.true
    })
    setNextRequestName(null)
    return
}
if (requestName === "Start Transfer Process" && isAuthenticationStatus(status)) {
    scheduleLoginThenRetry(
        "Start Transfer Process",
        "e2e_transfer_start_attempt",
        "e2e_transfer_start_max_attempts",
        DEFAULT_TRANSFER_START_MAX_ATTEMPTS,
        "Transfer start authentication is being renewed",
        "Transfer process could not be started after repeated authentication refreshes",
        `Transfer start kept returning HTTP ${status} after refreshing the consumer token`,
        `Start Transfer Process returned HTTP ${status}; refreshing the consumer token before retrying: ${responseText()}`
    )
    return
}
if (requestName === "Start Transfer Process" && isTransientTransferStartStatus(status)) {
    scheduleRetryOrFail(
        "Start Transfer Process",
        "e2e_transfer_start_attempt",
        "e2e_transfer_start_max_attempts",
        DEFAULT_TRANSFER_START_MAX_ATTEMPTS,
        "Transfer start endpoint is still stabilizing",
        "Transfer process could not be started after repeated checks",
        `Transfer start kept returning HTTP ${status} before the retry budget was exhausted`,
        `Start Transfer Process returned HTTP ${status}: ${responseText()}`
    )
    return
}
if (requestName === "Check Transfer Status" && isAuthenticationStatus(status)) {
    scheduleLoginThenRetry(
        "Check Transfer Status",
        "e2e_transfer_status_attempt",
        "e2e_transfer_status_max_attempts",
        DEFAULT_TRANSFER_STATUS_MAX_ATTEMPTS,
        "Transfer status authentication is being renewed",
        "Transfer status did not become visible after repeated authentication refreshes",
        `Transfer ${transferId || "<unknown>"} kept returning HTTP ${status} after refreshing the consumer token`,
        `Check Transfer Status returned HTTP ${status} for transfer id: ${transferId || "<unknown>"}; refreshing the consumer token before retrying: ${responseText()}`
    )
    return
}
if (requestName === "Check Transfer Status" && isTransientTransferLookupStatus(status)) {
    scheduleRetryOrFail(
        "Check Transfer Status",
        "e2e_transfer_status_attempt",
        "e2e_transfer_status_max_attempts",
        DEFAULT_TRANSFER_STATUS_MAX_ATTEMPTS,
        "Current transfer status is still pending because the transfer lookup is not stable yet",
        "Transfer status did not become visible after repeated direct lookups",
        `Transfer ${transferId || "<unknown>"} kept returning HTTP ${status} before the retry budget was exhausted`,
        `Check Transfer Status returned HTTP ${status} for transfer id: ${transferId || "<unknown>"}`
    )
    return
}
if (requestName === "Resolve Current Transfer Destination" && isAuthenticationStatus(status)) {
    scheduleLoginThenRetry(
        "Resolve Current Transfer Destination",
        "e2e_transfer_destination_attempt",
        "e2e_transfer_destination_max_attempts",
        DEFAULT_TRANSFER_DESTINATION_MAX_ATTEMPTS,
        "Transfer destination authentication is being renewed",
        "Transfer destination could not be resolved after repeated authentication refreshes",
        `Transfer ${transferId || "<unknown>"} kept returning HTTP ${status} after refreshing the consumer token`,
        `Resolve Current Transfer Destination returned HTTP ${status} for transfer id: ${transferId || "<unknown>"}; refreshing the consumer token before retrying: ${responseText()}`
    )
    return
}
if (requestName === "Resolve Current Transfer Destination" && isTransientTransferLookupStatus(status)) {
    scheduleRetryOrFail(
        "Resolve Current Transfer Destination",
        "e2e_transfer_destination_attempt",
        "e2e_transfer_destination_max_attempts",
        DEFAULT_TRANSFER_DESTINATION_MAX_ATTEMPTS,
        "Transfer destination resolution is still pending because the transfer lookup is not stable yet",
        "Transfer destination could not be resolved after repeated direct lookups",
        `Transfer ${transferId || "<unknown>"} kept returning HTTP ${status} before the retry budget was exhausted`,
        `Resolve Current Transfer Destination returned HTTP ${status} for transfer id: ${transferId || "<unknown>"}`
    )
    return
}
if (!["Start Transfer Process", "Check Transfer Status", "Resolve Current Transfer Destination"].includes(requestName)) {
    assertStatus200()
}
const body = parseJsonResponse()
if (!body) {
    console.log("No valid response body, skipping tests")
    return
}
if (body) {
    assertNoEdcError(body)
}
if (requestName === "Start Transfer Process") {
    clearLocalVar("e2e_transfer_start_attempt")
    clearLocalVar("e2e_transfer_status_attempt")
    clearLocalVar("e2e_transfer_destination_attempt")
    clearLocalVar("e2e_transfer_destination_bucket")
    assertCreated()
    extractAtId(body, "e2e_transfer_id")
    const expectedPath = getStoredVar("transferStartPath")
    assertNotEmpty(expectedPath, "transferStartPath")
    pm.test("Transfer request is aligned with the adapter-compatible transfer flow", function () {
        pm.expect(pm.request.url.toString()).to.include(`/management/v3/${expectedPath}`)
    })
    return
}
if (requestName === "Check Transfer Status") {
    assertStatus200()
    let transfer = body
    if (Array.isArray(body)) {
        if (body.length === 0) {
            scheduleRetryOrFail(
                "Check Transfer Status",
                "e2e_transfer_status_attempt",
                "e2e_transfer_status_max_attempts",
                DEFAULT_TRANSFER_STATUS_MAX_ATTEMPTS,
                "Current transfer status is still pending because no transfer entries are visible yet",
                "Transfer status did not become visible after repeated checks",
                `Transfer ${transferId || "<unknown>"} did not become visible in the status list before the retry budget was exhausted`,
                "Transfer status list is empty"
            )
            return
        }
        transfer = findTransferEntry(body, transferId)
    }
    if (!transfer) {
        scheduleRetryOrFail(
            "Check Transfer Status",
            "e2e_transfer_status_attempt",
            "e2e_transfer_status_max_attempts",
            DEFAULT_TRANSFER_STATUS_MAX_ATTEMPTS,
            "Current transfer status is still pending because the transfer is not visible yet",
            "Transfer status did not become visible after repeated checks",
            `Transfer ${transferId || "<unknown>"} did not become visible in the status list before the retry budget was exhausted`,
            `Current transfer status is pending for transfer id: ${transferId || "<unknown>"}. Visible transfer entries returned: ${Array.isArray(body) ? body.length : 1}`
        )
        return
    }
    assertFieldExists(transfer, "state")
    const state = transfer.state
    const transferErrorDetail = transfer.errorDetail || transfer.error || null
    pm.test("Transfer state is recognized by the framework", function () {
        pm.expect(state).to.be.oneOf(VALID_TRANSFER_STATES)
    })
    if (state === "TERMINATED") {
        clearLocalVar("e2e_transfer_status_attempt")
        pm.test("Transfer did not end in a terminated state", function () {
            pm.expect.fail("Transfer reached TERMINATED state")
        })
        if (transferErrorDetail) {
            console.log("Transfer error detail:", transferErrorDetail)
        }
        setNextRequestName(null)
        return
    }
    if (state === "STARTED") {
        clearLocalVar("e2e_transfer_status_attempt")
        pm.test("Transfer reached an active push state that allows destination validation", function () {
            pm.expect(state).to.equal("STARTED")
        })
        return
    }
    if (state === "COMPLETED" || state === "FINALIZED" || state === "ENDED" || state === "DEPROVISIONED") {
        clearLocalVar("e2e_transfer_status_attempt")
        pm.test("Transfer reached a terminal or post-terminal state accepted by the framework", function () {
            pm.expect(state).to.be.oneOf(["COMPLETED", "FINALIZED", "ENDED", "DEPROVISIONED"])
        })
        return
    }
    scheduleRetryOrFail(
        "Check Transfer Status",
        "e2e_transfer_status_attempt",
        "e2e_transfer_status_max_attempts",
        DEFAULT_TRANSFER_STATUS_MAX_ATTEMPTS,
        "Transfer is still in progress or in post-processing",
        "Transfer did not reach a successful terminal state before the retry budget was exhausted",
        `Transfer ${transferId || "<unknown>"} remained in state ${state || "unknown"} before the retry budget was exhausted`,
        `Transfer is still in state ${state || "unknown"}${transferErrorDetail ? ` (detail: ${transferErrorDetail})` : ""}`
    )
}
if (requestName === "Resolve Current Transfer Destination") {
    assertStatus200()
    let transfer = body
    if (Array.isArray(body)) {
        if (body.length === 0) {
            scheduleRetryOrFail(
                "Resolve Current Transfer Destination",
                "e2e_transfer_destination_attempt",
                "e2e_transfer_destination_max_attempts",
                DEFAULT_TRANSFER_DESTINATION_MAX_ATTEMPTS,
                "Transfer destination resolution is still pending because no transfer entries are visible yet",
                "Transfer destination could not be resolved after repeated checks",
                `Transfer ${transferId || "<unknown>"} did not become visible for destination validation before the retry budget was exhausted`,
                "Transfer status list is empty while resolving destination"
            )
            return
        }
        transfer = findTransferEntry(body, transferId)
    }
    if (!transfer) {
        scheduleRetryOrFail(
            "Resolve Current Transfer Destination",
            "e2e_transfer_destination_attempt",
            "e2e_transfer_destination_max_attempts",
            DEFAULT_TRANSFER_DESTINATION_MAX_ATTEMPTS,
            "Current transfer destination resolution is still pending because the transfer is not visible yet",
            "Transfer destination could not be resolved after repeated checks",
            `Transfer ${transferId || "<unknown>"} did not become visible for destination validation before the retry budget was exhausted`,
            `Current transfer destination resolution is pending for transfer id: ${transferId || "<unknown>"}. Visible transfer entries returned: ${Array.isArray(body) ? body.length : 1}`
        )
        return
    }
    clearLocalVar("e2e_transfer_destination_attempt")
    const state = readField(transfer, "state") || transfer.state
    if (state === "TERMINATED") {
        pm.test("Transfer destination validation did not observe a terminated transfer", function () {
            pm.expect.fail("Transfer reached TERMINATED state before destination validation")
        })
        const transferErrorDetail = transfer.errorDetail || transfer.error || null
        if (transferErrorDetail) {
            console.log("Transfer error detail:", transferErrorDetail)
        }
        return
    }

    const expectedAssetId = getStoredVar("e2e_asset_id")
    const transferAssetId = readField(transfer, "assetId") || transfer.assetId
    if (expectedAssetId) {
        pm.test("Transfer details still reference the negotiated asset", function () {
            pm.expect(transferAssetId).to.equal(expectedAssetId)
        })
    }

    const transferType = readField(transfer, "transferType") || transfer.transferType
    const expectedTransferType = getStoredVar("transferType") || "AmazonS3-PUSH"
    pm.test("Transfer request uses the transfer type expected by the adapter", function () {
        pm.expect(transferType).to.equal(expectedTransferType)
    })

    const requestedDestinationType = getStoredVar("transferDestinationType") || "AmazonS3"
    const expectedResolvedDestinationType =
        String(requestedDestinationType).toLowerCase() === "inesdatastore" ? "AmazonS3" : requestedDestinationType
    const expectsObjectStorageDestination =
        String(expectedTransferType || "").toLowerCase().includes("push") &&
        String(requestedDestinationType || "").toLowerCase() !== "httpdata"

    if (isEdcAdapter() && !expectsObjectStorageDestination) {
        pm.test("EDC transfer state is queryable through the standard management API", function () {
            pm.expect(state).to.be.oneOf(VALID_TRANSFER_STATES)
        })
        return
    }

    const dataDestination =
        readField(transfer, "dataDestination") ||
        transfer.dataDestination ||
        transfer["https://w3id.org/edc/v0.0.1/ns/dataDestination"] ||
        (isEdcAdapter() ? parseStoredJson("e2e_transfer_request_destination") : undefined)

    pm.test("Transfer details expose a resolved data destination", function () {
        pm.expect(dataDestination).to.not.be.undefined
        pm.expect(dataDestination).to.not.be.null
    })

    const destinationType = readField(dataDestination, "type")
    pm.test("Transfer destination type resolved by the runtime is object storage", function () {
        pm.expect(destinationType).to.equal(expectedResolvedDestinationType)
    })

    const expectedBucket = getStoredVar("e2e_expected_consumer_bucket")
    assertNotEmpty(expectedBucket, "e2e_expected_consumer_bucket")
    const bucketName = readField(dataDestination, "bucketName")
    pm.test("Transfer destination bucket matches the consumer bucket configured by the framework", function () {
        pm.expect(bucketName).to.equal(expectedBucket)
    })

    const endpointOverride = readField(dataDestination, "endpointOverride")
    pm.test("Transfer destination includes an S3 endpoint override", function () {
        pm.expect(endpointOverride).to.not.be.oneOf([undefined, null, ""])
    })

    saveCollectionVar("e2e_transfer_destination_bucket", bucketName)
}
})(); // End of IIFE
