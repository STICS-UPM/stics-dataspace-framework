// ./config/plugins.js`
'use strict';

module.exports = {
  menus: {
    config: {
      maxDepth: 3,
      layouts: {
        menuItem: {
          link: [
            {
              input: {
                label: 'Text for URL',
                name: 'slug',
                type: 'text'
              }
            },
          ],
          content: [
            {
              input: {
                label: 'Relation',
                name: 'related_content',
                type: 'relation',
              },
            }
          ],
        },
      },
    },
  },
};
