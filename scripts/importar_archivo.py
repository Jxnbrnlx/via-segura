"""Importa un archivo oficial desde la consola (lo mismo que Administración → Importar archivo en la página).

Ejemplos (desde la raíz del proyecto, con el entorno virtual activo y `alembic upgrade head` hecho):
    python scripts/importar_archivo.py --hojas datos/Base_Anuario_2025.xlsx
    python scripts/importar_archivo.py datos/anuario2025.csv --tipo siniestros --mapeo anuario_sdm_2025
    python scripts/importar_archivo.py datos/anuario2025.csv --tipo siniestros --mapeo anuario_sdm_2025 --confirmar
    python scripts/importar_archivo.py datos/Anuario_2015_2024.xlsx --tipo actores --mapeo anuario_sdm_2015_2024 \
        --columna id_registro=Codigo_Accidente --confirmar
    python scripts/importar_archivo.py datos/poblacion.csv --tipo poblacion --mapeo poblacion_osb_localidad --confirmar
    python scripts/importar_archivo.py datos/localidades.geojson --tipo localidades --confirmar
    python scripts/importar_archivo.py --confirmar-id 7          # confirma una previsualización anterior
    python scripts/importar_archivo.py --cancelar-id 7

Sin --confirmar solo PREVISUALIZA (no escribe datos). Orden recomendado para un anuario:
siniestros -> actores -> vehiculos (personas y vehículos se enlazan con los siniestros ya importados).
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from datetime import date, datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))


def _fecha(texto: str) -> date:
    return date.fromisoformat(texto)


def _imprimir_previsualizacion(pv) -> None:
    print(f"\nPrevisualización n.º {pv.importacion_id}  ({pv.tipo})  archivo: {pv.archivo}")
    if pv.hojas:
        print(f"Hojas del libro: {', '.join(pv.hojas)}   -> hoja elegida: {pv.hoja}")
    if pv.filas_estimadas is not None:
        print(f"Filas (aprox.): {pv.filas_estimadas}")
    if pv.columnas:
        print("\nColumnas (tipo inferido):")
        for c in pv.columnas:
            print(f"  - {c['nombre']}: {c['tipo_inferido']}")
    print("\nMapeo campo lógico -> columna original:")
    for campo, columna in pv.mapeo.items():
        print(f"  {campo:22s} <- {columna}")
    if pv.columnas_atributos:
        print("Columnas guardadas como atributos: " + ", ".join(pv.columnas_atributos))
    print("\nPrimeras filas:")
    for fila in pv.filas_muestra[:5]:
        print("  " + json.dumps(fila, ensure_ascii=False, default=str)[:300])
    v = pv.validacion
    print(f"\nValidación de muestra: {v.get('revisadas')} revisadas, {v.get('validas')} válidas, "
          f"{v.get('rechazadas')} rechazadas.")
    if v.get("motivos"):
        print("  Banderas: " + json.dumps(v["motivos"], ensure_ascii=False))
    for e in v.get("ejemplos_error") or []:
        print("  - " + e)
    for a in pv.advertencias:
        print("ADVERTENCIA: " + a)
    print("\nSe puede confirmar." if pv.puede_confirmar else "\nNO se puede confirmar todavía (revise lo anterior).")


def principal() -> int:
    p = argparse.ArgumentParser(description="Importa anuarios, población o polígonos de localidades.")
    p.add_argument("ruta", nargs="?", help="Archivo .csv, .xlsx o .geojson")
    p.add_argument("--tipo", choices=("siniestros", "actores", "vehiculos", "poblacion", "localidades"))
    p.add_argument("--mapeo", help="Código del mapeo (archivo en backend/app/data/mapeos/)")
    p.add_argument("--hoja", help="Hoja del libro de Excel (si no, se elige por el mapeo)")
    p.add_argument("--columna", action="append", default=[], metavar="CAMPO=COLUMNA",
                   help="Sobrescribe el mapeo de un campo (repetible). CAMPO= vacío lo desactiva.")
    p.add_argument("--confirmar", action="store_true", help="Importar después de previsualizar")
    p.add_argument("--confirmar-id", type=int, help="Confirmar una previsualización existente")
    p.add_argument("--cancelar-id", type=int, help="Cancelar una previsualización existente")
    p.add_argument("--hojas", metavar="RUTA_XLSX", help="Solo listar las hojas de un libro")
    p.add_argument("--url", help="Enlace oficial de la fuente (se guarda en su ficha)")
    p.add_argument("--fecha-publicacion", type=_fecha, help="AAAA-MM-DD")
    p.add_argument("--fecha-descarga", type=_fecha, help="AAAA-MM-DD en que se descargó el archivo oficial")
    args = p.parse_args()

    from app.services.lectores import abrir_tabla

    if args.hojas:
        lector = abrir_tabla(Path(args.hojas))
        print("Hojas: " + (", ".join(lector.hojas) or "(CSV: una sola tabla)"))
        lector.cerrar()
        return 0

    from sqlalchemy import inspect

    from app.config import get_settings
    from app.database import SessionLocal, engine
    from app.services.archivos import ErrorArchivo, recibir_archivo
    from app.services.geo_localidades import ErrorGeo
    from app.services.importador_excel import ErrorImportacion, ImportadorArchivos
    from app.services.mapeos import ErrorMapeo
    from app.services.repositorio_sql import RepositorioSQL

    if "importaciones" not in inspect(engine).get_table_names():
        print("La base de datos no tiene las tablas. Ejecuta primero:  alembic upgrade head")
        return 1
    cfg = get_settings()

    sobrescribir = {}
    for item in args.columna:
        if "=" not in item:
            p.error(f"--columna debe tener la forma CAMPO=COLUMNA (recibido: {item})")
        campo, columna = item.split("=", 1)
        sobrescribir[campo.strip()] = columna.strip()

    # Solo se registra lo que el administrador indica: no se inventa la fecha de descarga.
    metadatos = {"url": args.url, "fecha_publicacion": args.fecha_publicacion,
                 "fecha_descarga": datetime.combine(args.fecha_descarga, datetime.min.time(), tzinfo=timezone.utc)
                 if args.fecha_descarga else None}

    with SessionLocal() as sesion:
        importador = ImportadorArchivos(
            RepositorioSQL(sesion), cfg.carga_directorio, cfg.geo_directorio, bloque=cfg.importar_bloque,
            tolerancia_geo=cfg.geo_tolerancia_grados, coherencia_percentil=cfg.coherencia_percentil,
            coherencia_margen=cfg.coherencia_margen_grados, conservar_archivo=cfg.conservar_archivo_importado,
            progreso=print)
        try:
            if args.cancelar_id:
                importador.cancelar(args.cancelar_id)
                print(f"Importación n.º {args.cancelar_id} cancelada.")
                return 0
            importacion_id = args.confirmar_id
            if importacion_id is None:
                if not args.ruta or not args.tipo:
                    p.error("Indique la ruta del archivo y --tipo (o use --confirmar-id).")
                ruta = Path(args.ruta)
                if not ruta.is_file():
                    print(f"No existe el archivo {ruta}")
                    return 1
                mime = mimetypes.guess_type(ruta.name)[0] or "application/octet-stream"
                with ruta.open("rb") as flujo:
                    recibido = recibir_archivo(flujo, ruta.name, mime, cfg.carga_directorio,
                                               max_bytes=cfg.carga_max_mb * 1024 * 1024,
                                               max_descomprimido=cfg.carga_max_descomprimido_mb * 1024 * 1024)
                pv = importador.previsualizar(recibido, tipo=args.tipo, mapeo_codigo=args.mapeo, hoja=args.hoja,
                                              sobrescribir=sobrescribir or None)
                _imprimir_previsualizacion(pv)
                if not args.confirmar:
                    print(f"\nPara importar:  python scripts/importar_archivo.py --confirmar-id {pv.importacion_id}")
                    return 0
                if not pv.puede_confirmar:
                    return 2
                importacion_id = pv.importacion_id
            resultado = importador.confirmar(importacion_id, metadatos_fuente=metadatos)
        except (ErrorArchivo, ErrorImportacion, ErrorMapeo, ErrorGeo) as exc:
            print(f"\nNo se pudo importar: {exc}")
            return 2

    print("\n" + resultado.mensaje)
    print(json.dumps(resultado.resumen, ensure_ascii=False, indent=2, default=str)[:6000])
    return 0 if resultado.estado == "completada" else 2


if __name__ == "__main__":
    raise SystemExit(principal())
