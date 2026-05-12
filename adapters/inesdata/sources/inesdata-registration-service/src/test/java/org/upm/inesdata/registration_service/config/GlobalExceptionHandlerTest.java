package org.upm.inesdata.registration_service.config;

import jakarta.validation.ConstraintViolationException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.AuthenticationException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.context.request.WebRequest;
import org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler;
import org.upm.inesdata.registration_service.exception.DataValidationException;
import org.upm.inesdata.registration_service.exception.model.BaseErrorCode;
import org.upm.inesdata.registration_service.exception.model.ErrorResponse;

import java.util.NoSuchElementException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;

public class GlobalExceptionHandlerTest {

    @InjectMocks
    private GlobalExceptionHandler globalExceptionHandler;

    @Mock
    private WebRequest webRequest;

    @BeforeEach
    public void setUp() {
        MockitoAnnotations.openMocks(this);
    }

    @Test
    public void testHandleIllegalArgumentException() {
        IllegalArgumentException ex = new IllegalArgumentException("Invalid argument");
        ResponseEntity<ErrorResponse> response = globalExceptionHandler.handleIllegalArgumentException(ex);
        assertEquals(HttpStatus.BAD_REQUEST, response.getStatusCode());
        assertEquals(BaseErrorCode.BAD_REQUEST.getCode(), response.getBody().getCode());
    }

    @Test
    public void testHandleDataValidationException() {
        DataValidationException ex = new DataValidationException("Data validation error");
        ResponseEntity<ErrorResponse> response = globalExceptionHandler.handleDataValidationException(ex);
        assertEquals(HttpStatus.UNPROCESSABLE_ENTITY, response.getStatusCode());
        assertEquals(BaseErrorCode.UNPROCESSABLE_ENTITY.name(), response.getBody().getCode());
    }

    @Test
    public void testHandleNotFoundException() {
        NoSuchElementException ex = new NoSuchElementException("Not found");
        ResponseEntity<ErrorResponse> response = globalExceptionHandler.handleNotFoundException(ex);
        assertEquals(HttpStatus.NOT_FOUND, response.getStatusCode());
        assertEquals(BaseErrorCode.NOT_FOUND.name(), response.getBody().getCode());
    }

    @Test
    public void testHandleAuthenticationException() {
        AuthenticationException ex = mock(AuthenticationException.class);
        ResponseEntity<ErrorResponse> response = globalExceptionHandler.handleAuthenticationException(ex);
        assertEquals(HttpStatus.UNAUTHORIZED, response.getStatusCode());
        assertEquals(BaseErrorCode.UNAUTHORIZED.name(), response.getBody().getCode());
    }

    @Test
    public void testHandleAccessDeniedException() {
        AccessDeniedException ex = new AccessDeniedException("Access denied");
        ResponseEntity<ErrorResponse> response = globalExceptionHandler.handleAccessDeniedException(ex);
        assertEquals(HttpStatus.FORBIDDEN, response.getStatusCode());
        assertEquals(BaseErrorCode.FORBIDDEN.name(), response.getBody().getCode());
    }

    @Test
    public void testHandleExceptionCustom() {
        Exception ex = new Exception("Unexpected error");
        ResponseEntity<ErrorResponse> response = globalExceptionHandler.handleExceptionCustom(ex, webRequest);
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, response.getStatusCode());
        assertEquals(BaseErrorCode.UNEXPECTED_ERROR.name(), response.getBody().getCode());
    }

    @Test
    public void testHandleExceptionInternal() {
        Exception ex = new Exception("Internal error");
        HttpHeaders headers = new HttpHeaders();
        ResponseEntity<Object> response = globalExceptionHandler.handleExceptionInternal(ex, null, headers, HttpStatus.BAD_REQUEST, webRequest);
        assertEquals(HttpStatus.BAD_REQUEST, response.getStatusCode());
        assertEquals(BaseErrorCode.BAD_REQUEST.name(), ((ErrorResponse) response.getBody()).getCode());
    }
}
