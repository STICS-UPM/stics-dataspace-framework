'use strict';

const summaryService = require('../services/model-observer-summary');

module.exports = {
  async getParticipantSummary(ctx) {
    const { participantId } = ctx.params;
    if (!participantId) {
      ctx.body = { message: 'participantId is required' };
      ctx.status = 400;
      return;
    }

    ctx.body = summaryService.getParticipantSummary(participantId);
    ctx.status = 200;
  }
};