package org.upm.inesdata.registration_service.exception.model;

import java.io.Serializable;

/**
 * Interface for gauss error codes
 *
 * @author gmv
 */
public interface CoreErrorCode extends Serializable {

	/**
	 * Gets the error code
	 *
	 * @return {@link String} code of error
	 */
	String getCode();

	/**
	 * Gets the error status
	 *
	 * @return {@link Integer} status of error
	 */
	Integer getStatus();

}
