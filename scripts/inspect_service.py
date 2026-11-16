"""Inspección del servicio ArcGIS SIMUR ANTES de procesar datos.

Uso (desde la raíz del proyecto, con el entorno virtual activo):
    python scripts/inspect_service.py
    python scripts/inspect_service.py --json docs/inspeccion_arcgis.json

Imprime: capas y tablas, campos y tipos, conteos, relaciones, fecha de ocurrencia mínima y
máxima, conteo por año, valores distintos de las categorías, nulos por campo, duplicados,
coordenadas fuera de Bogotá, coincidencia geometría vs LATITUD/LONGITUD, formato de hora,
zona horaria de las fechas y una prueba de la unión por FORMULARIO.

Nunca solicita PLACA, FECHA_NACIMIENTO ni CODIGO_ACCIDENTADO (el cliente lo impide).
Cada verificación es independiente: si una falla, se informa y se sigue con las demás.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from app.services import calidad  # noqa: E402
from app.services.arcgis_client import (  # noqa: E402
    CAMPOS_ACCIDENTE, CAMPOS_ACTOR_VIAL, CAPA_ACCIDENTE, CAMPOS_PROHIBIDOS, TABLA_ACTOR_VIAL, TABLA_CAUSA,
    TABLA_VEHICULO, ClienteArcGIS, ErrorArcGIS, sql_lista_texto,
)

_HORA = re.compile(r"^\d{2}:\d{2}:\d{2}$")
CAJA = calidad.CAJA_BOGOTA


class Informe:
    def __init__(self) -> None:
        self.datos: dict = {"generado": datetime.now().isoformat(timespec="seconds")}

    def seccion(self, titulo: str) -> None:
        print(f"\n{'=' * 78}\n{titulo}\n{'=' * 78}")

    def verificar(self, clave: str, descripcion: str, funcion: Callable[[], object]) -> object:
        try:
            valor = funcion()
        except (ErrorArcGIS, ValueError, KeyError, TypeError) as exc:
            mensaje = getattr(exc, "mensaje", str(exc))
            print(f"  [NO DISPONIBLE] {descripcion}: {mensaje}")
            self.datos[clave] = {"error": mensaje}
            return None
        self.datos[clave] = valor
        texto = json.dumps(valor, ensure_ascii=False, default=str)
        print(f"  {descripcion}: {texto if len(texto) < 1500 else texto[:1500] + ' ...'}")
        return valor


def _fecha(ms: object) -> str | None:
    f = calidad.fecha_desde_epoch_ms(ms)
    return f.isoformat() if f else None


def _ordenar(conteo: dict) -> dict:
    return dict(sorted(((str(k), v) for k, v in conteo.items()), key=lambda kv: -kv[1]))


def principal() -> int:
    parser = argparse.ArgumentParser(description="Inspecciona el servicio ArcGIS de siniestralidad (SIMUR).")
    parser.add_argument("--url", help="URL base del FeatureServer (por defecto la de .env)")
    parser.add_argument("--json", help="Ruta donde guardar el informe en JSON")
    parser.add_argument("--muestras", type=int, default=3, help="Páginas de muestra para geometría/hora (def. 3)")
    args = parser.parse_args()

    # Pocos reintentos: algunas verificaciones son consultas pesadas y es mejor informarlas como
    # "NO DISPONIBLE" que dejar la inspección esperando varios minutos.
    cliente = (ClienteArcGIS(args.url, reintentos=1) if args.url
               else ClienteArcGIS.desde_configuracion(reintentos=1))
    inf = Informe()
    with cliente:
        inf.seccion("1. Servicio")
        def capas_y_tablas():
            m = cliente.metadatos_servicio()
            return {"capas": [(c["id"], c["name"]) for c in m.get("layers", [])],
                    "tablas": [(t["id"], t["name"]) for t in m.get("tables", [])],
                    "maxRecordCount": m.get("maxRecordCount"), "formatos": m.get("supportedQueryFormats")}
        servicio = inf.verificar("servicio", "Capas y tablas", capas_y_tablas)
        ids = [c[0] for c in (servicio or {}).get("capas", [])] + [t[0] for t in (servicio or {}).get("tablas", [])]
        ids = ids or list(range(7))

        inf.seccion("2. Campos, conteos y relaciones por capa/tabla")
        for capa in ids:
            def ficha(capa=capa):
                m = cliente.metadatos(capa)
                return {
                    "nombre": m.get("name"),
                    "tipo": m.get("type"),
                    "maxRecordCount": m.get("maxRecordCount"),
                    "formatos": m.get("supportedQueryFormats"),
                    "referencia_tiempo_fechas": m.get("dateFieldsTimeReference"),
                    "campos": {c["name"]: c.get("type", "").replace("esriFieldType", "") for c in m.get("fields", [])},
                    "campos_personales_presentes_no_se_importan": sorted(
                        {c["name"] for c in m.get("fields", [])} & CAMPOS_PROHIBIDOS),
                    "relaciones": [(r.get("relatedTableId"), r.get("keyField"), r.get("cardinality"))
                                   for r in m.get("relationships", [])],
                    "registros": cliente.contar(capa),
                }
            inf.verificar(f"capa_{capa}", f"Capa/tabla {capa}", ficha)

        inf.seccion("3. Capa 2 ACCIDENTE: cobertura temporal")
        inf.verificar("fecha_minima", "Fecha de ocurrencia mínima",
                      lambda: _fecha(cliente.valor_extremo(CAPA_ACCIDENTE, "FECHA_OCURRENCIA_ACC", maximo=False)))
        inf.verificar("fecha_maxima", "Fecha de ocurrencia MÁS RECIENTE",
                      lambda: _fecha(cliente.valor_extremo(CAPA_ACCIDENTE, "FECHA_OCURRENCIA_ACC", maximo=True)))
        hoy = calidad.hoy_bogota().isoformat()
        inf.verificar("fechas_futuras", f"Registros con fecha posterior a hoy ({hoy})",
                      lambda: cliente.contar(CAPA_ACCIDENTE, f"FECHA_OCURRENCIA_ACC > DATE '{hoy}'"))
        inf.verificar("por_anio", "Siniestros por año (ANO_OCURRENCIA_ACC)",
                      lambda: dict(sorted((str(int(k)) if isinstance(k, float) else str(k), v) for k, v in
                                          cliente.conteo_por_valor(CAPA_ACCIDENTE, "ANO_OCURRENCIA_ACC").items())))

        inf.seccion("4. Capa 2 ACCIDENTE: categorías")
        for campo in ("GRAVEDAD", "CLASE_ACC", "LOCALIDAD", "MUNICIPIO"):
            inf.verificar(f"valores_{campo}", f"Valores de {campo}",
                          lambda campo=campo: _ordenar(cliente.conteo_por_valor(CAPA_ACCIDENTE, campo)))

        inf.seccion("5. Capa 2 ACCIDENTE: nulos, duplicados y coordenadas")
        inf.verificar("nulos", "Nulos por campo", lambda: {
            c: cliente.contar(CAPA_ACCIDENTE, f"{c} IS NULL") for c in CAMPOS_ACCIDENTE if c != "OBJECTID"})
        for campo in ("CODIGO_ACCIDENTE", "FORMULARIO"):
            def duplicados(campo=campo):
                try:
                    filas = cliente.estadisticas(
                        CAPA_ACCIDENTE,
                        [{"statisticType": "count", "onStatisticField": "OBJECTID", "outStatisticFieldName": "n"}],
                        agrupar_por=[campo], having="COUNT(OBJECTID) > 1")
                    return {"metodo": "agrupación con HAVING", "valores_repetidos": len(filas),
                            "ejemplos": filas[:10]}
                except ErrorArcGIS:
                    total = cliente.contar(CAPA_ACCIDENTE)
                    cuerpo = cliente._consultar(CAPA_ACCIDENTE, {
                        "where": "1=1", "returnDistinctValues": "true", "returnCountOnly": "true",
                        "outFields": campo})
                    return {"metodo": "conteo de distintos (menos fiable)", "total": total,
                            "distintos": cuerpo.get("count"), "diferencia": total - int(cuerpo.get("count", 0))}
            inf.verificar(f"duplicados_{campo}", f"Duplicados de {campo}", duplicados)
        inf.verificar("fuera_de_bogota", f"Coordenadas fuera de la caja amplia {CAJA}", lambda: cliente.contar(
            CAPA_ACCIDENTE, f"LATITUD < {CAJA.lat_min} OR LATITUD > {CAJA.lat_max} OR "
                            f"LONGITUD < {CAJA.lon_min} OR LONGITUD > {CAJA.lon_max}"))
        inf.verificar("coordenadas_cero", "Coordenadas en 0",
                      lambda: cliente.contar(CAPA_ACCIDENTE, "LATITUD = 0 OR LONGITUD = 0"))

        inf.seccion("6. Muestras: geometría vs LATITUD/LONGITUD, hora y zona horaria")
        def muestras():
            total = cliente.contar(CAPA_ACCIDENTE)
            desplazamientos = sorted({0, max(0, total // 2), max(0, total - cliente.pagina)})[:args.muestras]
            dif_max, dif_grandes, revisados = 0.0, 0, 0
            horas_raras, no_medianoche, dia_distinto = Counter(), 0, 0
            for d in desplazamientos:
                registros, _ = cliente.consultar(CAPA_ACCIDENTE, "1=1", CAMPOS_ACCIDENTE, desplazamiento=d,
                                                 geometria=True)
                for r in registros:
                    revisados += 1
                    g = r.get("_geometria") or {}
                    if g.get("x") is not None and r.get("LONGITUD") is not None:
                        dif = max(abs(g["x"] - r["LONGITUD"]), abs(g["y"] - r["LATITUD"]))
                        dif_max = max(dif_max, dif)
                        dif_grandes += dif > 1e-5  # ~1 m
                    hora = r.get("HORA_OCURRENCIA_ACC")
                    if hora is not None and not _HORA.match(str(hora)):
                        horas_raras[str(hora)] += 1
                    ms = r.get("FECHA_OCURRENCIA_ACC")
                    if ms is not None and int(ms) % 86_400_000 != 0:
                        no_medianoche += 1
                    f = calidad.fecha_desde_epoch_ms(ms)
                    if f and calidad.clave(r.get("DIA_OCURRENCIA_ACC")) not in (None, calidad.clave(calidad.dia_semana(f))):
                        dia_distinto += 1
            return {"registros_revisados": revisados, "geometria_vs_latlon_dif_max_grados": dif_max,
                    "geometria_vs_latlon_dif_mayor_1m": dif_grandes,
                    "horas_con_formato_distinto_HH:MM:SS": dict(horas_raras.most_common(10)),
                    "fechas_que_no_son_medianoche_utc": no_medianoche,
                    "dia_semana_fuente_distinto_al_calculado": dia_distinto}
        inf.verificar("muestras", "Resultado de las muestras", muestras)

        inf.seccion("7. Tabla 3 VM_ACC_ACTOR_VIAL (sin datos personales)")
        for campo in ("ESTADO", "CONDICION", "CONDICION_A", "GENERO", "MUERTE_POSTERIOR"):
            inf.verificar(f"actor_{campo}", f"Valores de {campo}",
                          lambda campo=campo: _ordenar(cliente.conteo_por_valor(TABLA_ACTOR_VIAL, campo)))
        inf.verificar("actor_nulos", "Nulos", lambda: {
            c: cliente.contar(TABLA_ACTOR_VIAL, f"{c} IS NULL")
            for c in ("FORMULARIO", "CODIGO_VICTIMA", "CODIGO_VEHICULO", "ESTADO", "EDAD")})
        inf.verificar("actor_edad_atipica", "Edad fuera de 0-110 (se guardará como NULL)",
                      lambda: cliente.contar(TABLA_ACTOR_VIAL, "EDAD < 0 OR EDAD > 110"))

        inf.seccion("8. Tablas 5 VM_ACC_VEHICULO y 4 VM_ACC_CAUSA")
        for campo in ("CLASE", "SERVICIO", "MODALIDAD"):
            inf.verificar(f"vehiculo_{campo}", f"Valores de {campo}",
                          lambda campo=campo: _ordenar(cliente.conteo_por_valor(TABLA_VEHICULO, campo)))
        inf.verificar("vehiculo_sin_codigo", "Vehículos sin CODIGO_VEHICULO",
                      lambda: cliente.contar(TABLA_VEHICULO, "CODIGO_VEHICULO IS NULL"))
        inf.verificar("causa_tipo", "Valores de TIPO en causas",
                      lambda: _ordenar(cliente.conteo_por_valor(TABLA_CAUSA, "TIPO")))

        inf.seccion("9. Prueba de la unión por FORMULARIO (50 siniestros recientes)")
        def union():
            registros, _ = cliente.consultar(CAPA_ACCIDENTE, "1=1", ["FORMULARIO", "CODIGO_ACCIDENTE"],
                                             cantidad=50, orden="FECHA_OCURRENCIA_ACC DESC")
            por_formulario = {r["FORMULARIO"]: int(r["CODIGO_ACCIDENTE"]) for r in registros if r.get("FORMULARIO")}
            filas = cliente.consultar_todo(TABLA_ACTOR_VIAL, f"FORMULARIO IN {sql_lista_texto(list(por_formulario))}",
                                           CAMPOS_ACTOR_VIAL)
            con_actores = {f["FORMULARIO"] for f in filas}
            codigo_coincide = sum(1 for f in filas if str(f.get("CODIGO", "")).split("-")[0]
                                  == str(por_formulario.get(f["FORMULARIO"])))
            return {"siniestros": len(por_formulario), "con_personas": len(con_actores & set(por_formulario)),
                    "filas_personas": len(filas), "CODIGO_prefijo_igual_a_CODIGO_ACCIDENTE": codigo_coincide}
        inf.verificar("union_formulario", "Resultado", union)
        inf.datos["peticiones_http"] = cliente.peticiones

    if args.json:
        destino = Path(args.json)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(inf.datos, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"\nInforme guardado en {destino}")
    print("\nPega esta salida (o el JSON) en la conversación para ajustar el importador si hace falta.")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
