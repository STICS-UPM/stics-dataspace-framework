package org.upm.inesdata.registration_service.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import org.upm.inesdata.registration_service.entity.Participant;

/**
 * Repository interface for managing Participant entities.
 * Extends JpaRepository for basic CRUD operations.
 * @author gmv
 */
public interface ParticipantRepository extends JpaRepository<Participant, String> {
}
