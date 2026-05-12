'use strict';

const agreementService = require('../services/model-observer-agreement');

module.exports = {
  async getAgreementTimeline(ctx) {
    const { agreementId } = ctx.params;
    if (!agreementId) {
      ctx.body = { message: 'agreementId is required' };
      ctx.status = 400;
      return;
    }

    ctx.body = agreementService.getAgreementTimeline(agreementId, ctx.query || {});
    ctx.status = 200;
  }
};