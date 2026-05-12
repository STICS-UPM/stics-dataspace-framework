'use strict';

const benchmarkService = require('../services/model-observer-benchmark');

module.exports = {
  async getBenchmarkTimeline(ctx) {
    const { benchmarkRunId } = ctx.params;
    if (!benchmarkRunId) {
      ctx.body = { message: 'benchmarkRunId is required' };
      ctx.status = 400;
      return;
    }

    ctx.body = benchmarkService.getBenchmarkTimeline(benchmarkRunId, ctx.query || {});
    ctx.status = 200;
  }
};