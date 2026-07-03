export const environment = {
  production: true,
  jwt: {
    storageKey: 'access_token',
    storageRefreshKey: 'refresh_token',
    allowedDomains: [/.*/i],
    disallowedRoutes: [/.\/token\.*/i,/.\/public\.*/i]
  },
  runtime: {
    managementApiUrl: '',
    strapiUrl: '',
    catalogUrl: '',
    sharedUrl: "",
    ontologyUrl: "",
    ontologyAdminUser: "",
    ontologyAdminPassword: "",
    participantId: "",
    storageAccount: '',
    storageExplorerLinkTemplate: '',
    service: {
      asset: {
        baseUrl: '/v3/assets',
        uploadChunk: '/s3assets/upload-chunk',
        finalizeUpload: '/s3assets/finalize-upload',
        get: '/',
        getAll: '/request',
        count: '/pagination/count?type=asset'
      },
      contractAgreement: {
        baseUrl: '/v3/contractagreements',
        get: '/',
        getAll: '/request',
        getNegotiation: '/negotiation',
        count: '/pagination/count?type=contractAgreement'
      },
      policy: {
        baseUrl: '/v3/policydefinitions',
        complexBaseUrl: '/v3/complexpolicydefinitions',
        get: '/',
        getAll: '/request',
        count: '/pagination/count?type=policyDefinition'
      },
      contractDefinition: {
        baseUrl: '/v3/contractdefinitions',
        get: '/',
        getAll: '/request',
        count: '/pagination/count?type=contractDefinition'
      },
      contractNegotiation: {
        baseUrl: '/v3/contractnegotiations',
        get: '/',
        agreement: '/agreement',
        state: '/state',
        terminate: '/terminate',
        getAll: '/request'
      },
      transferProcess: {
        baseUrl: '/v3/transferprocesses',
        inesdataBaseUrl: '/v3/inesdatatransferprocesses',
        get: '/',
        deprovision: '/deprovision',
        state: '/state',
        terminate: '/terminate',
        getAll: '/request',
        count: '/pagination/count?type=transferProcess'
      },
      vocabulary: {
        baseUrl: '/connector-vocabularies',
        getAll: '/request-by-connector',
        managementUrl:'/vocabularies',
        getAllShared:'/request'
      },
      federatedCatalog: {
        count: '/pagination/count?type=federatedCatalog',
        paginationRequest: '/request'
      },
      modelExecution: {
        baseUrl: '/v3/modelexecutions',
        execute: '/execute'
      }
    },
    oauth2: {
      issuer: '',
      redirectPath: '/',
      clientId: '',
      scope: 'openid profile email',
      responseType: 'code',
      showDebugInformation: false,
      allowedUrls: ''
    }
  }
};
