"""Sincroniza la fuente principal (ArcGIS SIMUR) con la base de datos.

Uso (desde la raíz del proyecto, con el entorno virtual activo y `alembic upgrade head` hecho):
    python scripts/sync_arcgis.py                       # incremental (ventana ARCGIS_VENTANA_DIAS)
    python scripts/sync_arcgis.py --modo completa       # todo el servicio (cientos de miles de registros)
    python scripts/sync_arcgis.py --modo completa --desde-anio 2015
    python scripts/sync_arcgis.py --modo completa --desde-anio 2025 --max-paginas 2   # prueba corta

Si el servicio no responde, la importación queda registrada como "fallida" y se conservan
los datos guardados previamente. Código de salida: 0 completada, 2 fallida.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))


def principal() -> int:
    parser = argparse.ArgumentParser(description="Sincroniza los siniestros desde ArcGIS SIMUR.")
    parser.add_argument("--modo", choices=("incremental", "completa"), default="incremental")
    parser.add_argument("--desde-anio", type=int, help="Solo en modo completa: importar desde este año")
    parser.add_argument("--ventana-dias", type=int, help="Sobrescribe ARCGIS_VENTANA_DIAS")
    parser.add_argument("--max-paginas", type=int, help="Detenerse tras N páginas (para pruebas)")
    parser.add_argument("--detalle", action="store_true", help="Imprime el resumen completo en JSON")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    from sqlalchemy import inspect

    from app.config import get_settings
    from app.database import SessionLocal, engine
    from app.services.arcgis_client import ClienteArcGIS
    from app.services.arcgis_sync import SincronizadorArcGIS
    from app.services.repositorio_sql import RepositorioSQL

    if "siniestros_evento" not in inspect(engine).get_table_names():
        print("La base de datos no tiene las tablas. Ejecuta primero:  alembic upgrade head")
        return 1

    cfg = get_settings()
    with ClienteArcGIS.desde_configuracion() as cliente, SessionLocal() as sesion:
        sincronizador = SincronizadorArcGIS(
            cliente, RepositorioSQL(sesion),
            ventana_dias=args.ventana_dias if args.ventana_dias is not None else cfg.arcgis_ventana_dias,
            lote_formularios=cfg.arcgis_lote_formularios,
            coherencia_percentil=cfg.coherencia_percentil,
            coherencia_margen=cfg.coherencia_margen_grados,
            progreso=print,
        )
        resultado = sincronizador.ejecutar(args.modo, desde_anio=args.desde_anio, max_paginas=args.max_paginas)

    print()
    print(resultado.mensaje)
    print(f"Importación n.º {resultado.importacion_id} - estado: {resultado.estado}")
    r = resultado.resumen
    if r.get("fecha_mas_reciente_en_servicio"):
        print(f"Fecha de ocurrencia más reciente publicada en el servicio: {r['fecha_mas_reciente_en_servicio']}")
    if r.get("coherencia_coordenadas"):
        print(f"Coordenadas marcadas 'sospechosa': {r['coherencia_coordenadas']['marcadas_sospechosas']}")
    ausentes = r.get("guardados_que_ya_no_aparecen_en_el_servicio")
    if ausentes and ausentes["cantidad"]:
        print(f"Registros guardados que ya no aparecen en el servicio (no se borraron): {ausentes['cantidad']}")
    for c in r.get("coincidencias_otras_fuentes") or []:
        print(f"Coinciden {c['coincidencias']} id con '{c['fuente']}' (fecha distinta: {c['fecha_distinta']}); "
              f"prevalece '{c['prevalece']}'.")
    if args.detalle:
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    return 0 if resultado.estado == "completada" else 2


if __name__ == "__main__":
    raise SystemExit(principal())
