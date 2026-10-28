FROM node:24-alpine@sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1 AS build
WORKDIR /app
COPY package*.json .
RUN npm ci
COPY . .
# Baked into the bundle so the UI shows which commit is deployed.
ARG APP_VERSION=dev
ENV VITE_APP_VERSION=$APP_VERSION
RUN npm run build

FROM nginxinc/nginx-unprivileged:stable-alpine@sha256:f5116ed4606f3eb015dd4a8e28cb9b351476dc0ad4bc6e9f93b19cec130cdf03
USER root
RUN apk upgrade --no-cache \
    && rm -f /etc/nginx/conf.d/default.conf \
    && chown 101:101 /etc/nginx/conf.d
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/default.conf.template
ENV SEATLOCK_API_HOST=backend
COPY --chmod=755 nginx-dns.envsh /docker-entrypoint.d/05-seatlock-dns.envsh
USER 101
EXPOSE 8080
