package org.upm.inesdata.registration_service.service;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.upm.inesdata.registration_service.entity.Participant;
import org.upm.inesdata.registration_service.exception.DataValidationException;
import org.upm.inesdata.registration_service.repository.ParticipantRepository;

import java.util.List;
import java.util.NoSuchElementException;
import java.util.Optional;

/**
 * Implementation of ParticipantService that interacts with ParticipantRepository.
 * @author gmv
 */
@Service
public class ParticipantServiceImpl implements ParticipantService {

  @Autowired
  private ParticipantRepository participantRepository;

  /**
   * Retrieves all participants.
   *
   * @return a list of Participant objects.
   */
  @Override
  public List<Participant> findAll() {
    return participantRepository.findAll();
  }

  /**
   * Retrieves a participant by its ID.
   *
   * @param id the ID of the participant to retrieve.
   * @return an Optional containing the Participant, or empty if not found.
   */
  @Override
  public Optional<Participant> findById(String id) {
    return participantRepository.findById(id);
  }

  /**
   * Updates an existing participant.
   *
   * @param id         the ID of the participant to update.
   * @param participant the updated Participant object.
   * @return the updated Participant object.
   * @throws NoSuchElementException if the participant with the given ID is not found.
   */
  @Override
  public Participant update(String id, Participant participant) {
    Optional<Participant> originalParticipantOptional = participantRepository.findById(id);
    if (originalParticipantOptional.isEmpty()) {
      throw new NoSuchElementException("Participant not found");
    } else {
      Participant originalParticipant = originalParticipantOptional.get();
      originalParticipant.setUrl(participant.getUrl());
      originalParticipant.setParticipantId(id);
      return participantRepository.save(originalParticipant);
    }
  }

  /**
   * Creates a new participant.
   *
   * @param participant the Participant object to create.
   * @return the created Participant object.
   * @throws DataValidationException if a participant with the same ID already exists.
   */
  @Override
  public Participant create(Participant participant) {
    if (participantRepository.existsById(participant.getParticipantId())) {
      throw new DataValidationException("Participant already exists");
    }
    participant.setCreatedAt(System.currentTimeMillis());
    return participantRepository.save(participant);
  }

  /**
   * Deletes a participant by its ID.
   *
   * @param id the ID of the participant to delete.
   */
  @Override
  public void deleteById(String id) {
    participantRepository.deleteById(id);
  }
}
