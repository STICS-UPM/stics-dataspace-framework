import {
  BrowserLocationLike,
  ModelObserverRuntimeConfig,
  resolveModelObserverApiBaseUrl,
  resolveOauthAllowedUrls
} from './model-observer-runtime';

describe('model observer runtime utilities', () => {
  const connectorLocation: BrowserLocationLike = {
    protocol: 'http:',
    hostname: 'conn-citycouncil-demo.dev.ds.dataspaceunit.upm',
    origin: 'http://conn-citycouncil-demo.dev.ds.dataspaceunit.upm'
  };

  it('uses explicit strapi url when it is configured', () => {
    const runtime: ModelObserverRuntimeConfig = {
      strapiUrl: 'http://backend-demo.dev.ds.dataspaceunit.upm/'
    };

    expect(resolveModelObserverApiBaseUrl(runtime, connectorLocation))
      .toBe('http://conn-citycouncil-demo.dev.ds.dataspaceunit.upm/inesdata-connector-interface/model-observer');

    expect(resolveModelObserverApiBaseUrl(runtime, null))
      .toBe('http://backend-demo.dev.ds.dataspaceunit.upm/api/model-observer');
  });

  it('falls back to the backend host present in allowed urls', () => {
    const runtime: ModelObserverRuntimeConfig = {
      participantId: 'conn-citycouncil-demo',
      oauth2: {
        allowedUrls: 'http://conn-citycouncil-demo.dev.ds.dataspaceunit.upm,http://backend-demo.dev.ds.dataspaceunit.upm'
      }
    };

    expect(resolveModelObserverApiBaseUrl(runtime, connectorLocation))
      .toBe('http://conn-citycouncil-demo.dev.ds.dataspaceunit.upm/inesdata-connector-interface/model-observer');
  });

  it('derives the backend host from the connector host when runtime config is incomplete', () => {
    const runtime: ModelObserverRuntimeConfig = {
      managementApiUrl: 'http://conn-citycouncil-demo.dev.ds.dataspaceunit.upm/management',
      participantId: 'conn-citycouncil-demo',
      oauth2: {
        allowedUrls: 'http://conn-citycouncil-demo.dev.ds.dataspaceunit.upm,http://conn-citycouncil-demo:19193'
      }
    };

    expect(resolveModelObserverApiBaseUrl(runtime, connectorLocation))
      .toBe('http://conn-citycouncil-demo.dev.ds.dataspaceunit.upm/inesdata-connector-interface/model-observer');
  });

  it('keeps the public connector path prefix when the portal is served below a vm-single route', () => {
    const runtime: ModelObserverRuntimeConfig = {
      managementApiUrl: 'https://validation.example.org/c/consumer-a/management',
      participantId: 'conn-consumer-a-demo'
    };
    const vmSingleLocation: BrowserLocationLike = {
      protocol: 'https:',
      hostname: 'validation.example.org',
      origin: 'https://validation.example.org',
      pathname: '/inesdata-connector-interface/ai-model-observer/participants/qa-ai-model-consumer'
    };

    expect(resolveModelObserverApiBaseUrl(runtime, vmSingleLocation))
      .toBe('https://validation.example.org/c/consumer-a/inesdata-connector-interface/model-observer');
  });

  it('supports relative same-origin management API paths for routed connector deployments', () => {
    const runtime: ModelObserverRuntimeConfig = {
      managementApiUrl: '/c/consumer-b/management',
      participantId: 'conn-consumer-b-demo'
    };
    const routedLocation: BrowserLocationLike = {
      protocol: 'https:',
      hostname: 'validation.example.org',
      origin: 'https://validation.example.org',
      pathname: '/c/consumer-b/inesdata-connector-interface/ai-model-observer'
    };

    expect(resolveModelObserverApiBaseUrl(runtime, routedLocation))
      .toBe('https://validation.example.org/c/consumer-b/inesdata-connector-interface/model-observer');
  });

  it('prefers the current public route prefix when management API is same-origin without that prefix', () => {
    const runtime: ModelObserverRuntimeConfig = {
      managementApiUrl: 'https://validation.example.org/management',
      participantId: 'conn-consumer-c-demo'
    };
    const routedLocation: BrowserLocationLike = {
      protocol: 'https:',
      hostname: 'validation.example.org',
      origin: 'https://validation.example.org',
      pathname: '/c/consumer-c/inesdata-connector-interface/ai-model-observer/participants'
    };

    expect(resolveModelObserverApiBaseUrl(runtime, routedLocation))
      .toBe('https://validation.example.org/c/consumer-c/inesdata-connector-interface/model-observer');
  });

  it('sanitizes oauth allowed urls and appends the derived backend origin once', () => {
    const runtime: ModelObserverRuntimeConfig = {
      participantId: 'conn-citycouncil-demo',
      oauth2: {
        allowedUrls: ' ,http://conn-citycouncil-demo.dev.ds.dataspaceunit.upm,,http://backend-demo.dev.ds.dataspaceunit.upm, '
      }
    };

    expect(resolveOauthAllowedUrls(runtime, connectorLocation)).toEqual([
      'http://conn-citycouncil-demo.dev.ds.dataspaceunit.upm',
      'http://backend-demo.dev.ds.dataspaceunit.upm'
    ]);
  });
});
