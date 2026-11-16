"""Endpoints de administración (todos exigen token, salvo el inicio de sesión)."""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, Path, Query, Request, UploadFile
from sqlalchemy import func, select

from .. import models
from ..api.deps import AdminDep, BaseDatos, Config, PaginacionDep
from ..api.errores import ErrorApi
from ..config import Configuracion
from ..schemas.admin import ConfirmarEntrada, LoginEntrada, SincronizarEntrada
from ..seguridad import crear_token, verificar_contrasena
from ..services.archivos import ErrorArchivo, recibir_archivo
from ..services.geo_localidades import ErrorGeo
from ..services.importador_excel import TIPOS, ErrorImportacion, ImportadorArchivos
from ..services.mapeos import ErrorMapeo, cargar_mapeo, listar_mapeos
from ..services.repositorio_sql import RepositorioSQL

log = logging.getLogger("via_segura.admin")
router = APIRouter()
_CANDADO_SYNC = threading.Lock()
MB = 1024 * 1024
ERRORES_CARGA = (ErrorArchivo, ErrorImportacion, ErrorMapeo, ErrorGeo)


def crear_importador(sesion, cfg: Configuracion) -> ImportadorArchivos:
    return ImportadorArchivos(
        RepositorioSQL(sesion), cfg.carga_directorio, cfg.geo_directorio, bloque=cfg.importar_bloque,
        tolerancia_geo=cfg.geo_tolerancia_grados, coherencia_percentil=cfg.coherencia_percentil,
        coherencia_margen=cfg.coherencia_margen_grados, conservar_archivo=cfg.conservar_archivo_importado)


# ------------------------------------------------------------------------------- sesión

@router.post("/auth/login", summary="Iniciar sesión de administrador")
def iniciar_sesion(entrada: LoginEntrada, db: BaseDatos, cfg: Config) -> dict:
    usuario = db.scalar(select(models.UsuarioAdmin).where(models.UsuarioAdmin.correo == entrada.correo))
    activo = usuario is not None and usuario.activo
    if not verificar_contrasena(entrada.contrasena, usuario.hash_contrasena if activo else None):
        log.warning("Inicio de sesión fallido")
        raise ErrorApi(401, "credenciales_invalidas", "Correo o contraseña incorrectos.")
    usuario.ultimo_acceso = datetime.now(timezone.utc)
    db.commit()
    token, expira = crear_token(usuario.id, usuario.rol, cfg.secret_key, cfg.token_expira_minutos)
    return {"access_token": token, "token_type": "bearer", "expira_en": expira.isoformat(),
            "usuario": {"correo": usuario.correo, "rol": usuario.rol}}


@router.get("/me", summary="Administrador actual")
def yo(admin: AdminDep) -> dict:
    return {"correo": admin.correo, "rol": admin.rol,
            "ultimo_acceso": admin.ultimo_acceso.isoformat() if admin.ultimo_acceso else None}


# ------------------------------------------------------------------------------- mapeos

@router.get("/mappings", summary="Mapeos de columnas disponibles")
def mapeos(_admin: AdminDep) -> dict:
    salida = []
    for codigo in listar_mapeos():
        m = cargar_mapeo(codigo)
        salida.append({"codigo": codigo, "descripcion": m.descripcion, "verificado": m.verificado,
                       "fuente": m.fuente_codigo,
                       "hojas": {t: {"nombres_hoja": h.nombres_hoja, "campos": h.campos} for t, h in m.hojas.items()}})
    return {"datos": salida, "tipos_de_carga": list(TIPOS)}


# ------------------------------------------------------------------------------- importaciones

def _publica(imp: models.Importacion, detalle: bool = False) -> dict:
    datos = {
        "id": imp.id, "tipo": imp.tipo, "modo": imp.modo, "archivo": imp.archivo, "hoja": imp.hoja,
        "estado": imp.estado, "fuente_id": imp.fuente_id, "usuario_id": imp.usuario_id,
        "iniciada_en": imp.iniciada_en.isoformat() if imp.iniciada_en else None,
        "finalizada_en": imp.finalizada_en.isoformat() if imp.finalizada_en else None,
        "filas_revisadas": imp.filas_revisadas, "filas_validas": imp.filas_validas,
        "filas_rechazadas": imp.filas_rechazadas,
        "fecha_min_evento": imp.fecha_min_evento.isoformat() if imp.fecha_min_evento else None,
        "fecha_max_evento": imp.fecha_max_evento.isoformat() if imp.fecha_max_evento else None,
    }
    if detalle:
        resumen = json.loads(json.dumps(imp.resumen or {}, default=str))
        if isinstance(resumen.get("archivo"), dict):
            resumen["archivo"].pop("token", None)  # referencia interna al archivo temporal
        datos.update(mapeo=imp.mapeo, errores=imp.errores or [], resumen=resumen)
    return datos


@router.post("/imports", status_code=201, summary="Subir y previsualizar un archivo")
def cargar_archivo(
    admin: AdminDep, db: BaseDatos, cfg: Config,
    archivo: Annotated[UploadFile, File(description="CSV, XLSX o GeoJSON")],
    tipo: Annotated[str, Form(description="siniestros, actores, vehiculos, poblacion o localidades")],
    mapeo: Annotated[str | None, Form(max_length=60)] = None,
    hoja: Annotated[str | None, Form(max_length=120)] = None,
    columnas: Annotated[str | None, Form(max_length=4000, description='JSON {"campo": "Columna"}')] = None,
) -> dict:
    sobrescribir = None
    if columnas:
        try:
            sobrescribir = json.loads(columnas)
        except json.JSONDecodeError:
            raise ErrorApi(422, "parametros_invalidos", "columnas debe ser un objeto JSON.") from None
        if (not isinstance(sobrescribir, dict) or len(sobrescribir) > 30
                or not all(isinstance(k, str) and isinstance(v, str) for k, v in sobrescribir.items())):
            raise ErrorApi(422, "parametros_invalidos", 'columnas debe ser {"campo": "Columna"} con textos.')
    try:
        recibido = recibir_archivo(archivo.file, archivo.filename, archivo.content_type, cfg.carga_directorio,
                                   max_bytes=cfg.carga_max_mb * MB,
                                   max_descomprimido=cfg.carga_max_descomprimido_mb * MB)
        pv = crear_importador(db, cfg).previsualizar(recibido, tipo=tipo, mapeo_codigo=mapeo, hoja=hoja,
                                                     sobrescribir=sobrescribir, usuario_id=admin.id)
    except ERRORES_CARGA as exc:
        raise ErrorApi(400, "archivo_rechazado", str(exc)) from None
    finally:
        archivo.file.close()
    return {"datos": pv.como_dict()}


@router.get("/imports", summary="Historial de importaciones y sincronizaciones")
def historial(
    _admin: AdminDep, db: BaseDatos, paginacion: PaginacionDep,
    tipo: Annotated[str | None, Query(pattern="^(arcgis|excel)$")] = None,
    estado: Annotated[str | None, Query(pattern="^(pendiente|previsualizada|en_proceso|completada|fallida|cancelada)$")] = None,
) -> dict:
    cond = []
    if tipo:
        cond.append(models.Importacion.tipo == tipo)
    if estado:
        cond.append(models.Importacion.estado == estado)
    total = db.scalar(select(func.count()).select_from(models.Importacion).where(*cond)) or 0
    filas = db.scalars(select(models.Importacion).where(*cond)
                       .order_by(models.Importacion.iniciada_en.desc(), models.Importacion.id.desc())
                       .offset(paginacion.desplazamiento).limit(paginacion.tamano)).all()
    return {"datos": [_publica(i) for i in filas],
            "paginacion": {"pagina": paginacion.pagina, "tamano": paginacion.tamano, "total": total,
                           "paginas": (total + paginacion.tamano - 1) // paginacion.tamano}}


def _importacion(db, importacion_id: int) -> models.Importacion:
    imp = db.get(models.Importacion, importacion_id, populate_existing=True)
    if imp is None:
        raise ErrorApi(404, "no_encontrado", f"No existe la importación n.º {importacion_id}.")
    return imp


@router.get("/imports/{importacion_id}", summary="Detalle de una importación")
def detalle(importacion_id: Annotated[int, Path(ge=1)], _admin: AdminDep, db: BaseDatos) -> dict:
    return {"datos": _publica(_importacion(db, importacion_id), detalle=True)}


def _confirmar_en_segundo_plano(fabrica, cfg: Configuracion, importacion_id: int, metadatos: dict) -> None:
    with fabrica() as sesion:
        try:
            crear_importador(sesion, cfg).confirmar(importacion_id, metadatos_fuente=metadatos, reservada=True)
        except Exception:  # noqa: BLE001 - el estado 'fallida' queda registrado por el importador
            log.exception("Fallo al procesar la importación %s", importacion_id)


@router.post("/imports/{importacion_id}/confirm", status_code=202, summary="Confirmar (procesa en segundo plano)")
def confirmar(
    importacion_id: Annotated[int, Path(ge=1)], admin: AdminDep, db: BaseDatos, cfg: Config,
    request: Request, tareas: BackgroundTasks, entrada: ConfirmarEntrada | None = None,
) -> dict:
    _importacion(db, importacion_id)
    try:
        crear_importador(db, cfg).reservar(importacion_id)
    except ERRORES_CARGA as exc:
        raise ErrorApi(409, "no_confirmable", str(exc)) from None
    entrada = entrada or ConfirmarEntrada()
    metadatos = {
        "url": entrada.url, "fecha_publicacion": entrada.fecha_publicacion,
        "fecha_descarga": datetime(entrada.fecha_descarga.year, entrada.fecha_descarga.month,
                                   entrada.fecha_descarga.day, tzinfo=timezone.utc) if entrada.fecha_descarga else None,
    }
    tareas.add_task(_confirmar_en_segundo_plano, request.app.state.fabrica_sesion, cfg, importacion_id, metadatos)
    return {"datos": {"id": importacion_id, "estado": "en_proceso",
                      "mensaje": "La importación se está procesando. Consulte su estado en el historial.",
                      "seguimiento": f"/api/v1/admin/imports/{importacion_id}"}}


@router.post("/imports/{importacion_id}/cancel", summary="Cancelar una previsualización")
def cancelar(importacion_id: Annotated[int, Path(ge=1)], _admin: AdminDep, db: BaseDatos, cfg: Config) -> dict:
    _importacion(db, importacion_id)
    try:
        crear_importador(db, cfg).cancelar(importacion_id)
    except ERRORES_CARGA as exc:
        raise ErrorApi(409, "no_cancelable", str(exc)) from None
    return {"datos": {"id": importacion_id, "estado": "cancelada"}}


# ------------------------------------------------------------------------------- ArcGIS

def _sincronizar_en_segundo_plano(ejecutor, entrada: SincronizarEntrada, usuario_id: int) -> None:
    if not _CANDADO_SYNC.acquire(blocking=False):
        log.warning("Ya hay una sincronización en curso; se descarta la nueva.")
        return
    try:
        ejecutor(modo=entrada.modo, desde_anio=entrada.desde_anio, max_paginas=entrada.max_paginas,
                 usuario_id=usuario_id)
    except Exception:  # noqa: BLE001 - la importación queda 'fallida' y se registra el error
        log.exception("Fallo en la sincronización ArcGIS")
    finally:
        _CANDADO_SYNC.release()


@router.post("/sync/arcgis", status_code=202, summary="Sincronizar con ArcGIS (segundo plano)")
def sincronizar(admin: AdminDep, db: BaseDatos, request: Request, tareas: BackgroundTasks,
                entrada: SincronizarEntrada | None = None) -> dict:
    entrada = entrada or SincronizarEntrada()
    hace_12h = datetime.now(timezone.utc) - timedelta(hours=12)
    en_curso = db.scalar(select(models.Importacion.id).where(
        models.Importacion.tipo == "arcgis", models.Importacion.estado == "en_proceso",
        models.Importacion.iniciada_en >= hace_12h).limit(1))
    if en_curso is not None or _CANDADO_SYNC.locked():
        raise ErrorApi(409, "sincronizacion_en_curso", "Ya hay una sincronización en curso. Espere a que termine.")
    tareas.add_task(_sincronizar_en_segundo_plano, request.app.state.ejecutor_sync, entrada, admin.id)
    return {"datos": {"mensaje": "Sincronización iniciada. Si el servicio no responde, se conservan los datos "
                                 "guardados y la importación queda como 'fallida'.",
                      "modo": entrada.modo, "desde_anio": entrada.desde_anio,
                      "seguimiento": "/api/v1/admin/imports?tipo=arcgis"}}
