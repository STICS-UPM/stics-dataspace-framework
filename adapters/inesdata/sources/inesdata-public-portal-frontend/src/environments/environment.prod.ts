import { NgxLoggerLevel } from 'ngx-logger';
import packageJson from '../../package.json';

export const environment = {
  production: true,
  info: {
    version: packageJson.version,
    name: packageJson.name,
    app: packageJson.project
  },
  api: {
    endpoints: {}
  },
  messages: {
    life: 5000
  },
  tables: {
    pagination: {
      available: [10, 50, 100]
    }
  },
  runtime: {
		strapiUrl: 'http://localhost:1337',
		service:{
			strapi:{
				getFederatedCatalog: '/api/get-federated-catalog',
				getLandingPage: '/api/landing-page?populate[Welcome][populate][0]=Image&populate[Catalog][populate][0]=Background&populate[GetToKnowUs][populate][0]=Background&populate[Join][populate][0]=Image',
				getMenu: '/api/menus?filters[slug][$eq]=public-portal-menu&populate[items][populate]=related_content',
				getVocabularies: '/api/get-vocabularies',
				getGenericPage: '/api/generic-pages/'
			}
		}
  },
  logging: {
    disableWindowConsoleLogging: true,
    disableNgxLogging: false,
    apiUrl: 'http://localhost:68552/api/logs',
    logLevel: NgxLoggerLevel.ERROR,
    serverLogLevel: NgxLoggerLevel.ERROR,
    enableSourceMaps: false
  }
};
