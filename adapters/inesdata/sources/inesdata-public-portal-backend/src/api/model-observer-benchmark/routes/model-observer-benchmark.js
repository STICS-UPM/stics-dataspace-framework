module.exports = {
  routes: [
    {
      method: 'GET',
      path: '/model-observer/benchmarks/:benchmarkRunId',
      handler: 'model-observer-benchmark.getBenchmarkTimeline',
      config: {
        auth: false
      }
    }
  ]
};