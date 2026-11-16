# VÍA SEGURA: imagen de la aplicación (API + página web).
# Se construye con:  docker compose build     (ver README.md)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN useradd --create-home --uid 10001 viasegura

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY backend ./backend
COPY frontend ./frontend
COPY scripts ./scripts
COPY docker ./docker

# Leaflet y Chart.js se descargan del registro de npm con verificación SHA-512 (requiere Internet al construir).
RUN python scripts/descargar_librerias.py \
 && mkdir -p backend/app/data/cargas backend/app/data/geo \
 && chown -R viasegura:viasegura backend/app/data

USER viasegura
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"
CMD ["sh", "docker/arranque.sh"]
