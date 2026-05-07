# Creating multi-stage build for production
FROM node:18-alpine as build
RUN apk add --no-cache build-base gcc autoconf automake zlib-dev libpng-dev vips-dev git > /dev/null 2>&1
ENV NODE_ENV=production \
	YARN_ENABLE_TELEMETRY=0 \
	npm_config_update_notifier=false

WORKDIR /opt/
COPY package.json yarn.lock ./
RUN yarn global add node-gyp@10.1.0 \
	&& yarn config set network-timeout 600000 -g \
	&& yarn install --production --frozen-lockfile --non-interactive
ENV PATH /opt/node_modules/.bin:$PATH
WORKDIR /opt/app
COPY package.json yarn.lock ./
COPY config ./config
COPY content ./content
COPY database ./database
COPY favicon.png generate-env.sh jsconfig.json ./
COPY public ./public
COPY scripts ./scripts
COPY src ./src
COPY types ./types
RUN yarn build

# Creating final production image
FROM node:18-alpine
RUN apk add --no-cache vips-dev
ENV NODE_ENV=production
WORKDIR /opt/
COPY --from=build /opt/node_modules ./node_modules
WORKDIR /opt/app
COPY --from=build /opt/app ./
ENV PATH /opt/node_modules/.bin:$PATH

RUN chown -R node:node /opt/app
USER node

# Importing default Strapi content (Home page, etc)
RUN ./generate-env.sh && yarn strapi import --force -f content/base-content.tar.gz && rm .env

EXPOSE 1337
CMD ["yarn", "start"]
