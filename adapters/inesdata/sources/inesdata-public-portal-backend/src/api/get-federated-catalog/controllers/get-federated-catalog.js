'use strict';

const axios = require('axios');
const tokenService = require('../../services/token-service');


module.exports = {
  getFederatedCatalog: async (ctx, next) => {
    try {
      const accessToken = await tokenService.getAccessToken();
      if (!accessToken) {
        ctx.body = { message: 'Access token not available. Please authenticate first.' };
        ctx.status = 401;
        return;
      }

      // URL for fetching the federated catalog
      const countCatalogUrl = `${process.env.CATALOG_BASE_URL}/management/pagination/count?type=federatedCatalog`;

      const body = { ...ctx.request.body };
      delete body.offset
      delete body.limit
      delete body.sortOrder
      delete body.sortField

      const countResponse = await axios.post(countCatalogUrl, body, {
        headers: {
          Authorization: `Bearer ${accessToken}`
        }
      });

      // URL for fetching the federated catalog
      const catalogUrl = `${process.env.CATALOG_BASE_URL}/management/federatedcatalog/request`;

      // Fetch the federated catalog using the access token
      const catalogsResponse = await axios.post(catalogUrl, ctx.request.body, {
        headers: {
          Authorization: `Bearer ${accessToken}`
        }
      });

      catalogsResponse.data.forEach(catalog => {
        delete catalog['http://www.w3.org/ns/dcat#service'];
        delete catalog['originator'];

        const datasets = catalog['http://www.w3.org/ns/dcat#dataset'];
        if (Array.isArray(datasets)) {
          datasets.forEach(dataset => {
            delete dataset['http://www.w3.org/ns/dcat#distribution'];
            delete dataset['odrl:hasPolicy'];
            delete dataset['@type'];
          });
        } else {
          delete datasets['http://www.w3.org/ns/dcat#distribution'];
          delete datasets['odrl:hasPolicy'];
          delete datasets['@type'];
        }
      });

      const finalResponse = {
        catalogs: catalogsResponse.data,
        totalElements: countResponse.data
      };

      // Respond with the fetched data
      ctx.body = finalResponse;
    } catch (err) {
      console.error('Error:', err);
      ctx.body = { message: 'Error fetching federated catalog!', details: err.message };
      ctx.status = 500;
    }
  }
};
