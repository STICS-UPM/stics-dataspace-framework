package org.upm.inesdata.registration_service.service;

import org.upm.inesdata.registration_service.entity.Participant;

import java.util.List;
import java.util.Optional;

import java.util.List;
import java.util.Optional;

/**
 * Service interface for managing Participant entities.
 * @author gmv
 */
public interface ParticipantService {

    /**
     * Retrieves all participants.
     *
     * @return a list of Participant objects.
     */
    List<Participant> findAll();

    /**
     * Retrieves a participant by its ID.
     *
     * @param id the ID of the participant to retrieve.
     * @return an Optional containing the Participant, or empty if not found.
     */
    Optional<Participant> findById(String id);

    /**
     * Updates an existing participant.
     *
     * @param id         the ID of the participant to update.
     * @param participant the updated Participant object.
     * @return the updated Participant object.
     */
    Participant update(String id, Participant participant);

    /**
     * Creates a new participant.
     *
     * @param participant the Participant object to create.
     * @return the created Participant object.
     */
    Participant create(Participant participant);

    /**
     * Deletes a participant by its ID.
     *
     * @param id the ID of the participant to delete.
     */
    void deleteById(String id);
}
