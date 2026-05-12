package org.upm.inesdata.registration_service.controller;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.context.ContextConfiguration;
import org.springframework.test.context.junit.jupiter.SpringExtension;
import org.upm.inesdata.registration_service.entity.Participant;
import org.upm.inesdata.registration_service.service.ParticipantService;

import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;
import static org.springframework.test.util.AssertionErrors.assertNotNull;

/**
 * Clase de pruebas unitarias para {@link ParticipantController}
 */
@ExtendWith(SpringExtension.class)
@ContextConfiguration(classes = { ParticipantController.class })
class ParticipantControllerTest {

    @Autowired
    private ParticipantController controller;

    @MockBean
    private ParticipantService service;

    /**
     * Prueba del método {@link ParticipantController#getAllParticipants()}
     */
    @Test
    void getAllParticipantsTest() {
        Participant participant = getParticipant();
        // Preparation
        when(service.findAll()).thenReturn(List.of(participant));
        // Execute Test
        List<Participant> response = controller.getAllParticipants();
        // Verify
        assertNotNull("No debe ser nulo", response);
    }

    /**
     * Prueba del método {@link ParticipantController#createParticipant(Participant)}
     */
    @Test
    void createParticipantTest() {
        Participant participant = getParticipant();
        // Preparation
        when(service.create(any())).thenReturn(participant);
        // Execute Test
        Participant response = controller.createParticipant(participant);
        // Verify
        assertNotNull("No debe ser nulo", response);
    }

    /**
     * Prueba del método {@link ParticipantController#updateParticipant(String, Participant)}
     */
    @Test
    void updateParticipantTest() {
        Participant participant = getParticipant();
        // Preparation
        when(service.update(anyString(), any())).thenReturn(participant);
        // Execute Test
        Participant response = controller.updateParticipant("1", participant);
        // Verify
        assertNotNull("No debe ser nulo", response);
    }

    /**
     * Prueba del método {@link ParticipantController#deleteParticipant(String)}
     */
    @Test
    void deleteParticipantTest() {
        // Preparation
        doNothing().when(service).deleteById(anyString());
        // Execute Test
        controller.deleteParticipant("1");
        // Verify
        verify(service, times(1)).deleteById("1");
    }

    private Participant getParticipant() {
        Participant participant = new Participant();
        participant.setParticipantId("1");
        participant.setUrl("http://local");
        participant.setCreatedAt(23332233254L);
        return participant;
    }
}
