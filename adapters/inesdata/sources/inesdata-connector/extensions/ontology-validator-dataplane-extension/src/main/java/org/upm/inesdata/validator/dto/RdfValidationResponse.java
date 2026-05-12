package org.upm.inesdata.validator.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Response DTO for RDF validation callback.
 *
 * Example:
 * {
 *   "transferId": "transfer-123",
 *   "valid": true,
 *   "message": "Validation passed"
 * }
 */
public class RdfValidationResponse {

    @JsonProperty("transferId")
    private String transferId;

    @JsonProperty("valid")
    private boolean valid;

    @JsonProperty("message")
    private String message;

    public RdfValidationResponse() {
    }

    public RdfValidationResponse(String transferId, boolean valid, String message) {
        this.transferId = transferId;
        this.valid = valid;
        this.message = message;
    }

    public String getTransferId() {
        return transferId;
    }

    public void setTransferId(String transferId) {
        this.transferId = transferId;
    }

    public boolean isValid() {
        return valid;
    }

    public void setValid(boolean valid) {
        this.valid = valid;
    }

    public String getMessage() {
        return message;
    }

    public void setMessage(String message) {
        this.message = message;
    }
}

