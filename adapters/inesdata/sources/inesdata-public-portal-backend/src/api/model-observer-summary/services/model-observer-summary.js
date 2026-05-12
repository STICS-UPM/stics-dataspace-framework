'use strict';

const store = require('../../model-observer-shared/services/model-observer-store');

function getParticipantSummary(participantId) {
  return store.participantSummary(participantId);
}

module.exports = {
  getParticipantSummary
};