#!/bin/sh
# Arranque del contenedor: migraciones, DEMO opcional y servidor.
set -eu

case "${SECRET_KEY:-}${DATABASE_URL:-}" in
  *CAMBIAR*)
    echo "ERROR: .env.docker todavía tiene valores de ejemplo (CAMBIAR...). Cambie SECRET_KEY y POSTGRES_PASSWORD." >&2
    exit 1 ;;
esac

echo "Aplicando migraciones…"
alembic upgrade head

if [ "${CARGAR_DEMO:-0}" = "1" ]; then
  echo "CARGAR_DEMO=1: cargando datos DEMO sintéticos si faltan…"
  python scripts/generar_demo.py --si-falta || echo "No se pudo cargar la DEMO (la aplicación arranca igual)."
fi

if [ -n "${ADMIN_CORREO:-}" ] && [ -n "${ADMIN_CONTRASENA:-}" ]; then
  python scripts/crear_admin.py --correo "$ADMIN_CORREO" --contrasena-env ADMIN_CONTRASENA --si-existe-omitir \
    || echo "No se pudo crear el administrador (revise ADMIN_CORREO y ADMIN_CONTRASENA)."
fi

echo "VÍA SEGURA escuchando en el puerto 8000"
exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 --proxy-headers
