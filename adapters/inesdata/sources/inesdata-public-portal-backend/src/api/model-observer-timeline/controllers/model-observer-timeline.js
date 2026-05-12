'use strict';

const timelineService = require('../services/model-observer-timeline');

module.exports = {
  async getTimeline(ctx) {
    const { assetId } = ctx.params;
    if (!assetId) {
      ctx.body = { message: 'assetId is required' };
      ctx.status = 400;
      return;
    }

    ctx.body = timelineService.getTimeline(assetId, ctx.query || {});
    ctx.status = 200;
  }
};