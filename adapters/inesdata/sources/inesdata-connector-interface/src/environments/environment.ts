// This file can be replaced during build by using the `fileReplacements` array.
// `ng build` replaces `environment.ts` with `environment.prod.ts`.
// The list of file replacements can be found in `angular.json`.

export const environment = {
  production: false,
  jwt: {
    storageKey: 'access_token',
    storageRefreshKey: 'refresh_token',
    allowedDomains: [/.*/i],
    disallowedRoutes: [/.\/token\.*/i,/.\/public\.*/i]
  },
  runtime: {
    managementApiUrl: "http://localhost:19193/management",
    strapiUrl: "http://localhost:1337",
    catalogUrl: "http://localhost:19193/management/federatedcatalog",
    sharedUrl: "http://localhost:19196/shared",
    ontologyUrl: "http://ontology-hub-demo.dev.ds.dataspaceunit.upm",
    ontologyAdminUser: "",
    ontologyAdminPassword: "",
    participantId: "connector-c1",
    storageAccount: "company2assets",
    storageExplorerLinkTemplate: "storageexplorer://v=1",
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
      issuer: 'http://keycloak:8080/realms/dataspace',
      redirectPath: '/inesdata-connector-interface',
      clientId: 'dataspace-users',
      scope: 'openid profile email',
      responseType: 'code',
      showDebugInformation: true,
      allowedUrls: 'http://localhost:4200'
    }
  }
};

/*
 * For easier debugging in development mode, you can import the following file
 * to ignore zone related error stack frames such as `zone.run`, `zoneDelegate.invokeTask`.
 *
 * This import should be commented out in production mode because it will have a negative impact
 * on performance if an error is thrown.
 */
// import 'zone.js/plugins/zone-error';  // Included with Angular CLI.
