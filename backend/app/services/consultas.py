"""Consultas de la API pública (SQLAlchemy 2; PostgreSQL o SQLite).

Reglas que este módulo garantiza:
- Siempre UNA fuente por consulta: nunca se suman fuentes (decisión 1).
- Siniestros y personas se cuentan por separado; las personas se derivan de actores_viales y se
  rotulan "derivado de actor vial" (decisión 4).
- Coordenadas: solo se devuelven las válidas (decisión 5); el resto se cuenta y se informa.
- No se exponen formulario (IPAT), edad exacta ni ningún dato personal (decisión 6).
- Tasas solo con denominadores oficiales cargados, con fórmula y fuente (decisión 7).
- Toda respuesta lleva fuente, periodo real de los datos filtrados y filtros aplicados.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Integer, and_, cast, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from .. import models
from ..schemas.filtros import Filtros, Paginacion
from . import calidad, concentracion, geo_localidades

SE = models.SiniestroEvento
AV = models.ActorVial
VE = models.VehiculoEvento
CE = models.CausaEvento
FD = models.FuenteDatos
DO = models.DenominadorOficial

FUENTE_POR_DEFECTO = "arcgis_simur_accidentalidad"
FUENTES_EVENTOS = ("arcgis_simur_accidentalidad", "anuario_sdm_2025", "anuario_sdm_2015_2024", "demo_sintetica")
ALIAS_FUENTE = {"arcgis": "arcgis_simur_accidentalidad", "anuario_2025": "anuario_sdm_2025",
                "anuario_2015_2024": "anuario_sdm_2015_2024", "demo": "demo_sintetica"}
CODIGO_POBLACION = "poblacion_osb_localidad"
CLAVE_TOTAL_BOGOTA = "BOGOTA"

ADVERTENCIA_POR_DEFECTO = ("Por defecto se cuentan solo los siniestros con heridos o con muertos (serie comparable "
                           "entre años). Use gravedad=todas para incluir 'Solo Daños'.")
ADVERTENCIA_SOLO_DANOS = ("La categoría 'Solo Daños' no es comparable entre años: su registro cae fuertemente desde "
                          "2023 en las fuentes (observación; la causa no está documentada).")
NOTA_PERSONAS = ("Personas derivadas de la tabla de actores viales (no es un campo de la fuente). Una persona no "
                 "es un siniestro: estas cifras nunca se suman con las de siniestros.")
NOTA_CONTEOS = ("Un conteo mayor indica más registros, no necesariamente mayor riesgo: influyen la población, el "
                "flujo vehicular y la exposición.")
DIAS = calidad.DIAS_SEMANA


class ErrorConsulta(Exception):
    def __init__(self, estado: int, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.estado, self.codigo, self.mensaje = estado, codigo, mensaje


# =============================================================================== fuente y filtros

def resolver_fuente(db: Session, codigo: str | None) -> models.FuenteDatos:
    codigo = ALIAS_FUENTE.get(codigo or "", codigo) or FUENTE_POR_DEFECTO
    if codigo not in FUENTES_EVENTOS:
        raise ErrorConsulta(400, "fuente_invalida",
                            f"'{codigo}' no es una fuente de siniestros. Opciones: {', '.join(FUENTES_EVENTOS)} "
                            f"(alias: {', '.join(ALIAS_FUENTE)}).")
    fuente = db.scalar(select(FD).where(FD.codigo == codigo))
    if fuente is None:
        raise ErrorConsulta(404, "fuente_sin_datos",
                            f"La fuente '{codigo}' todavía no está registrada: no se ha importado ni sincronizado.")
    return fuente


def condiciones(f: Filtros, fuente_id: int) -> list:
    c = [SE.fuente_id == fuente_id]
    if f.fecha_desde:
        c.append(SE.fecha_evento >= f.fecha_desde)
    if f.fecha_hasta:
        c.append(SE.fecha_evento <= f.fecha_hasta)
    if f.anio:
        c.append(SE.anio.in_(f.anio))
    if f.mes:
        c.append(SE.mes.in_(f.mes))
    if f.localidad:
        c.append(SE.localidad.in_(f.localidad))
    if f.clase:
        c.append(SE.clase_siniestro.in_(f.clase))
    gravedades = f.gravedades_efectivas
    if gravedades is not None:
        c.append(SE.gravedad.in_(gravedades))
    if f.actor:
        # Alias propio: así el EXISTS se correlaciona solo con el siniestro, aunque la consulta externa use actores.
        av = aliased(AV)
        c.append(exists().where(av.siniestro_id == SE.id, av.condicion.in_(f.actor)))
    return c


def condiciones_personas(f: Filtros) -> list:
    """Con filtro de actor, las personas contadas son solo las de esa condición."""
    return [AV.condicion.in_(f.actor)] if f.actor else []


def ficha_fuente(fuente: models.FuenteDatos) -> dict:
    return {
        "codigo": fuente.codigo, "nombre": fuente.nombre, "entidad": fuente.entidad, "url": fuente.url,
        "formato": fuente.formato, "prioridad": fuente.prioridad,
        "periodo_inicio": _iso(fuente.periodo_inicio), "periodo_fin": _iso(fuente.periodo_fin),
        "fecha_publicacion": _iso(fuente.fecha_publicacion), "fecha_descarga": _iso(fuente.fecha_descarga),
        "notas": fuente.notas,
    }


def _iso(valor) -> str | None:
    return valor.isoformat() if valor else None


def periodo_filtrado(db: Session, cond: list) -> dict:
    inicio, fin, n = db.execute(select(func.min(SE.fecha_evento), func.max(SE.fecha_evento), func.count())
                                .where(*cond)).one()
    return {"inicio": _iso(inicio), "fin": _iso(fin), "registros": int(n or 0)}


def envolver(db: Session, fuente, f: Filtros, cond: list, datos, unidad: str,
             advertencias: list[str] | None = None, periodo: dict | None = None) -> dict:
    avisos = list(advertencias or [])
    if f.usa_gravedad_por_defecto:
        avisos.append(ADVERTENCIA_POR_DEFECTO)
    if f.incluye_solo_danos:
        avisos.append(ADVERTENCIA_SOLO_DANOS)
    if fuente.codigo == "anuario_sdm_2025":
        avisos.append("El anuario 2025 no incluye siniestros 'Solo Daños'.")
    periodo = periodo or periodo_filtrado(db, cond)
    if periodo["registros"] == 0:
        avisos.append("No hay registros para estos filtros en esta fuente.")
    return {
        "datos": datos,
        "unidad": unidad,
        "fuente": ficha_fuente(fuente),
        "periodo": periodo,
        "filtros": f.como_dict(),
        "advertencias": list(dict.fromkeys(avisos)),
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# =============================================================================== utilidades de conteo

def _conteo(db: Session, cond: list) -> int:
    return int(db.scalar(select(func.count()).select_from(SE).where(*cond)) or 0)


def _por(db: Session, columna, cond: list) -> dict:
    return {k: int(n) for k, n in db.execute(select(columna, func.count()).where(*cond).group_by(columna))}


def _personas_por_estado(db: Session, f: Filtros, cond: list) -> dict:
    filas = db.execute(select(AV.estado, func.count()).join(SE, AV.siniestro_id == SE.id)
                       .where(*cond, *condiciones_personas(f)).group_by(AV.estado))
    conteo = {k: int(n) for k, n in filas}
    return {"heridas": conteo.get("HERIDO", 0), "fallecidas": conteo.get("MUERTO", 0),
            "ilesas": conteo.get("ILESO", 0), "sin_estado": conteo.get(None, 0),
            "total_registradas": sum(conteo.values())}


def _fuente_tiene_personas(db: Session, fuente_id: int) -> bool:
    return db.scalar(select(AV.id).join(SE, AV.siniestro_id == SE.id).where(SE.fuente_id == fuente_id).limit(1)) is not None


def _anios(db: Session, cond: list) -> list[int]:
    return sorted(a for (a,) in db.execute(select(SE.anio).where(*cond).distinct()) if a is not None)


# =============================================================================== tasas

def calcular_tasa(db: Session, numerador: int, anios: list[int], localidades: list[str], f: Filtros,
                  unidad_numerador: str = "siniestros") -> dict:
    """tasa = numerador / Σ población de cada año del periodo × 100.000 (promedio anual por 100.000 hab.)."""
    fuente = db.scalar(select(FD).where(FD.codigo == CODIGO_POBLACION))
    if fuente is None or not db.scalar(select(exists().where(DO.fuente_id == fuente.id))):
        return {"disponible": False,
                "motivo": "No hay población oficial cargada: solo se muestran conteos. Importe el archivo de "
                          "población por localidad para calcular tasas."}
    if not anios:
        return {"disponible": False, "motivo": "No hay registros en el periodo."}
    filas = {(loc, a): p for loc, a, p in db.execute(
        select(DO.localidad, DO.anio, DO.poblacion).where(DO.fuente_id == fuente.id, DO.anio.in_(anios),
                                                          DO.localidad.in_(localidades)))}
    faltan = [f"{loc} {a}" for loc in localidades for a in anios if (loc, a) not in filas]
    if faltan:
        return {"disponible": False, "motivo": "Falta población oficial para: " + ", ".join(faltan[:10])}
    denominador = sum(filas.values())
    avisos = []
    hoy = calidad.hoy_bogota()
    if f.mes or (f.fecha_desde and (f.fecha_desde.month, f.fecha_desde.day) != (1, 1)) or \
            (f.fecha_hasta and (f.fecha_hasta.month, f.fecha_hasta.day) != (12, 31)):
        avisos.append("El periodo filtrado no cubre años completos: la tasa queda por debajo de la anual.")
    if hoy.year in anios:
        avisos.append(f"{hoy.year} es el año en curso (datos parciales): la tasa queda por debajo de la anual.")
    return {
        "disponible": True,
        "valor": round(numerador / denominador * 100_000, 2),
        "unidad": f"{unidad_numerador} por 100.000 habitantes por año",
        "formula": f"{unidad_numerador} ÷ suma de la población de cada año del periodo × 100.000",
        "numerador": numerador, "denominador": denominador, "anios": anios,
        "fuente_denominador": {"codigo": fuente.codigo, "nombre": fuente.nombre, "entidad": fuente.entidad,
                               "url": fuente.url},
        "advertencias": avisos,
    }


# =============================================================================== endpoints

def resumen_dashboard(db: Session, fuente, f: Filtros) -> dict:
    cond = condiciones(f, fuente.id)
    total = _conteo(db, cond)
    por_gravedad = _por(db, SE.gravedad, cond)
    f_sin_gravedad = f.model_copy(update={"gravedad": [], "todas_las_gravedades": True})
    solo_danos = _conteo(db, condiciones(f_sin_gravedad, fuente.id) + [SE.gravedad == "Solo Daños"])
    coord_validas = _conteo(db, cond + [SE.coordenada_valida.is_(True)])
    tiene_personas = _fuente_tiene_personas(db, fuente.id)
    personas = _personas_por_estado(db, f, cond) if tiene_personas else None
    localidades = f.localidad or [CLAVE_TOTAL_BOGOTA]
    anios = _anios(db, cond)
    kpis = [
        {"clave": "siniestros", "valor": total, "unidad": "siniestros",
         "etiqueta": "Siniestros con heridos o muertos" if f.usa_gravedad_por_defecto else "Siniestros (según filtro de gravedad)"},
        {"clave": "siniestros_con_muertos", "valor": por_gravedad.get("Con Muertos", 0), "unidad": "siniestros",
         "etiqueta": "Siniestros con al menos una persona fallecida"},
    ]
    if personas:
        kpis += [
            {"clave": "personas_heridas", "valor": personas["heridas"], "unidad": "personas",
             "etiqueta": "Personas heridas", "derivado": "actor vial"},
            {"clave": "personas_fallecidas", "valor": personas["fallecidas"], "unidad": "personas",
             "etiqueta": "Personas fallecidas", "derivado": "actor vial"},
        ]
    avisos = []
    if not tiene_personas:
        avisos.append("Esta fuente no tiene personas importadas: no se muestran heridos ni fallecidos. "
                      "Importe la hoja Actor vial (anuarios) o sincronice ArcGIS.")
    else:
        avisos.append(NOTA_PERSONAS)
    if f.actor:
        avisos.append(f"Con el filtro de actor vial, las personas contadas son solo: {', '.join(f.actor)}.")
    return envolver(db, fuente, f, cond, {
        "kpis": kpis,
        "siniestros_por_gravedad": por_gravedad,
        "solo_danos_aparte": {"valor": solo_danos, "unidad": "siniestros", "advertencia": ADVERTENCIA_SOLO_DANOS},
        "personas": personas,
        "coordenadas": {"validas": coord_validas, "sin_coordenada_valida": total - coord_validas},
        "tasa_siniestros": calcular_tasa(db, total, anios, localidades, f),
        "tasa_fallecidos": calcular_tasa(db, personas["fallecidas"], anios, localidades, f, "personas fallecidas")
        if personas else {"disponible": False, "motivo": "Sin personas importadas en esta fuente."},
    }, "siniestros", avisos)


ORDEN = {"fecha": SE.fecha_evento, "hora": SE.hora, "localidad": SE.localidad, "clase": SE.clase_siniestro,
         "gravedad": SE.gravedad, "id": SE.id_registro}


def _fila_publica(s: models.SiniestroEvento) -> dict:
    valida = bool(s.coordenada_valida)
    return {
        "id_registro": s.id_registro, "fecha": _iso(s.fecha_evento), "anio": s.anio, "mes": s.mes,
        "dia_semana": s.dia_semana, "hora": s.hora, "minuto": s.minuto,
        "localidad": s.localidad, "localidad_nombre": calidad.LOCALIDADES.get(s.localidad) if s.localidad else None,
        "direccion": s.direccion, "barrio": s.barrio, "via": s.via_nombre, "clase": s.clase_siniestro,
        "gravedad": s.gravedad, "gravedad_tradicional": s.gravedad_tradicional,
        "latitud": s.latitud if valida else None, "longitud": s.longitud if valida else None,
        "coordenada_valida": valida, "motivo_sin_coordenada": None if valida else s.motivo_coordenada,
    }


def condiciones_listado(f: Filtros, fuente_id: int, busqueda: str | None = None,
                        solo_con_coordenada: bool = False) -> list:
    """Condiciones de la tabla de siniestros (Explorador y exportación CSV)."""
    cond = condiciones(f, fuente_id)
    if solo_con_coordenada:
        cond.append(SE.coordenada_valida.is_(True))
    if busqueda:
        patron = "%" + busqueda.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        cond.append(or_(SE.direccion.ilike(patron, escape="\\"), SE.barrio.ilike(patron, escape="\\"),
                        SE.via_nombre.ilike(patron, escape="\\")))
    return cond


def _personas_por_siniestro(db: Session, ids: list[int], f: Filtros) -> dict[int, dict]:
    personas: dict[int, dict] = {}
    if not ids:
        return personas
    for sid, estado, n in db.execute(
            select(AV.siniestro_id, AV.estado, func.count())
            .where(AV.siniestro_id.in_(ids), *condiciones_personas(f))
            .group_by(AV.siniestro_id, AV.estado)):
        p = personas.setdefault(sid, {"heridas": 0, "fallecidas": 0, "ilesas": 0})
        clave = {"HERIDO": "heridas", "MUERTO": "fallecidas", "ILESO": "ilesas"}.get(estado)
        if clave:
            p[clave] += int(n)
    return personas


def contar_listado(db: Session, cond: list) -> int:
    return _conteo(db, cond)


def iterar_exportacion(db: Session, fuente_id: int, codigo_fuente: str, f: Filtros, busqueda: str | None,
                       solo_con_coordenada: bool, bloque: int = 2000):
    """Recorre los siniestros filtrados por fecha e id (paginación por clave, sin OFFSET) y produce filas públicas."""
    cond = condiciones_listado(f, fuente_id, busqueda, solo_con_coordenada)
    ultimo = None
    while True:
        consulta = select(SE).where(*cond)
        if ultimo is not None:
            fecha, ident = ultimo
            consulta = consulta.where(or_(SE.fecha_evento > fecha, and_(SE.fecha_evento == fecha, SE.id > ident)))
        filas = db.scalars(consulta.order_by(SE.fecha_evento.asc(), SE.id.asc()).limit(bloque)).all()
        if not filas:
            return
        personas = _personas_por_siniestro(db, [s.id for s in filas], f)
        vacio = {"heridas": 0, "fallecidas": 0, "ilesas": 0}
        for s in filas:
            yield dict(_fila_publica(s), fuente=codigo_fuente, personas=personas.get(s.id, vacio))
        ultimo = (filas[-1].fecha_evento, filas[-1].id)
        db.expunge_all()  # libera memoria entre bloques


def listar_siniestros(db: Session, fuente, f: Filtros, pag: Paginacion, orden: str = "-fecha",
                      busqueda: str | None = None, solo_con_coordenada: bool = False) -> dict:
    cond = condiciones_listado(f, fuente.id, busqueda, solo_con_coordenada)
    descendente = orden.startswith("-")
    columna = ORDEN.get(orden.lstrip("-"))
    if columna is None:
        raise ErrorConsulta(400, "orden_invalido", f"orden debe ser uno de: {', '.join(ORDEN)} (con '-' para descendente).")
    total = _conteo(db, cond)
    filas = db.scalars(select(SE).where(*cond)
                       .order_by(columna.desc() if descendente else columna.asc(), SE.id.desc() if descendente else SE.id.asc())
                       .offset(pag.desplazamiento).limit(pag.tamano)).all()
    personas = _personas_por_siniestro(db, [s.id for s in filas], f)
    vacio = {"heridas": 0, "fallecidas": 0, "ilesas": 0}
    datos = [dict(_fila_publica(s), personas=dict(personas.get(s.id, vacio), derivado="actor vial")) for s in filas]
    respuesta = envolver(db, fuente, f, cond, datos, "siniestros", [NOTA_PERSONAS])
    respuesta["paginacion"] = {"pagina": pag.pagina, "tamano": pag.tamano, "total": total,
                               "paginas": (total + pag.tamano - 1) // pag.tamano}
    respuesta["orden"] = orden
    return respuesta


def detalle_siniestro(db: Session, fuente, id_registro: int) -> dict:
    s = db.scalar(select(SE).where(SE.fuente_id == fuente.id, SE.id_registro == id_registro))
    if s is None:
        raise ErrorConsulta(404, "no_encontrado", f"No existe el siniestro {id_registro} en la fuente {fuente.codigo}.")
    actores = db.scalars(select(AV).where(AV.siniestro_id == s.id).order_by(AV.consecutivo_victima)).all()
    vehiculos = db.scalars(select(VE).where(VE.siniestro_id == s.id).order_by(VE.codigo_vehiculo)).all()
    causas = db.scalars(select(CE).where(CE.siniestro_id == s.id).order_by(CE.codigo_vehiculo, CE.codigo_causa)).all()
    return {
        "datos": dict(_fila_publica(s), atributos=s.atributos or {},
                      personas=[{"condicion": a.condicion, "estado": a.estado, "sexo": a.sexo,
                                 "rango_edad": a.rango_edad, "codigo_vehiculo": a.codigo_vehiculo,
                                 "muerte_posterior": a.muerte_posterior} for a in actores],
                      vehiculos=[{"codigo_vehiculo": v.codigo_vehiculo, "clase": v.clase, "servicio": v.servicio,
                                  "modalidad": v.modalidad} for v in vehiculos],
                      causas=[{"codigo_vehiculo": c.codigo_vehiculo, "codigo_causa": c.codigo_causa,
                               "nombre": c.nombre, "tipo_causa": c.tipo_causa} for c in causas]),
        "fuente": ficha_fuente(fuente),
        "advertencias": [NOTA_PERSONAS, "La edad se publica solo por rangos."],
    }


def geojson_siniestros(db: Session, fuente, f: Filtros, limite: int = 2000,
                       bbox: tuple[float, float, float, float] | None = None) -> dict:
    cond = condiciones(f, fuente.id)
    total_filtrados = _conteo(db, cond)
    cond_validas = cond + [SE.coordenada_valida.is_(True), SE.latitud.is_not(None), SE.longitud.is_not(None)]
    if bbox:
        oeste, sur, este, norte = bbox
        cond_validas += [SE.longitud >= oeste, SE.longitud <= este, SE.latitud >= sur, SE.latitud <= norte]
    total_validas = _conteo(db, cond_validas)
    filas = db.execute(select(SE.id_registro, SE.latitud, SE.longitud, SE.fecha_evento, SE.gravedad,
                              SE.clase_siniestro, SE.localidad, SE.hora)
                       .where(*cond_validas).order_by(SE.fecha_evento.desc(), SE.id.desc()).limit(limite)).all()
    features = [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"id_registro": i, "fecha": _iso(fecha), "gravedad": g, "clase": c, "localidad": loc,
                       "hora": h},
    } for i, lat, lon, fecha, g, c, loc, h in filas]
    sin_coordenada = _conteo(db, cond + [SE.coordenada_valida.is_(False)])
    avisos = [f"{sin_coordenada} registros filtrados no tienen coordenada válida y no aparecen en el mapa."] \
        if sin_coordenada else []
    if total_validas > limite:
        avisos.append(f"Se muestran los {limite} registros más recientes de {total_validas}; acerque el mapa o "
                      "filtre más para ver el resto.")
    respuesta = envolver(db, fuente, f, cond, None, "siniestros", avisos)
    respuesta.pop("datos")
    return {"type": "FeatureCollection", "features": features,
            "metadatos": dict(respuesta, total_filtrados=total_filtrados, con_coordenada_valida=total_validas,
                              sin_coordenada_valida=sin_coordenada, devueltos=len(features),
                              truncado=total_validas > limite, limite=limite)}


def por_localidad(db: Session, fuente, f: Filtros) -> dict:
    cond = condiciones(f, fuente.id)
    conteos = _por(db, SE.localidad, cond)
    personas: dict = {}
    if _fuente_tiene_personas(db, fuente.id):
        for loc, estado, n in db.execute(select(SE.localidad, AV.estado, func.count()).join(AV, AV.siniestro_id == SE.id)
                                         .where(*cond, *condiciones_personas(f)).group_by(SE.localidad, AV.estado)):
            p = personas.setdefault(loc, {"heridas": 0, "fallecidas": 0})
            if estado == "HERIDO":
                p["heridas"] += int(n)
            elif estado == "MUERTO":
                p["fallecidas"] += int(n)
    anios = _anios(db, cond)
    filas = []
    for clave, nombre in calidad.LOCALIDADES.items():
        if f.localidad and clave not in f.localidad:
            continue
        n = conteos.get(clave, 0)
        p = personas.get(clave)
        filas.append({
            "localidad": clave, "nombre": nombre, "codigo": next(c for c, v in calidad.CODIGO_LOCALIDAD.items() if v == clave),
            "siniestros": n,
            "personas_heridas": p["heridas"] if p else (0 if personas else None),
            "personas_fallecidas": p["fallecidas"] if p else (0 if personas else None),
            "tasa_siniestros": calcular_tasa(db, n, anios, [clave], f),
        })
    filas.sort(key=lambda x: -x["siniestros"])
    sin_localidad = conteos.get(None, 0)
    avisos = [NOTA_CONTEOS]
    if sin_localidad:
        avisos.append(f"{sin_localidad} siniestros no tienen localidad reconocida y no se asignan a ninguna.")
    if personas:
        avisos.append(NOTA_PERSONAS)
    return envolver(db, fuente, f, cond, {"localidades": filas, "sin_localidad": sin_localidad},
                    "siniestros", avisos)


def por_periodo(db: Session, fuente, f: Filtros, agrupacion: str = "anio") -> dict:
    if agrupacion not in ("anio", "mes"):
        raise ErrorConsulta(400, "agrupacion_invalida", "agrupacion debe ser 'anio' o 'mes'.")
    cond = condiciones(f, fuente.id)
    columnas = [SE.anio] if agrupacion == "anio" else [SE.anio, SE.mes]
    series: dict[str, dict] = {}
    for *clave, gravedad, n in db.execute(select(*columnas, SE.gravedad, func.count()).where(*cond)
                                          .group_by(*columnas, SE.gravedad)):
        periodo = str(clave[0]) if agrupacion == "anio" else f"{clave[0]}-{clave[1]:02d}"
        fila = series.setdefault(periodo, {"periodo": periodo, "siniestros": 0, "por_gravedad": {},
                                           "personas_heridas": None, "personas_fallecidas": None})
        fila["siniestros"] += int(n)
        fila["por_gravedad"][gravedad or "Sin dato"] = int(n)
    if _fuente_tiene_personas(db, fuente.id):
        for fila in series.values():
            fila["personas_heridas"] = fila["personas_fallecidas"] = 0
        for *clave, estado, n in db.execute(select(*columnas, AV.estado, func.count()).join(AV, AV.siniestro_id == SE.id)
                                            .where(*cond, *condiciones_personas(f)).group_by(*columnas, AV.estado)):
            periodo = str(clave[0]) if agrupacion == "anio" else f"{clave[0]}-{clave[1]:02d}"
            if periodo in series and estado in ("HERIDO", "MUERTO"):
                series[periodo]["personas_heridas" if estado == "HERIDO" else "personas_fallecidas"] += int(n)
    avisos = [NOTA_PERSONAS]
    hoy = calidad.hoy_bogota()
    if str(hoy.year) in series or f"{hoy.year}-{hoy.month:02d}" in series:
        avisos.append(f"El último periodo ({hoy.year}) está en curso: sus cifras son parciales.")
    return envolver(db, fuente, f, cond, {"agrupacion": agrupacion,
                                          "serie": [series[k] for k in sorted(series)]}, "siniestros", avisos)


def por_hora_dia(db: Session, fuente, f: Filtros) -> dict:
    cond = condiciones(f, fuente.id)
    matriz = {d: [0] * 24 for d in DIAS}
    sin_hora = 0
    for dia, hora, n in db.execute(select(SE.dia_semana, SE.hora, func.count()).where(*cond)
                                   .group_by(SE.dia_semana, SE.hora)):
        if hora is None or dia not in matriz:
            sin_hora += int(n)
        else:
            matriz[dia][hora] += int(n)
    return envolver(db, fuente, f, cond, {
        "dias": list(DIAS), "horas": list(range(24)),
        "matriz": [{"dia": d, "conteos": matriz[d]} for d in DIAS], "sin_hora": sin_hora,
    }, "siniestros", [f"{sin_hora} siniestros sin hora registrada no se incluyen."] if sin_hora else [])


DIMENSIONES_ACTOR = {"condicion": AV.condicion, "sexo": AV.sexo, "rango_edad": AV.rango_edad}


def por_actor(db: Session, fuente, f: Filtros, dimension: str = "condicion") -> dict:
    columna = DIMENSIONES_ACTOR.get(dimension)
    if columna is None:
        raise ErrorConsulta(400, "dimension_invalida", f"dimension debe ser una de: {', '.join(DIMENSIONES_ACTOR)}.")
    cond = condiciones(f, fuente.id)
    if not _fuente_tiene_personas(db, fuente.id):
        return envolver(db, fuente, f, cond, {"dimension": dimension, "grupos": [], "disponible": False}, "personas",
                        ["Esta fuente no tiene personas importadas: esta dimensión no está disponible. Importe la hoja "
                         "Actor vial del anuario o sincronice ArcGIS (tabla VM_ACC_ACTOR_VIAL)."])
    grupos: dict = {}
    for valor, estado, n in db.execute(select(columna, AV.estado, func.count()).join(SE, AV.siniestro_id == SE.id)
                                       .where(*cond, *condiciones_personas(f)).group_by(columna, AV.estado)):
        g = grupos.setdefault(valor, {"valor": valor or "Sin dato", "personas": 0, "heridas": 0, "fallecidas": 0,
                                      "ilesas": 0, "sin_estado": 0})
        g["personas"] += int(n)
        g[{"HERIDO": "heridas", "MUERTO": "fallecidas", "ILESO": "ilesas"}.get(estado, "sin_estado")] += int(n)
    lista = sorted(grupos.values(), key=lambda g: -g["personas"])
    avisos = [NOTA_PERSONAS]
    if dimension == "rango_edad":
        avisos.append("Rangos de edad según los cursos de vida del archivo oficial de población.")
    return envolver(db, fuente, f, cond, {"dimension": dimension, "grupos": lista, "disponible": True}, "personas", avisos)


def por_gravedad(db: Session, fuente, f: Filtros) -> dict:
    cond = condiciones(f, fuente.id)
    datos = {"siniestros_por_gravedad": {(k or "Sin dato"): v for k, v in _por(db, SE.gravedad, cond).items()}}
    tradicional = _por(db, SE.gravedad_tradicional, cond)
    if any(k for k in tradicional):
        datos["siniestros_por_gravedad_tradicional"] = {(k or "Sin dato"): v for k, v in tradicional.items()}
    f_sin = f.model_copy(update={"gravedad": [], "todas_las_gravedades": True})
    datos["solo_danos_aparte"] = {"valor": _conteo(db, condiciones(f_sin, fuente.id) + [SE.gravedad == "Solo Daños"]),
                                  "advertencia": ADVERTENCIA_SOLO_DANOS}
    if _fuente_tiene_personas(db, fuente.id):
        datos["personas_por_estado"] = _personas_por_estado(db, f, cond)
    return envolver(db, fuente, f, cond, datos, "siniestros",
                    ["La gravedad principal es la que publica la fuente (anuarios: indicador a 30 días; ArcGIS: "
                     "campo GRAVEDAD).", NOTA_PERSONAS])


def por_clase(db: Session, fuente, f: Filtros) -> dict:
    cond = condiciones(f, fuente.id)
    conteos = _por(db, SE.clase_siniestro, cond)
    return envolver(db, fuente, f, cond, {"clases": [{"clase": k or "Sin dato", "siniestros": v}
                                                     for k, v in sorted(conteos.items(), key=lambda kv: -kv[1])]},
                    "siniestros")


def concentracion_geografica(db: Session, fuente, f: Filtros, tamano_m: int, minimo: int = 1,
                             bbox: tuple[float, float, float, float] | None = None, max_celdas: int = 20_000) -> dict:
    cond = condiciones(f, fuente.id)
    validas = cond + [SE.coordenada_valida.is_(True), SE.latitud.is_not(None), SE.longitud.is_not(None)]
    if bbox:
        oeste, sur, este, norte = bbox
        validas += [SE.longitud >= oeste, SE.longitud <= este, SE.latitud >= sur, SE.latitud <= norte]
    dlat, dlon = concentracion.pasos_grados(tamano_m)
    x = (SE.latitud - concentracion.ORIGEN_LAT) / dlat
    y = (SE.longitud - concentracion.ORIGEN_LON) / dlon
    if db.get_bind().dialect.name == "sqlite":
        fila_expr, col_expr = cast(x, Integer), cast(y, Integer)  # valores positivos: truncar = piso
    else:
        fila_expr, col_expr = cast(func.floor(x), Integer), cast(func.floor(y), Integer)
    fila_c, col_c = fila_expr.label("fila"), col_expr.label("columna")
    # Se agrupa por la etiqueta (no por la expresión) para que PostgreSQL no vea parámetros distintos.
    consulta = (select(fila_c, col_c, func.count().label("n")).where(*validas).group_by(fila_c, col_c)
                .having(func.count() >= minimo).order_by(func.count().desc()).limit(max_celdas + 1))
    filas = db.execute(consulta).all()
    truncado = len(filas) > max_celdas
    celdas = [dict(concentracion.limites_celda(fi, co, tamano_m), fila=fi, columna=co, conteo=int(n))
              for fi, co, n in filas[:max_celdas]]
    total_validas = _conteo(db, validas)
    sin_coordenada = _conteo(db, cond + [SE.coordenada_valida.is_(False)])
    avisos = [NOTA_CONTEOS, "La cuadrícula muestra dónde se concentran los registros históricos; no predice "
              "siniestros futuros ni indica rutas seguras."]
    if sin_coordenada:
        avisos.append(f"{sin_coordenada} registros filtrados sin coordenada válida no se incluyen.")
    if truncado:
        avisos.append(f"Se devuelven las {max_celdas} celdas con más registros.")
    return envolver(db, fuente, f, cond, {
        "tamano_celda_m": tamano_m, "origen": {"lat": concentracion.ORIGEN_LAT, "lon": concentracion.ORIGEN_LON},
        "celdas": celdas, "minimo_por_celda": minimo, "registros_en_celdas": sum(c["conteo"] for c in celdas),
        "registros_con_coordenada_valida": total_validas, "sin_coordenada_valida": sin_coordenada,
        "truncado": truncado,
    }, "siniestros", avisos)


_CACHE_GEO: dict = {}


def _poligonos(directorio_geo: Path) -> dict | None:
    ruta = Path(directorio_geo) / geo_localidades.NOMBRE_ARCHIVO
    if not ruta.is_file():
        return None
    marca = ruta.stat().st_mtime
    if _CACHE_GEO.get("marca") != marca or _CACHE_GEO.get("ruta") != str(ruta):
        _CACHE_GEO.update(marca=marca, ruta=str(ruta), datos=json.loads(ruta.read_text(encoding="utf-8")))
    return _CACHE_GEO["datos"]


def geojson_localidades(db: Session, fuente, f: Filtros, directorio_geo: Path) -> dict:
    base = por_localidad(db, fuente, f)
    por_clave = {fila["localidad"]: fila for fila in base["datos"]["localidades"]}
    poligonos = _poligonos(directorio_geo)
    avisos = list(base["advertencias"])
    if poligonos:
        features = []
        for feat in poligonos.get("features", []):
            clave = feat["properties"]["localidad"]
            if clave not in por_clave:
                continue
            fila = por_clave[clave]
            features.append({"type": "Feature", "geometry": feat["geometry"],
                             "properties": {**feat["properties"], "siniestros": fila["siniestros"],
                                            "personas_heridas": fila["personas_heridas"],
                                            "personas_fallecidas": fila["personas_fallecidas"],
                                            "tasa_siniestros": fila["tasa_siniestros"].get("valor")}})
        tipo = "poligonos_oficiales"
        geo = db.scalar(select(FD).where(FD.codigo == "localidades_bogota"))
        fuente_geo = ficha_fuente(geo) if geo else None
    else:
        centros = {loc: (lat, lon) for loc, lat, lon in db.execute(
            select(SE.localidad, func.avg(SE.latitud), func.avg(SE.longitud))
            .where(SE.fuente_id == fuente.id, SE.coordenada_valida.is_(True), SE.localidad.is_not(None))
            .group_by(SE.localidad))}
        features = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                     "properties": {"localidad": k, "nombre": fila["nombre"], "codigo": fila["codigo"],
                                    "siniestros": fila["siniestros"], "personas_heridas": fila["personas_heridas"],
                                    "personas_fallecidas": fila["personas_fallecidas"],
                                    "tasa_siniestros": fila["tasa_siniestros"].get("valor")}}
                    for k, fila in por_clave.items() if k in centros for lat, lon in [centros[k]]]
        tipo = "centroide_de_puntos_reales"
        fuente_geo = None
        avisos.append("No hay polígonos oficiales cargados: cada localidad se dibuja como un círculo en el promedio "
                      "de las coordenadas válidas de sus siniestros. No es un límite oficial.")
        faltan = [k for k in por_clave if k not in centros]
        if faltan:
            avisos.append("Sin coordenadas válidas para ubicar: " + ", ".join(faltan))
    return {"type": "FeatureCollection", "features": features,
            "metadatos": {**{k: v for k, v in base.items() if k != "datos"}, "advertencias": avisos,
                          "tipo_geometria": tipo, "fuente_geometria": fuente_geo,
                          "sin_localidad": base["datos"]["sin_localidad"]}}


# =============================================================================== catálogo

def listar_fuentes(db: Session) -> list[dict]:
    conteos = dict(db.execute(select(SE.fuente_id, func.count()).group_by(SE.fuente_id)).all())
    denominadores = dict(db.execute(select(DO.fuente_id, func.count()).group_by(DO.fuente_id)).all())
    ultimas = {}
    for fid, estado, fin in db.execute(
            select(models.Importacion.fuente_id, models.Importacion.estado, models.Importacion.finalizada_en)
            .where(models.Importacion.estado.in_(("completada", "fallida")))
            .order_by(models.Importacion.iniciada_en.desc())):
        ultimas.setdefault(fid, {"estado": estado, "finalizada_en": _iso(fin)})
    salida = []
    for fuente in db.scalars(select(FD).order_by(FD.prioridad, FD.codigo)):
        tipo = ("siniestros" if fuente.codigo in FUENTES_EVENTOS else
                "denominador" if fuente.codigo == CODIGO_POBLACION else "geografia")
        salida.append({**ficha_fuente(fuente), "tipo": tipo, "activa": fuente.activa,
                       "registros": conteos.get(fuente.id, 0) if tipo == "siniestros" else denominadores.get(fuente.id, 0)
                       if tipo == "denominador" else None,
                       "ultima_actualizacion": ultimas.get(fuente.id),
                       "por_defecto": fuente.codigo == FUENTE_POR_DEFECTO})
    return salida


DIMENSIONES = {
    "gravedad_tradicional": ("Gravedad tradicional", "Solo existe en el anuario 2015-2024."),
    "barrio": ("Barrio", "Solo lo publica ArcGIS (campo BARRIO)."),
    "via_nombre": ("Nombre de la vía", "Solo lo publica ArcGIS (campo MVINOMBRE)."),
    "hora": ("Hora", "Hora del siniestro."),
    "personas": ("Personas (actor vial)", "Requiere la hoja Actor vial del anuario o la tabla VM_ACC_ACTOR_VIAL de ArcGIS."),
    "vehiculos": ("Vehículos", "Requiere la hoja Vehículos del anuario o la tabla VM_ACC_VEHICULO de ArcGIS."),
    "causas": ("Causas / hipótesis", "Solo las publica ArcGIS (tabla VM_ACC_CAUSA); los anuarios no las incluyen."),
    "coordenadas": ("Coordenadas válidas", "Sin coordenadas se usa el mapa por localidad."),
}


def metadatos_campos(db: Session, fuente) -> dict:
    fid = fuente.id
    total = _conteo(db, [SE.fuente_id == fid])

    def no_nulos(columna) -> int:
        return _conteo(db, [SE.fuente_id == fid, columna.is_not(None)])

    def hijos(modelo) -> int:
        return int(db.scalar(select(func.count()).select_from(modelo).join(SE, modelo.siniestro_id == SE.id)
                             .where(SE.fuente_id == fid)) or 0)

    presentes = {
        "gravedad_tradicional": no_nulos(SE.gravedad_tradicional), "barrio": no_nulos(SE.barrio),
        "via_nombre": no_nulos(SE.via_nombre), "hora": no_nulos(SE.hora),
        "personas": hijos(AV), "vehiculos": hijos(VE), "causas": hijos(CE),
        "coordenadas": _conteo(db, [SE.fuente_id == fid, SE.coordenada_valida.is_(True)]),
    }
    dimensiones = []
    for clave, (etiqueta, nota) in DIMENSIONES.items():
        n = presentes[clave]
        dimensiones.append({"clave": clave, "etiqueta": etiqueta, "disponible": n > 0, "registros": n,
                            "nota": nota if n == 0 else None})
    valores = {
        "anios": _anios(db, [SE.fuente_id == fid]),
        "localidades": [{"clave": k, "nombre": calidad.LOCALIDADES[k]} for k in
                        sorted(k for (k,) in db.execute(select(SE.localidad).where(SE.fuente_id == fid).distinct()) if k)],
        "clases": sorted(k for (k,) in db.execute(select(SE.clase_siniestro).where(SE.fuente_id == fid).distinct()) if k),
        "gravedades": sorted(k for (k,) in db.execute(select(SE.gravedad).where(SE.fuente_id == fid).distinct()) if k),
        "actores": sorted(k for (k,) in db.execute(select(AV.condicion).join(SE, AV.siniestro_id == SE.id)
                                                   .where(SE.fuente_id == fid).distinct()) if k),
    }
    campos = [
        {"campo": "id_registro", "descripcion": "Código del siniestro en la fuente"},
        {"campo": "fecha", "descripcion": "Fecha de ocurrencia (fecha local de Bogotá)"},
        {"campo": "hora", "descripcion": "Hora de ocurrencia (0-23)"},
        {"campo": "localidad", "descripcion": "Clave canónica de la localidad (MAYÚSCULAS, sin tildes)"},
        {"campo": "clase", "descripcion": "Clase de siniestro"},
        {"campo": "gravedad", "descripcion": "Con Muertos / Con Heridos / Solo Daños"},
        {"campo": "latitud, longitud", "descripcion": "Solo cuando la coordenada es válida; nunca se imputan"},
        {"campo": "personas", "descripcion": "Conteos derivados de actor vial (heridas, fallecidas, ilesas)"},
    ]
    return {"datos": {"total_siniestros": total, "dimensiones": dimensiones, "valores_para_filtros": valores,
                      "campos": campos, "no_publicados": ["formulario (IPAT)", "edad exacta", "placa",
                                                          "fecha de nacimiento", "código de la persona"]},
            "fuente": ficha_fuente(fuente),
            "advertencias": ["Si una dimensión no está disponible en esta fuente, la interfaz la oculta y explica "
                             "qué fuente adicional haría falta."]}


def salud(db: Session) -> bool:
    try:
        db.execute(select(1))
        return True
    except Exception:  # noqa: BLE001 - solo informa el estado
        return False

