package org.upm.inesdata.registration_service.controller;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.upm.inesdata.registration_service.entity.Participant;
import org.upm.inesdata.registration_service.service.ParticipantService;

import java.util.List;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import java.util.List;

/**
 * REST controller for managing public participant operations.
 * @author gmv
 */
@RestController
@RequestMapping("/public/participants")
@Tag(name = "Participants", description = "Operations related to Participants")
public class PublicParticipantController {

    @Autowired
    private ParticipantService participantService;

    /**
     * Retrieves a list of all participants.
     *
     * @return a list of Participant objects.
     */
    @Operation(summary = "Get all participants", description = "Retrieves a list of all participants.")
    @GetMapping
    public List<Participant> getAllParticipants() {
        return participantService.findAll();
    }
}
