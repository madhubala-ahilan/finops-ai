FROM node:22-alpine AS build

WORKDIR /app

ARG VITE_API_BASE_URL
ARG BUILD_VERSION=local
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_FINOPS_BUILD_VERSION=$BUILD_VERSION

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["/bin/sh", "-c", "printf 'window.__FINOPS_CONFIG__ = { API_BASE_URL: \"%s\", BUILD_VERSION: \"%s\" };\\n' \"${VITE_API_BASE_URL:-}\" \"${FINOPS_FRONTEND_VERSION:-${VITE_FINOPS_BUILD_VERSION:-local}}\" > /usr/share/nginx/html/config.js && nginx -g 'daemon off;'"]
