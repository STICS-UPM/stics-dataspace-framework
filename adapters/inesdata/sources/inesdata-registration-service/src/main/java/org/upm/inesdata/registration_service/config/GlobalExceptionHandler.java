package org.upm.inesdata.registration_service.config;

import jakarta.validation.ConstraintViolationException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.AuthenticationException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ControllerAdvice;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.context.request.WebRequest;
import org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler;
import org.upm.inesdata.registration_service.exception.model.BaseErrorCode;
import org.upm.inesdata.registration_service.exception.DataValidationException;
import org.upm.inesdata.registration_service.exception.model.ErrorResponse;

import java.util.NoSuchElementException;

import static org.springframework.http.HttpStatus.BAD_REQUEST;
import static org.springframework.http.HttpStatus.FORBIDDEN;
import static org.springframework.http.HttpStatus.INTERNAL_SERVER_ERROR;
import static org.springframework.http.HttpStatus.METHOD_NOT_ALLOWED;
import static org.springframework.http.HttpStatus.NOT_FOUND;
import static org.springframework.http.HttpStatus.UNAUTHORIZED;
import static org.springframework.http.HttpStatus.UNPROCESSABLE_ENTITY;
import static org.springframework.http.HttpStatus.UNSUPPORTED_MEDIA_TYPE;
import static org.upm.inesdata.registration_service.exception.HttpStatusUtil.httpStatusException;

/**
 * Global exception handler
 *
 * @author gmv
 */
@ControllerAdvice
public class GlobalExceptionHandler extends ResponseEntityExceptionHandler {

    /**
     * Exception handler for {@link IllegalArgumentException}
     *
     * @param ex
     *        {@link IllegalArgumentException} the exception
     *
     * @return {@link ResponseEntity}&lt;{@link ErrorResponse}&gt; the error response
     */
    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<ErrorResponse> handleIllegalArgumentException(IllegalArgumentException ex) {
        return buildResponse(ex, BaseErrorCode.BAD_REQUEST.getCode(), BAD_REQUEST);
    }

    /**
     * Exception handler for {@link ConstraintViolationException}
     *
     * @param ex
     *        {@link ConstraintViolationException} the exception
     *
     * @return {@link ResponseEntity}&lt;{@link ErrorResponse}&gt; the error response
     */
    @ExceptionHandler(ConstraintViolationException.class)
    public final ResponseEntity<ErrorResponse> handleConstraintViolationException(ConstraintViolationException ex) {
        return addContext(ex, new DataValidationException(ex).getErrorResponse());
    }


    /**
     * Exception handler for {@link DataValidationException}
     *
     * @param ex
     *        {@link DataValidationException} the exception
     *
     * @return {@link ResponseEntity}&lt;{@link ErrorResponse}&gt; the error response
     */
    @ExceptionHandler(DataValidationException.class)
    public final ResponseEntity<ErrorResponse> handleDataValidationException(DataValidationException ex) {
        return buildResponse(ex, BaseErrorCode.UNPROCESSABLE_ENTITY.name(), UNPROCESSABLE_ENTITY);
    }

    /**
     * Exception handler for {@link NoSuchElementException}
     *
     * @param ex
     *        {@link NoSuchElementException} the exception
     *
     * @return {@link ResponseEntity}&lt;{@link ErrorResponse}&gt; the error response
     */
    @ExceptionHandler(NoSuchElementException.class)
    public final ResponseEntity<ErrorResponse> handleNotFoundException(NoSuchElementException ex) {
        return buildResponse(ex, BaseErrorCode.NOT_FOUND.name(), NOT_FOUND);
    }

    /**
     * Exception handler for {@link AuthenticationException}
     *
     * @param ex
     *        {@link AuthenticationException} the exception
     *
     * @return {@link ResponseEntity}&lt;{@link ErrorResponse}&gt; the error response
     */
    @ExceptionHandler(AuthenticationException.class)
    public final ResponseEntity<ErrorResponse> handleAuthenticationException(AuthenticationException ex) {
        return buildResponse(ex, BaseErrorCode.UNAUTHORIZED.name(), UNAUTHORIZED);
    }

    /**
     * Exception handler for {@link AccessDeniedException}
     * <p>
     * FORBIDDEN(403, "Forbiddden")
     *
     * @param ex
     *        {@link AuthenticationException} the exception
     *
     * @return {@link ResponseEntity}&lt;{@link ErrorResponse}&gt; the error response
     */
    @ExceptionHandler(AccessDeniedException.class)
    public final ResponseEntity<ErrorResponse> handleAccessDeniedException(AccessDeniedException ex) {
        return buildResponse(ex, BaseErrorCode.FORBIDDEN.name(), FORBIDDEN);
    }

    /**
     * Exception handler for {@link Exception}
     *
     * @param ex
     *        {@link Exception} the exception
     * @param request
     *        {@link WebRequest} the request
     *
     * @return {@link ResponseEntity}&lt;{@link ErrorResponse}&gt; the error response
     */
    @ExceptionHandler(Exception.class)
    public final ResponseEntity<ErrorResponse> handleExceptionCustom(Exception ex, WebRequest request) {
        return buildResponse(ex, BaseErrorCode.UNEXPECTED_ERROR.name(), httpStatusException(ex));
    }

    /**
     * (non-javadoc)
     *
     * @see ResponseEntityExceptionHandler#handleMethodArgumentNotValid(MethodArgumentNotValidException, HttpHeaders, HttpStatusCode, WebRequest)
     */
    @Override
    protected ResponseEntity<Object> handleMethodArgumentNotValid(MethodArgumentNotValidException ex, HttpHeaders headers,
        HttpStatusCode status, WebRequest request) {
        return (ResponseEntity) addContext(ex, new DataValidationException(ex).getErrorResponse());
    }

    /**
     * Overridden from the parent class to customize responses for some exceptions
     *
     * @see ResponseEntityExceptionHandler#handleExceptionInternal(Exception, Object, HttpHeaders, HttpStatusCode, WebRequest)
     */
    @Override
    protected ResponseEntity handleExceptionInternal(Exception ex, Object body, HttpHeaders headers, HttpStatusCode statusCode,
        WebRequest request) {
        if (statusCode instanceof HttpStatus status) {
            return switch (status) {
                case BAD_REQUEST -> buildResponse(ex, BaseErrorCode.BAD_REQUEST.name(), BAD_REQUEST);
                case NOT_FOUND -> buildResponse(ex, BaseErrorCode.NOT_FOUND.name(), NOT_FOUND);
                case METHOD_NOT_ALLOWED -> buildResponse(ex, BaseErrorCode.BAD_REQUEST.name(), METHOD_NOT_ALLOWED);
                case UNSUPPORTED_MEDIA_TYPE -> buildResponse(ex, BaseErrorCode.BAD_REQUEST.name(), UNSUPPORTED_MEDIA_TYPE);
                case UNPROCESSABLE_ENTITY -> buildResponse(ex, BaseErrorCode.UNPROCESSABLE_ENTITY.name(), UNPROCESSABLE_ENTITY);
                case INTERNAL_SERVER_ERROR -> buildResponse(ex, BaseErrorCode.UNEXPECTED_ERROR.name(), INTERNAL_SERVER_ERROR);
                default -> buildResponse(ex, BaseErrorCode.UNEXPECTED_ERROR.name(), status);
            };
        }
        return buildResponse(ex, BaseErrorCode.UNEXPECTED_ERROR.name(), statusCode.value(), ex.getMessage());
    }

    /**
     * Builds error response
     *
     * @param ex
     * 		the exception
     * @param code
     * 		the error code
     * @param statusCode
     * 		the http status
     *
     * @return {@link ResponseEntity}&lt;{@link ErrorResponse}&gt; the error response
     */
    protected ResponseEntity<ErrorResponse> buildResponse(Exception ex, String code, HttpStatus statusCode) {
        return buildResponse(ex, code, statusCode.value(), statusCode.getReasonPhrase());
    }

    /**
     * Builds error response
     *
     * @param ex
     * 		the exception
     * @param code
     * 		the error code
     * @param status
     * 		the error status
     * @param message
     * 		the error message
     *
     * @return {@link ResponseEntity}&lt;{@link ErrorResponse}&gt; the error response
     */
    protected ResponseEntity<ErrorResponse> buildResponse(Exception ex, String code, int status, String message) {
        ErrorResponse error = new ErrorResponse();
        error.setCode(code);
        error.setStatus(status);
        error.setMessage(message);
        error.setDetails(ex.getMessage());
        return addContext(ex, error);
    }

    /**
     * Adds context information to error response
     *
     * @param ex
     * 		the exception
     * @param response
     * 		the error response
     *
     * @return {@link ResponseEntity}&lt;{@link ErrorResponse}&gt; the response entity with error
     */
    protected ResponseEntity<ErrorResponse> addContext(Exception ex, ErrorResponse response) {
        if (logger.isErrorEnabled()) {
            logger.error(ex.getMessage(), ex);
        }
        HttpHeaders httpHeaders = new HttpHeaders();
        httpHeaders.setContentType(MediaType.APPLICATION_PROBLEM_JSON);
        return ResponseEntity.status(response.getStatus()).headers(httpHeaders).body(response);
    }

}
