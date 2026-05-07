FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PORT=8000 \
    COTTAS_FILE=/data/sample.cottas

WORKDIR /app

COPY . /app

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir "pycottas==1.0.0" "pycottas-endpoint[cli,web]>=0.5.3,<1.0.0" \
    && mkdir -p /data \
    && python -m pycottas rdf2cottas \
        --rdf_file /app/src/pycottas/prueba.ttl \
        --cottas_file /data/sample.cottas \
        --index SPO

EXPOSE 8000

CMD ["sh", "-c", "pycottas-endpoint serve \"${COTTAS_FILE:-/data/sample.cottas}\" --host 0.0.0.0 --port \"${PORT:-8000}\""]
