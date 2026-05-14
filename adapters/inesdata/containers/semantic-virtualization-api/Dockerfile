FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PORT=8000 \
    MORPH_KGV_CONFIG=/opt/morph-kgv/examples/csv/config.ini

WORKDIR /app

COPY morph-kgv /opt/morph-kgv
COPY morph_kgv_http_server.py /app/morph_kgv_http_server.py

RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential curl \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir /opt/morph-kgv

EXPOSE 8000

CMD ["python", "/app/morph_kgv_http_server.py"]
