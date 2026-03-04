export const environment = {
  production: true,
  appName: 'CatalogModelIA DS',
  version: '1.0.0',
  
  // EDC Connector endpoints - will be loaded from runtime config
  runtime: {
    managementApiUrl: '',
    providerApiUrl: '',
    consumerApiUrl: '',
    catalogUrl: '',
    participantId: '',
    
    service: {
      asset: {
        baseUrl: '/v3/assets',
        get: '/',
        getAll: '/request',
      },
      policy: {
        baseUrl: '/v3/policydefinitions',
        get: '/',
        getAll: '/request',
      },
      contractDefinition: {
        baseUrl: '/v3/contractdefinitions',
        get: '/',
        getAll: '/request',
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
    
    oauth2: {
      enabled: false,
      issuer: '',
      clientId: '',
      scope: 'openid profile email',
      responseType: 'code',
      showDebugInformation: false,
    }
  },
  
  features: {
    enableAssetSourceFilter: true,
    enableStorageTypeFilter: true,
    enableFormatFilter: true,
    enableTaskFilter: true,
    enableContractCreation: true,
    enableNegotiation: true,
  }
};
