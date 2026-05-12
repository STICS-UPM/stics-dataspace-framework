package org.upm.inesdata.registration_service.exception.model;

import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.io.Serial;
import java.io.Serializable;

/**
 * Error response data for fields validations
 *
 * @author gmv
 */

@Data
@NoArgsConstructor
public class ErrorValidation implements Serializable {

	@Serial
	private static final long serialVersionUID = 3904372875916968293L;

	/**
	 * the name of field
	 */
	@Schema(description = "Field name")
	private String field;
	/**
	 * the code of validation
	 */
	@Schema(description = "Validation code")
	private String code;
	/**
	 * the details of validation
	 */
	@Schema(description = "Validation details")
	private String details;

	/**
	 * Constructor
	 *
	 * @param field
	 * 		the name of field
	 * @param code
	 * 		the code of validation
	 * @param details
	 * 		the details of validation
	 */
	public ErrorValidation(@JsonProperty("field") String field, @JsonProperty("code") String code,
			@JsonProperty("details") String details) {
		this.field = field;
		this.code = code;
		this.details = details;
	}

}
