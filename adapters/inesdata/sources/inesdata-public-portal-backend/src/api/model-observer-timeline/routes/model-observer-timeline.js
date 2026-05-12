module.exports = {
  routes: [
    {
      method: 'GET',
      path: '/model-observer/timeline/:assetId',
      handler: 'model-observer-timeline.getTimeline',
      config: {
        auth: false
      }
    }
  ]
};