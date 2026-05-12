module.exports = {
  routes: [
    {
      method: 'GET',
      path: '/model-observer/agreements/:agreementId',
      handler: 'model-observer-agreement.getAgreementTimeline',
      config: {
        auth: false
      }
    }
  ]
};