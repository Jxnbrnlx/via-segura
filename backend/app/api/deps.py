"""Dependencias de FastAPI: configuración, sesión de base de datos, filtros, fuente y administrador."""
from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Annotated

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError
from sqlalchemy.orm import Session

from .. import models
from ..config import Configuracion
from ..schemas.filtros import Filtros, Paginacion
from ..seguridad import ErrorToken, decodificar_token
from ..services import consultas
from ..services.calidad import CAJA_BOGOTA
from .errores import ErrorApi, detalles_validacion


def obtener_config(request: Request) -> Configuracion:
    return request.app.state.config


def obtener_db(request: Request) -> Iterator[Session]:
    sesion = request.app.state.fabrica_sesion()
    try:
        yield sesion
    finally:
        sesion.close()


Config = Annotated[Configuracion, Depends(obtener_config)]
BaseDatos = Annotated[Session, Depends(obtener_db)]


def obtener_filtros(
    fuente: Annotated[str | None, Query(max_length=60, description="Código o alias de la fuente (por defecto: arcgis)")] = None,
    fecha_desde: Annotated[date | None, Query(description="AAAA-MM-DD")] = None,
    fecha_hasta: Annotated[date | None, Query(description="AAAA-MM-DD")] = None,
    anio: Annotated[list[int], Query(description="Repetible")] = [],  # noqa: B006
    mes: Annotated[list[int], Query(description="1-12, repetible")] = [],  # noqa: B006
    localidad: Annotated[list[str], Query(description="Nombre o clave, repetible")] = [],  # noqa: B006
    clase: Annotated[list[str], Query(description="Clase de siniestro, repetible")] = [],  # noqa: B006
    gravedad: Annotated[list[str], Query(description="Con Muertos, Con Heridos, Solo Daños o 'todas'")] = [],  # noqa: B006
    actor: Annotated[list[str], Query(description="Condición del actor vial (PEATON, CICLISTA...), repetible")] = [],  # noqa: B006
) -> Filtros:
    try:
        return Filtros(fuente=fuente, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, anio=anio, mes=mes,
                       localidad=localidad, clase=clase, gravedad=gravedad, actor=actor)
    except ValidationError as exc:
        raise ErrorApi(422, "parametros_invalidos", "Hay filtros inválidos.", detalles_validacion(exc.errors())) from None


FiltrosDep = Annotated[Filtros, Depends(obtener_filtros)]


def obtener_paginacion(
    pagina: Annotated[int, Query(ge=1, le=100_000)] = 1,
    tamano: Annotated[int, Query(ge=1, le=200, description="Máximo 200")] = 50,
) -> Paginacion:
    return Paginacion(pagina=pagina, tamano=tamano)


PaginacionDep = Annotated[Paginacion, Depends(obtener_paginacion)]


def obtener_fuente(filtros: FiltrosDep, db: BaseDatos) -> models.FuenteDatos:
    return consultas.resolver_fuente(db, filtros.fuente)


FuenteDep = Annotated[models.FuenteDatos, Depends(obtener_fuente)]


def interpretar_bbox(texto: str | None) -> tuple[float, float, float, float] | None:
    """'oeste,sur,este,norte' en grados (como Leaflet getBounds().toBBoxString())."""
    if not texto:
        return None
    try:
        oeste, sur, este, norte = (float(v) for v in texto.split(","))
    except ValueError:
        raise ErrorApi(422, "parametros_invalidos", "bbox debe ser 'oeste,sur,este,norte' en grados.") from None
    if not (oeste < este and sur < norte and -180 <= oeste <= 180 and -180 <= este <= 180
            and -90 <= sur <= 90 and -90 <= norte <= 90):
        raise ErrorApi(422, "parametros_invalidos", "bbox fuera de rango o con los extremos invertidos.")
    # Se recorta a la caja amplia de Bogotá: fuera de ella no hay coordenadas válidas.
    return (max(oeste, CAJA_BOGOTA.lon_min), max(sur, CAJA_BOGOTA.lat_min),
            min(este, CAJA_BOGOTA.lon_max), min(norte, CAJA_BOGOTA.lat_max))


_bearer = HTTPBearer(auto_error=False)


def admin_actual(credenciales: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
                 db: BaseDatos, cfg: Config) -> models.UsuarioAdmin:
    cabeceras = {"WWW-Authenticate": "Bearer"}
    if credenciales is None or credenciales.scheme.lower() != "bearer":
        raise ErrorApi(401, "no_autenticado", "Inicie sesión como administrador.", cabeceras=cabeceras)
    try:
        datos = decodificar_token(credenciales.credentials, cfg.secret_key)
    except ErrorToken as exc:
        raise ErrorApi(401, "token_invalido", str(exc), cabeceras=cabeceras) from None
    usuario = db.get(models.UsuarioAdmin, int(datos["sub"]))
    if usuario is None or not usuario.activo:
        raise ErrorApi(401, "token_invalido", "La cuenta no existe o está desactivada.", cabeceras=cabeceras)
    return usuario


AdminDep = Annotated[models.UsuarioAdmin, Depends(admin_actual)]
