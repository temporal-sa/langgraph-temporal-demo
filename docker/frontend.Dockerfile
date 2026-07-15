FROM nginx:1.27-alpine

ENV WEB_PORT=8080 \
    DEFAULT_AGENT_BACKEND=temporal-langgraph \
    BACKEND_URL=http://backend:8000 \
    TEMPORAL_LANGGRAPH_BACKEND_URL=/api \
    TEMPORAL_UI_URL="" \
    TEMPORAL_API_UPSTREAM=http://temporal-api:8000 \
    LANGGRAPH_API_UPSTREAM=http://langgraph-api:8001 \
    TEMPORAL_LANGGRAPH_API_UPSTREAM=http://temporal-langgraph-api:8002

COPY web/ /usr/share/nginx/html/
COPY docker/web-entrypoint.sh /docker-entrypoint.d/40-generate-web-config.sh
COPY docker/nginx-default.conf.template /etc/nginx/templates/default.conf.template
RUN chmod +x /docker-entrypoint.d/40-generate-web-config.sh

EXPOSE 8080
