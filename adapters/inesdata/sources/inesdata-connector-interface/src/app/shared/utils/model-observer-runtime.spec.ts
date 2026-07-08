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
      .toBe('http://conn-citycouncil-demo.dev.ds.dataspaceunit.upm/connector-interface/model-observer');

    expect(resolveModelObserverApiBaseUrl(runtime, null))
      .toBe('http://backend-demo.dev.ds.dataspaceunit.upm/api/model-observer');
  });

  it('uses the public backend path when the interface is exposed through participant hosts', () => {
    const runtime: ModelObserverRuntimeConfig = {
      strapiUrl: 'https://org1.pionera.oeg.fi.upm.es/public-portal-backend',
      managementApiUrl: 'https://org3.pionera.oeg.fi.upm.es/management',
      participantId: 'conn-org3-pionera'
    };
    const publicParticipantLocation: BrowserLocationLike = {
      protocol: 'https:',
      hostname: 'org3.pionera.oeg.fi.upm.es',
      origin: 'https://org3.pionera.oeg.fi.upm.es'
    };

    expect(resolveModelObserverApiBaseUrl(runtime, publicParticipantLocation))
      .toBe('https://org1.pionera.oeg.fi.upm.es/public-portal-backend/api/model-observer');
  });

  it('falls back to the backend host present in allowed urls', () => {
    const runtime: ModelObserverRuntimeConfig = {
      participantId: 'conn-citycouncil-demo',
      oauth2: {
        allowedUrls: 'http://conn-citycouncil-demo.dev.ds.dataspaceunit.upm,http://backend-demo.dev.ds.dataspaceunit.upm'
      }
    };

    expect(resolveModelObserverApiBaseUrl(runtime, connectorLocation))
      .toBe('http://conn-citycouncil-demo.dev.ds.dataspaceunit.upm/connector-interface/model-observer');
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
      .toBe('http://conn-citycouncil-demo.dev.ds.dataspaceunit.upm/connector-interface/model-observer');
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
