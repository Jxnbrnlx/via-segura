"""Endpoints públicos (solo lectura). Todos aceptan los filtros comunes y el parámetro `fuente`."""
from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import StreamingResponse

from ..api.deps import BaseDatos, Config, FiltrosDep, FuenteDep, PaginacionDep, interpretar_bbox
from ..api.errores import ErrorApi
from ..services import concentracion, consultas, exportacion

router = APIRouter()
VERSION = "0.7.0"


@router.get("/health", summary="Estado del servicio")
def health(db: BaseDatos) -> dict:
    ok = consultas.salud(db)
    return {"estado": "ok" if ok else "degradado", "base_de_datos": "ok" if ok else "sin conexión", "version": VERSION}


@router.get("/sources", summary="Fichas de las fuentes de datos")
def fuentes(db: BaseDatos) -> dict:
    return {"datos": consultas.listar_fuentes(db),
            "advertencias": ["Cada consulta usa UNA fuente; las cifras de fuentes distintas no se suman."]}


@router.get("/metadata/fields", summary="Campos, dimensiones disponibles y valores para filtros")
def metadatos(fuente: FuenteDep, db: BaseDatos) -> dict:
    return consultas.metadatos_campos(db, fuente)


@router.get("/dashboard/summary", summary="Indicadores principales")
def resumen(fuente: FuenteDep, filtros: FiltrosDep, db: BaseDatos) -> dict:
    return consultas.resumen_dashboard(db, fuente, filtros)


@router.get("/accidents", summary="Siniestros (tabla paginada)")
def siniestros(
    fuente: FuenteDep, filtros: FiltrosDep, paginacion: PaginacionDep, db: BaseDatos,
    orden: Annotated[str, Query(max_length=20, description="fecha, hora, localidad, clase, gravedad o id; '-' = descendente")] = "-fecha",
    q: Annotated[str | None, Query(max_length=100, description="Busca en dirección, barrio y vía")] = None,
    solo_con_coordenada: bool = False,
) -> dict:
    return consultas.listar_siniestros(db, fuente, filtros, paginacion, orden, q, solo_con_coordenada)


@router.get("/accidents/geojson", summary="Puntos con coordenada válida (GeoJSON)")
def siniestros_geojson(
    fuente: FuenteDep, filtros: FiltrosDep, db: BaseDatos,
    limite: Annotated[int, Query(ge=1, le=10_000)] = 2000,
    bbox: Annotated[str | None, Query(max_length=100, description="oeste,sur,este,norte")] = None,
) -> dict:
    return consultas.geojson_siniestros(db, fuente, filtros, limite, interpretar_bbox(bbox))


@router.get("/accidents/{id_registro:int}", summary="Detalle de un siniestro")
def siniestro(id_registro: Annotated[int, Path(ge=1)], fuente: FuenteDep, db: BaseDatos) -> dict:
    return consultas.detalle_siniestro(db, fuente, id_registro)


@router.get("/analytics/by-locality", summary="Siniestros, personas y tasas por localidad")
def por_localidad(fuente: FuenteDep, filtros: FiltrosDep, db: BaseDatos) -> dict:
    return consultas.por_localidad(db, fuente, filtros)


@router.get("/analytics/by-period", summary="Serie por año o por mes")
def por_periodo(fuente: FuenteDep, filtros: FiltrosDep, db: BaseDatos,
                agrupacion: Annotated[str, Query(pattern="^(anio|mes)$")] = "anio") -> dict:
    return consultas.por_periodo(db, fuente, filtros, agrupacion)


@router.get("/analytics/by-hour-day", summary="Matriz día de la semana × hora")
def por_hora_dia(fuente: FuenteDep, filtros: FiltrosDep, db: BaseDatos) -> dict:
    return consultas.por_hora_dia(db, fuente, filtros)


@router.get("/analytics/by-actor", summary="Personas por condición, sexo o rango de edad")
def por_actor(fuente: FuenteDep, filtros: FiltrosDep, db: BaseDatos,
              dimension: Annotated[str, Query(pattern="^(condicion|sexo|rango_edad)$")] = "condicion") -> dict:
    return consultas.por_actor(db, fuente, filtros, dimension)


@router.get("/analytics/by-severity", summary="Siniestros por gravedad y personas por estado")
def por_gravedad(fuente: FuenteDep, filtros: FiltrosDep, db: BaseDatos) -> dict:
    return consultas.por_gravedad(db, fuente, filtros)


@router.get("/analytics/by-class", summary="Siniestros por clase")
def por_clase(fuente: FuenteDep, filtros: FiltrosDep, db: BaseDatos) -> dict:
    return consultas.por_clase(db, fuente, filtros)


@router.get("/analytics/concentration", summary="Cuadrícula de concentración de registros")
def concentracion_geografica(
    fuente: FuenteDep, filtros: FiltrosDep, db: BaseDatos,
    tamano_celda_m: Annotated[int, Query(ge=concentracion.TAMANO_MIN_M, le=concentracion.TAMANO_MAX_M)] = concentracion.TAMANO_DEFECTO_M,
    minimo: Annotated[int, Query(ge=1, le=10_000, description="Conteo mínimo para devolver una celda")] = 1,
    bbox: Annotated[str | None, Query(max_length=100)] = None,
) -> dict:
    return consultas.concentracion_geografica(db, fuente, filtros, tamano_celda_m, minimo, interpretar_bbox(bbox))


@router.get("/localities/geojson", summary="Mapa temático por localidad")
def localidades_geojson(fuente: FuenteDep, filtros: FiltrosDep, db: BaseDatos, cfg: Config) -> dict:
    return consultas.geojson_localidades(db, fuente, filtros, cfg.geo_directorio)


@router.get("/export/accidents.csv", summary="Exportar los siniestros filtrados (CSV)")
def exportar_csv(
    fuente: FuenteDep, filtros: FiltrosDep, db: BaseDatos, cfg: Config, request: Request,
    formato: Annotated[str, Query(pattern="^(excel|estandar)$",
                                  description="excel: ';' y coma decimal · estandar: ',' y punto decimal")] = "excel",
    q: Annotated[str | None, Query(max_length=100, description="Busca en dirección, barrio y vía")] = None,
    solo_con_coordenada: bool = False,
):
    """Mismos filtros que /accidents. Una fila por siniestro; las personas van en columnas aparte
    (derivado de actor vial). No incluye el número de formulario ni datos personales."""
    total = consultas.contar_listado(db, consultas.condiciones_listado(filtros, fuente.id, q, solo_con_coordenada))
    if total > cfg.exportar_max_filas:
        miles = lambda n: f"{n:,}".replace(",", ".")  # noqa: E731
        raise ErrorApi(400, "exportacion_muy_grande",
                       f"La consulta tiene {miles(total)} siniestros y el máximo por archivo es "
                       f"{miles(cfg.exportar_max_filas)}. Acote los filtros (por ejemplo, por año) y descargue por partes.")
    fabrica = request.app.state.fabrica_sesion
    fuente_id, codigo = fuente.id, fuente.codigo

    def contenido():
        # Sesión propia: la del request puede cerrarse antes de terminar de enviar el archivo.
        with fabrica() as sesion:
            yield from exportacion.generar_csv(
                consultas.iterar_exportacion(sesion, fuente_id, codigo, filtros, q, solo_con_coordenada), formato)

    nombre = exportacion.nombre_archivo(codigo, date.today().strftime("%Y%m%d"))
    return StreamingResponse(contenido(), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{nombre}"',
        "X-Total-Registros": str(total), "Cache-Control": "no-store"})
