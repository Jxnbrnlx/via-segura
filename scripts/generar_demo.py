"""Carga (o borra) datos DEMO sintéticos para probar VÍA SEGURA sin datos oficiales.

Ejemplos (desde la raíz del proyecto, con el entorno virtual activo y `alembic upgrade head` hecho):
    python scripts/generar_demo.py                      # 4.000 siniestros sintéticos (2020-2025)
    python scripts/generar_demo.py --cantidad 20000     # más registros
    python scripts/generar_demo.py --solo-csv demo_csv  # solo escribe los CSV, sin tocar la base
    python scripts/generar_demo.py --borrar             # borra la fuente DEMO y todo lo suyo
    python scripts/generar_demo.py --si-falta           # solo si todavía no está cargada (lo usa Docker)

Los datos son INVENTADOS (ver backend/app/services/demo.py). Aparecen como una fuente aparte,
«DEMO — Datos sintéticos», que nunca se suma con las fuentes oficiales.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))


def principal() -> int:
    p = argparse.ArgumentParser(description="Datos DEMO sintéticos (no oficiales).")
    p.add_argument("--cantidad", type=int, default=4000, help="Número de siniestros (100-200000). Por defecto 4000.")
    p.add_argument("--semilla", type=int, default=2026, help="Misma semilla = mismos datos.")
    p.add_argument("--solo-csv", metavar="CARPETA", help="Solo escribir los CSV en esta carpeta.")
    p.add_argument("--borrar", action="store_true", help="Borrar la fuente DEMO de la base de datos.")
    p.add_argument("--si-falta", action="store_true", help="No hacer nada si la DEMO ya está cargada (para Docker).")
    args = p.parse_args()
    if not 100 <= args.cantidad <= 200_000:
        p.error("--cantidad debe estar entre 100 y 200000")

    from app.services import demo

    if args.solo_csv:
        rutas = demo.escribir_csv(demo.generar(args.cantidad, args.semilla), Path(args.solo_csv))
        for tipo, ruta in rutas.items():
            print(f"{tipo:10s} -> {ruta}")
        print("\nPuede subirlos en Administración → Importar archivo, con el mapeo «DEMO: datos sintéticos…».")
        return 0

    from sqlalchemy import inspect

    from app.config import get_settings
    from app.database import SessionLocal, engine

    if "importaciones" not in inspect(engine).get_table_names():
        print("La base de datos no tiene las tablas. Ejecute primero:  alembic upgrade head")
        return 1

    with SessionLocal() as sesion:
        if args.borrar:
            n = demo.borrar_demo(sesion)
            print(f"Fuente DEMO borrada ({n} siniestros). Las fuentes oficiales no se tocaron." if n
                  else "No había datos DEMO.")
            return 0
        if args.si_falta and demo.hay_demo(sesion):
            print("La DEMO ya está cargada; no se vuelve a generar.")
            return 0
        print(f"Generando {args.cantidad} siniestros sintéticos (semilla {args.semilla})…")
        try:
            demo.cargar_demo(sesion, get_settings(), n=args.cantidad, semilla=args.semilla, progreso=print)
        except Exception as exc:  # noqa: BLE001 - se muestra al usuario
            print(f"\nNo se pudo cargar la DEMO: {exc}")
            return 2
    print("\nListo. En la página, abra Filtros → Fuente y elija «DEMO — Datos sintéticos».")
    print("Si no hay otras fuentes con datos, la DEMO se muestra directamente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
