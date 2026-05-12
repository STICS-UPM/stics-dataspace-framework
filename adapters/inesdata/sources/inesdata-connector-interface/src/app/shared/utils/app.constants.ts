import { InjectionToken } from '@angular/core';

export const BASE_PATH = new InjectionToken<string>('basePath');
export const CONNECTOR_MANAGEMENT_API = new InjectionToken<string>('MANAGEMENT_API');
export const CONNECTOR_CATALOG_API = new InjectionToken<string>('CATALOG_API');
export const COLLECTION_FORMATS = {
    'csv': ',',
    'tsv': '   ',
    'ssv': ' ',
    'pipes': '|'
}

export const DATA_ADDRESS_TYPES = {
  httpData: 'HttpData',
  amazonS3: 'AmazonS3',
  inesDataStore: 'InesDataStore'
}

export const ASSET_TYPES = {
  dataset: 'Dataset',
  service: 'Service',
  machineLearning: 'Machine learning'
}

export const CATEGORIES = {
  default: 'Default',
  dataset: 'Dataset',
  service: 'Service',
  machineLearning: 'Machine learning'
}

export const CONTEXTS = {
  dcterms: "http://purl.org/dc/terms/",
  dcat: "http://www.w3.org/ns/dcat#",
  odrl: "http://www.w3.org/ns/odrl/2/"
}
