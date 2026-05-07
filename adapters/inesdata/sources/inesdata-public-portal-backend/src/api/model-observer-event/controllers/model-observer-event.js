'use strict';

const eventService = require('../services/model-observer-event');

module.exports = {
  async create(ctx) {
    try {
      ctx.body = eventService.createEvent(ctx.request.body || {});
      ctx.status = 201;
    } catch (error) {
      ctx.body = {
        message: error.message,
        details: error.validationErrors || []
      };
      ctx.status = 400;
    }
  },

  async createBulk(ctx) {
    try {
      ctx.body = eventService.createBulkEvents(ctx.request.body || []);
      ctx.status = 201;
    } catch (error) {
      ctx.body = {
        message: error.message,
        details: error.validationErrors || []
      };
      ctx.status = 400;
    }
  }
};