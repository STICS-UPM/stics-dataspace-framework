// ./src/extensions/menus/strapi-server.js`
'use strict';

module.exports = plugin => {
  // Get current `MenuItem` attributes.
  const defaultAttrs = plugin.contentTypes['menu-item'].schema.attributes;

  // Define custom attributes for `MenuItem` the same way they would be defined
  // on any other schema.
  const customAttrs = {
    slug: {
      type: 'string',
    },
    related_content: {
      type: 'relation',
      relation: 'oneToOne',
      target: 'api::generic-page.generic-page',
    },
  };

  // Extend the `MenuItem` content type with custom attributes.
  plugin.contentTypes['menu-item'].schema.attributes = {
    ...defaultAttrs,
    ...customAttrs,
  };

  return plugin;
};
