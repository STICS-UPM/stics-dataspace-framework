package org.upm.inesdata.registration_service.exception.model;

import com.fasterxml.jackson.annotation.JsonInclude;
import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.io.Serial;
import java.io.Serializable;
import java.util.ArrayList;
import java.util.List;

/**
 * Error response data for REST API
 *
 * @author gmv
 */
@Data
@NoArgsConstructor
@Schema(description = "Error response")
public class ErrorResponse implements Serializable {

	@Serial
	private static final long serialVersionUID = 2721651714907098912L;

	/**
	 * the code of error
	 */
	@Schema(description = "Error code")
	private String code;
	/**
	 * the status of error
	 */
	@Schema(description = "Error status")
	private int status;
	/**
	 * the message of error
	 */
	@Schema(description = "Error message")
	private String message;
	/**
	 * the details of error
	 */
	@Schema(description = "Error details")
	@JsonInclude(JsonInclude.Include.NON_EMPTY)
	private String details;
	/**
	 * the list of invalid parameters
	 */
	@Schema(description = "Invalid parameters")
	@JsonInclude(JsonInclude.Include.NON_EMPTY)
	private List<ErrorValidation> invalidParams;

	/**
	 * Constructor
	 *
	 * @param code
	 * 		the code of error
	 * @param message
	 * 		the message of error
	 * @param details
	 * 		the details of error
	 */
	public ErrorResponse(CoreErrorCode code, String message, String details) {
		super();
		this.code = code.getCode();
		this.status = code.getStatus();
		this.message = message;
		this.details = details;
	}

	/**
	 * Constructor
	 *
	 * @param code
	 * 		the code of error
	 * @param message
	 * 		the message of error
	 * @param invalidParams
	 * 		the list of invalid parameters
	 */
	public ErrorResponse(CoreErrorCode code, String message, List<ErrorValidation> invalidParams) {
		super();
		this.code = code.getCode();
		this.status = code.getStatus();
		this.message = message;
		this.invalidParams = new ArrayList<>(invalidParams);
	}


}
