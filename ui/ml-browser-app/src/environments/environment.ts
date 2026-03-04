export const environment = {
  production: false,
  appName: 'Asset Filter Template',
  version: '1.0.0',

  // Runtime endpoints
  runtime: {
    // Provider Management API (asset/policy/contract definition)
    managementApiUrl: 'http://localhost:19193/management',
    providerManagementUrl: 'http://localhost:19193/management',

    // Consumer endpoints (extensions + management)
    consumerApiUrl: 'http://localhost:29191',
    consumerManagementUrl: 'http://localhost:29193/management',
    consumerProtocolUrl: 'http://localhost:29194/protocol',
    providerApiUrl: 'http://localhost:19191',

    // Provider DSP endpoint
    providerProtocolUrl: 'http://localhost:19194/protocol',

    // Filter + infer extensions
    filterApiUrl: 'http://localhost:29191/api/filter/catalog',
    inferApiUrl: 'http://localhost:29191/api/infer',

    catalogProtocol: 'dataspace-protocol-http',
    participantId: 'consumer',

    // EDC API service endpoints (standard EDC paths)
    service: {
      asset: {
        baseUrl: '/v3/assets',
        get: '/',
        getAll: '/request',
        count: '/request/count',
        uploadChunk: '/s3assets/upload-chunk',
        finalizeUpload: '/s3assets/finalize-upload',
      },
      policy: {
        baseUrl: '/v3/policydefinitions',
        get: '/',
        getAll: '/request',
        count: '/request',
        complexBaseUrl: '/v3/policydefinitions/complex',
      },
      contractDefinition: {
        baseUrl: '/v3/contractdefinitions',
        get: '/',
        getAll: '/request',
        count: '/request',
      },
      contractNegotiation: {
        baseUrl: '/v3/contractnegotiations',
        get: '/',
        getAll: '/request',
      },
      transferProcess: {
        baseUrl: '/v3/transferprocesses',
        get: '/',
        getAll: '/request',
      },
      federatedCatalog: {
        paginationRequest: '/request'
      }
    },

    // OAuth2/OIDC configuration (optional)
    oauth2: {
      enabled: false,
      issuer: 'http://localhost:18082/realms/demo',
      clientId: 'ml-browser-client',
      scope: 'openid profile email',
      responseType: 'code',
      showDebugInformation: true,
    },

    devAuth: {
      enabled: true
    }
  },

  // Feature flags
  features: {
    enableAssetSourceFilter: true,
    enableStorageTypeFilter: true,
    enableFormatFilter: true,
    enableTaskFilter: true,
    enableContractCreation: true,
    enableNegotiation: true,
  }
};
