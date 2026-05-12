package org.upm.inesdata.registration_service.service;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.context.ContextConfiguration;
import org.springframework.test.context.junit.jupiter.SpringExtension;
import org.upm.inesdata.registration_service.entity.Participant;
import org.upm.inesdata.registration_service.exception.DataValidationException;
import org.upm.inesdata.registration_service.repository.ParticipantRepository;

import java.util.List;
import java.util.NoSuchElementException;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

/**
 * Clase de pruebas unitarias para {@link ParticipantServiceImpl}
 */
@ExtendWith(SpringExtension.class)
@ContextConfiguration(classes = { ParticipantServiceImpl.class })
class ParticipantServiceImplTest {

    @Autowired
    private ParticipantServiceImpl service;

    @MockBean
    private ParticipantRepository repository;

    /**
     * Prueba del método {@link ParticipantServiceImpl#findAll()}
     */
    @Test
    void findAllTest() {
        Participant participant = getParticipant();
        // Preparation
        when(repository.findAll()).thenReturn(List.of(participant));
        // Execute Test
        List<Participant> result = service.findAll();
        // Verify
        assertNotNull(result, "No debe ser nulo");
        assertEquals(1, result.size(), "El tamaño de la lista debe ser 1");
    }

    /**
     * Prueba del método {@link ParticipantServiceImpl#findById(String)}
     */
    @Test
    void findByIdTest() {
        Participant participant = getParticipant();
        // Preparation
        when(repository.findById(anyString())).thenReturn(Optional.of(participant));
        // Execute Test
        Optional<Participant> result = service.findById("1");
        // Verify
        assertTrue(result.isPresent(), "El participante debe estar presente");
    }

    /**
     * Prueba del método {@link ParticipantServiceImpl#findById(String)} cuando no se encuentra el participante
     */
    @Test
    void findByIdNotFoundTest() {
        // Preparation
        when(repository.findById(anyString())).thenReturn(Optional.empty());
        // Execute Test
        Optional<Participant> result = service.findById("1");
        // Verify
        assertFalse(result.isPresent(), "El participante no debe estar presente");
    }

    /**
     * Prueba del método {@link ParticipantServiceImpl#update(String, Participant)}
     */
    @Test
    void updateTest() {
        Participant originalParticipant = getParticipant();
        originalParticipant.setParticipantId("1");
        // Preparation
        when(repository.findById(anyString())).thenReturn(Optional.of(originalParticipant));
        when(repository.save(any(Participant.class))).thenReturn(originalParticipant);
        
        Participant updatedParticipant = new Participant();
        updatedParticipant.setUrl("new_url");
        // Execute Test
        Participant result = service.update("1", updatedParticipant);
        // Verify
        assertNotNull(result, "No debe ser nulo");
        assertEquals("new_url", result.getUrl(), "La URL debe coincidir");
        verify(repository, times(1)).save(originalParticipant);
    }

    /**
     * Prueba del método {@link ParticipantServiceImpl#update(String, Participant)} cuando no se encuentra el participante
     */
    @Test
    void updateNotFoundTest() {
        // Preparation
        when(repository.findById(anyString())).thenReturn(Optional.empty());
        
        Participant updatedParticipant = new Participant();
        // Execute Test & Verify
        assertThrows(NoSuchElementException.class, () -> service.update("1", updatedParticipant), "Debe lanzar NoSuchElementException");
    }

    /**
     * Prueba del método {@link ParticipantServiceImpl#create(Participant)}
     */
    @Test
    void createTest() {
        Participant participant = getParticipant();
        participant.setParticipantId("1");
        // Preparation
        when(repository.existsById(anyString())).thenReturn(false);
        when(repository.save(any(Participant.class))).thenReturn(participant);
        // Execute Test
        Participant result = service.create(participant);
        // Verify
        assertNotNull(result, "No debe ser nulo");
        verify(repository, times(1)).save(participant);
    }

    /**
     * Prueba del método {@link ParticipantServiceImpl#create(Participant)} cuando el participante ya existe
     */
    @Test
    void createAlreadyExistsTest() {
        Participant participant = getParticipant();
        participant.setParticipantId("1");
        // Preparation
        when(repository.existsById(anyString())).thenReturn(true);
        // Execute Test & Verify
        assertThrows(DataValidationException.class, () -> service.create(participant), "Debe lanzar DataValidationException");
    }

    /**
     * Prueba del método {@link ParticipantServiceImpl#deleteById(String)}
     */
    @Test
    void deleteByIdTest() {
        // Preparation
        doNothing().when(repository).deleteById(anyString());
        // Execute Test
        service.deleteById("1");
        // Verify
        verify(repository, times(1)).deleteById("1");
    }

    private Participant getParticipant() {
        Participant participant = new Participant();
        participant.setParticipantId("1");
        participant.setUrl("http://local");
        participant.setCreatedAt(23332233254L);
        return participant;
    }
}
