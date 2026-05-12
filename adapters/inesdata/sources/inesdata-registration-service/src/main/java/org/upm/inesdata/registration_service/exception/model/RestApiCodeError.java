package org.upm.inesdata.registration_service.exception.model;

/**
 * REST API enum for code errors of gauss-rest-api
 *
 * @author gmv
 */
public enum RestApiCodeError implements CoreErrorCode {

	/**
	 * Validation error
	 */
	VALIDATION("VALIDATION", 422);

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
	RestApiCodeError(String code, Integer status) {
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

}
