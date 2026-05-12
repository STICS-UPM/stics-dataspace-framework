package org.upm.inesdata.registration_service.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.validation.constraints.NotNull;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Entity class representing a participant in the EDC system.
 * @author gmv
 */
@Data
@NoArgsConstructor
@Entity
@Table(name = "edc_participant")
public class Participant {

    /**
     * The unique identifier for the participant.
     */
    @Id
    @NotNull
    private String participantId;

    /**
     * The URL associated with the participant.
     */
    @NotNull
    private String url;

    /**
     * The timestamp when the participant was created.
     */
    @NotNull
    private long createdAt;

    /**
     * The URL associated with the  shared vocabularies of participants.
     */
    @NotNull
    private String sharedUrl;
}
