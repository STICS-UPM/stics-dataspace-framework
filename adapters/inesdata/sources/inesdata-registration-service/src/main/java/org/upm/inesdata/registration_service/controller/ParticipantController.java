package org.upm.inesdata.registration_service.controller;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.security.access.annotation.Secured;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.upm.inesdata.registration_service.entity.Participant;
import org.upm.inesdata.registration_service.service.ParticipantService;

import java.util.List;

@RestController
@RequestMapping("/participants")
@Tag(name = "Participants", description = "Operations related to Participants")
public class ParticipantController {

  @Autowired
  private ParticipantService participantService;

  /**
   * Retrieves all participants.
   *
   * @return a list of participants
   */
  @Operation(summary = "Get all participants", description = "Retrieves a list of all participants.")
  @Secured("dataspace-admin")
  @GetMapping
  public List<Participant> getAllParticipants() {
    return participantService.findAll();
  }

  /**
   * Creates a new participant.
   *
   * @param participant the participant to create
   * @return the created participant
   */
  @Operation(summary = "Create a participant", description = "Creates a new participant.",
      security = @SecurityRequirement(name = "dataspace-admin"))
  @Secured("dataspace-admin")
  @PostMapping
  public Participant createParticipant(@RequestBody Participant participant) {
    return participantService.create(participant);
  }

  /**
   * Updates an existing participant.
   *
   * @param id          the ID of the participant to update
   * @param participant the updated participant
   * @return the updated participant
   */
  @Operation(summary = "Update a participant", description = "Updates an existing participant.",
      security = @SecurityRequirement(name = "dataspace-admin"))
  @Secured("dataspace-admin")
  @PutMapping("/{id}")
  public Participant updateParticipant(@PathVariable String id, @RequestBody Participant participant) {
    return participantService.update(id, participant);
  }

  /**
   * Deletes a participant by ID.
   *
   * @param id the ID of the participant to delete
   */
  @Operation(summary = "Delete a participant", description = "Deletes a participant by ID.",
      security = @SecurityRequirement(name = "dataspace-admin"))
  @Secured("dataspace-admin")
  @DeleteMapping("/{id}")
  public void deleteParticipant(@PathVariable String id) {
    participantService.deleteById(id);
  }
}
