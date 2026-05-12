module.exports = {
  routes: [
    {
      method: 'GET',
      path: '/model-observer/participants/:participantId/summary',
      handler: 'model-observer-summary.getParticipantSummary',
      config: {
        auth: false
      }
    }
  ]
};