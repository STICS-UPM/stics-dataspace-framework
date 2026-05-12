module.exports = (config, { strapi }) => {
  return async (ctx, next) => {
    await next();

    if (ctx.request.url.includes('/api/menus?filters[slug][$eq]=')) {
      if (ctx.response.body && ctx.response.body.data) {
        ctx.response.body.data.forEach(menu => {
          if (menu.attributes.items && menu.attributes.items.data) {
            menu.attributes.items.data.forEach(item => {
              if (item.attributes.related_content.data) {
                item.attributes.related_content = {
                  id: item.attributes.related_content.data.id
                };
              }
            });
          }
        });
      }
    }
  };
};
