FROM node:22-alpine AS builder

WORKDIR /app

COPY app/package.json app/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY app/ .
RUN npm run lib-build -- --configuration production \
    && npm run build -- --configuration production

FROM nginx:1.27-alpine

COPY dashboard-nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist/data-dashboard/browser/ /usr/share/nginx/html/edc-dashboard/
