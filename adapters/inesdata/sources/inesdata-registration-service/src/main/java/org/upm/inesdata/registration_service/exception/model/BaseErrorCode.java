package org.upm.inesdata.registration_service.exception.model;

import java.util.Arrays;

/**
 * Default enum for gauss error codes
 *
 * @author gmv
 */
public enum BaseErrorCode implements CoreErrorCode {

	/**
	 * Unexpected error
	 */
	UNEXPECTED_ERROR("UNEXPECTED_ERROR", 500),

	/**
	 * Service unavailable
	 */
	SERVICE_UNAVAILABLE("SERVICE_UNAVAILABLE", 503),

	/**
	 * Some register, object or configuration not found
	 */
	NOT_FOUND("NOT_FOUND", 404),

	/**
	 * Unauthorized
	 */
	UNAUTHORIZED("UNAUTHORIZED", 401),

	/**
	 * Forbidden
	 */
	FORBIDDEN("FORBIDDEN", 403),

	/**
	 * Bad request
	 */
	BAD_REQUEST("BAD_REQUEST", 400),

	/**
	 * Received a null data in a required param
	 */
	NULL_DATA("NULL_DATA", 400),

	/**
	 * Incorrect format
	 */
	WRONG_FORMAT("WRONG_FORMAT", 400),
	UNPROCESSABLE_ENTITY("UNPROCCESABLE_ENTITY", 422),

	/**
	 * Business Key
	 */
	BUSINESS_KEY("BUSINESS_KEY", 500);

	/**
	 * Code error
	 */
	private final String code;

	/**
	 * Status error
	 */
	private final Integer status;

	/**
	 * Private constructor
	 *
	 * @param code
	 * 		error code
	 * @param status
	 * 		error estatus
	 */
	BaseErrorCode(String code, Integer status) {
		this.code = code;
		this.status = status;
	}

	/**
	 * (non-javadoc)
	 *
	 * @see CoreErrorCode#getCode()
	 */
	@Override
	public String getCode() {
		return code;
	}

	/**
	 * (non-javadoc)
	 *
	 * @see CoreErrorCode#getStatus()
	 */
	@Override
	public Integer getStatus() {
		return status;
	}

	/**
	 * Find an enum value by status. If a status is assigned to multiple enum values, get the first occurrence
	 *
	 * @param status
	 * 		the status
	 *
	 * @return {@link CoreErrorCode} enum value
	 */
	public static CoreErrorCode getByStatus(Integer status) {
		// @formatter:off
		return Arrays.stream(BaseErrorCode.values())
				.filter(i -> i.getStatus().equals(status)).findFirst()
				.orElse(BaseErrorCode.UNEXPECTED_ERROR);
		// @formatter:on
	}
}
