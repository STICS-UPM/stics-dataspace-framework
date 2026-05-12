import type { Schema, Attribute } from '@strapi/strapi';

export interface LandingPageComponentsCatalog extends Schema.Component {
  collectionName: 'components_landing_page_components_catalogs';
  info: {
    displayName: 'Catalog';
    description: '';
  };
  attributes: {
    Title: Attribute.String & Attribute.Required;
    Description: Attribute.String & Attribute.Required;
    Background: Attribute.Media;
  };
}

export interface LandingPageComponentsGetToKnowUs extends Schema.Component {
  collectionName: 'components_landing_page_components_get_to_know_uses';
  info: {
    displayName: 'Get To Know us';
    description: '';
  };
  attributes: {
    Title: Attribute.String & Attribute.Required;
    Description: Attribute.RichText & Attribute.Required;
    Background: Attribute.Media & Attribute.Required;
  };
}

export interface LandingPageComponentsJoin extends Schema.Component {
  collectionName: 'components_landing_page_components_joins';
  info: {
    displayName: 'Join';
    description: '';
  };
  attributes: {
    Title: Attribute.String & Attribute.Required;
    Description: Attribute.RichText & Attribute.Required;
    Image: Attribute.Media & Attribute.Required;
  };
}

export interface LandingPageComponentsWelcome extends Schema.Component {
  collectionName: 'components_landing_page_components_welcomes';
  info: {
    displayName: 'Welcome';
    icon: '';
    description: '';
  };
  attributes: {
    Text: Attribute.String & Attribute.Required;
    Image: Attribute.Media & Attribute.Required;
  };
}

declare module '@strapi/types' {
  export module Shared {
    export interface Components {
      'landing-page-components.catalog': LandingPageComponentsCatalog;
      'landing-page-components.get-to-know-us': LandingPageComponentsGetToKnowUs;
      'landing-page-components.join': LandingPageComponentsJoin;
      'landing-page-components.welcome': LandingPageComponentsWelcome;
    }
  }
}
