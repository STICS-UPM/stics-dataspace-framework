module.exports = {
  routes: [
    {
      method: 'POST',
      path: '/model-observer/events',
      handler: 'model-observer-event.create',
      config: {
        auth: false
      }
    },
    {
      method: 'POST',
      path: '/model-observer/events/bulk',
      handler: 'model-observer-event.createBulk',
      config: {
        auth: false
      }
    }
  ]
};