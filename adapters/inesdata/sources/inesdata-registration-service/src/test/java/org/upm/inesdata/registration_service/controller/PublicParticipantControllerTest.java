package org.upm.inesdata.registration_service.controller;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.ResponseEntity;
import org.springframework.test.context.ContextConfiguration;
import org.springframework.test.context.junit.jupiter.SpringExtension;
import org.upm.inesdata.registration_service.entity.Participant;
import org.upm.inesdata.registration_service.service.ParticipantService;

import java.util.List;
import java.util.Optional;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;
import static org.springframework.test.util.AssertionErrors.assertNotNull;

/**
 * Clase de pruebas unitarias para {@link PublicParticipantController}
 */
@ExtendWith(SpringExtension.class)
@ContextConfiguration(classes = { PublicParticipantController.class })
class PublicParticipantControllerTest {

    @Autowired
    private PublicParticipantController controller;

    @MockBean
    private ParticipantService service;

    /**
     * Prueba del método {@link PublicParticipantController#getAllParticipants()}
     */
    @Test
    void getParticipantByIdTest() {
        Participant participant = getParticipant();
        // Preparation
        when(service.findAll()).thenReturn(List.of(participant));
        // Execute Test
        List<Participant> response = controller.getAllParticipants();
        // Verify
        assertNotNull("No debe ser nulo", response);
    }

    private Participant getParticipant() {
        Participant participant = new Participant();
        participant.setParticipantId("1");
        participant.setUrl("http://local");
        participant.setCreatedAt(23332233254L);
        return participant;
    }
}
