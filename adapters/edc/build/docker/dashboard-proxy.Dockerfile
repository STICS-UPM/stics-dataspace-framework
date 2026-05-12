FROM python:3.12-alpine

WORKDIR /app

COPY server.py /app/server.py

ENV PROXY_PORT=8080
ENV PROXY_CONFIG_FILE=/app/config/proxy-config.json
ENV PROXY_AUTH_FILE=/app/config/proxy-auth.json

EXPOSE 8080

CMD ["python", "/app/server.py"]
