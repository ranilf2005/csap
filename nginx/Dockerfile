# syntax=docker/dockerfile:1

FROM nginxinc/nginx-unprivileged:1.27-alpine

COPY nginx.conf /etc/nginx/nginx.conf
COPY conf.d/csap.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080 8443
