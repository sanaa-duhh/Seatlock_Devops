FROM node:26-alpine@sha256:143494b1da2945f061539253adc65e4f1569ddf07da2d384c022c791a9d90a4a AS build
WORKDIR /app
COPY package*.json .
RUN npm ci
COPY . .
# Baked into the bundle so the UI shows which commit is deployed.
ARG APP_VERSION=dev
ENV VITE_APP_VERSION=$APP_VERSION
RUN npm run build

FROM nginxinc/nginx-unprivileged:stable-alpine@sha256:15c994d10d6d78658721c3bcafff14cb281fba2a4bdf9d5ba92c416a472516e3
USER root
RUN apk upgrade --no-cache \
    && rm -f /etc/nginx/conf.d/default.conf \
    && chown 101:101 /etc/nginx/conf.d
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --chmod=755 nginx-dns.envsh /docker-entrypoint.d/05-seatlock-dns.envsh
USER 101
EXPOSE 8080
