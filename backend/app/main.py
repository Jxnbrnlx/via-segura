"""Aplicación FastAPI de VÍA SEGURA.

Ejecutar (desde la raíz del proyecto, con el entorno virtual activo):
    uvicorn app.main:app --app-dir backend --reload
Aplicación: http://127.0.0.1:8000/   ·   Documentación de la API: http://127.0.0.1:8000/api/docs
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.errores import registrar_manejadores
from .api.middlewares import CabecerasSeguridad, LimitadorPeticiones, ProteccionCargas
from .config import Configuracion, get_settings
from .routers import admin, publico
from .seguridad import ErrorToken, decodificar_token

log = logging.getLogger("via_segura")
MB = 1024 * 1024
RUTA_LOGIN = "/api/v1/admin/auth/login"
RUTA_CARGAS = "/api/v1/admin/imports"


def ejecutor_sync_por_defecto(cfg: Configuracion, fabrica):
    """Ejecuta una sincronización ArcGIS completa con su propia sesión (para tareas en segundo plano)."""
    def ejecutar(*, modo: str, desde_anio: int | None, max_paginas: int | None, usuario_id: int | None):
        from .services.arcgis_client import ClienteArcGIS
        from .services.arcgis_sync import SincronizadorArcGIS
        from .services.repositorio_sql import RepositorioSQL

        with ClienteArcGIS(cfg.arcgis_base_url, pagina=cfg.arcgis_pagina, timeout_s=cfg.arcgis_timeout_s,
                           reintentos=cfg.arcgis_reintentos) as cliente, fabrica() as sesion:
            return SincronizadorArcGIS(
                cliente, RepositorioSQL(sesion), ventana_dias=cfg.arcgis_ventana_dias,
                lote_formularios=cfg.arcgis_lote_formularios, coherencia_percentil=cfg.coherencia_percentil,
                coherencia_margen=cfg.coherencia_margen_grados,
            ).ejecutar(modo, desde_anio=desde_anio, max_paginas=max_paginas, usuario_id=usuario_id)
    return ejecutar


def create_app(config: Configuracion | None = None, fabrica_sesion=None, ejecutor_sync=None) -> FastAPI:
    cfg = config or get_settings()
    if fabrica_sesion is None:
        from .database import SessionLocal

        fabrica_sesion = SessionLocal

    @asynccontextmanager
    async def ciclo_de_vida(_app: FastAPI):
        cfg.carga_directorio.mkdir(parents=True, exist_ok=True)
        cfg.geo_directorio.mkdir(parents=True, exist_ok=True)
        if cfg.entorno != "produccion" and len(cfg.secret_key) < 32:
            log.warning("SECRET_KEY de desarrollo: defina una propia en .env antes de publicar la aplicación.")
        yield

    app = FastAPI(
        title="VÍA SEGURA - API",
        version=publico.VERSION,
        description="Consulta de siniestralidad vial histórica de Bogotá D.C. con datos oficiales. "
                    "No es navegación, no es tiempo real y no predice siniestros.",
        lifespan=ciclo_de_vida,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.config = cfg
    app.state.fabrica_sesion = fabrica_sesion
    app.state.ejecutor_sync = ejecutor_sync or ejecutor_sync_por_defecto(cfg, fabrica_sesion)

    registrar_manejadores(app)
    app.include_router(publico.router, prefix="/api/v1", tags=["consulta pública"])
    app.include_router(admin.router, prefix="/api/v1/admin", tags=["administración"])

    # Frontend: la página principal en "/" y los archivos en "/static" (la API sigue en "/api").
    frontend = cfg.frontend_directorio
    if (frontend / "index.html").is_file():
        app.mount("/static", StaticFiles(directory=frontend), name="static")

        @app.get("/", include_in_schema=False)
        def inicio() -> FileResponse:
            return FileResponse(frontend / "index.html", headers={"Cache-Control": "no-cache"})

    def token_valido(token: str) -> bool:
        try:
            decodificar_token(token, cfg.secret_key)
            return True
        except ErrorToken:
            return False

    # El último middleware agregado es el más externo.
    app.add_middleware(ProteccionCargas, ruta=RUTA_CARGAS, max_bytes=cfg.carga_max_mb * MB + MB,
                       token_valido=token_valido)
    app.add_middleware(LimitadorPeticiones, limite_por_minuto=cfg.limite_peticiones_por_minuto,
                       reglas={RUTA_LOGIN: cfg.limite_login_por_minuto})
    app.add_middleware(CORSMiddleware, allow_origins=cfg.cors_lista, allow_methods=["GET", "POST"],
                       allow_headers=["Authorization", "Content-Type"], allow_credentials=False, max_age=600)
    app.add_middleware(CabecerasSeguridad)
    return app


app = create_app()
