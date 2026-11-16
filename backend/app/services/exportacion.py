"""Exportación CSV de siniestros (funciones puras, sin base de datos).

Reglas:
- Solo se exportan campos públicos: nunca `formulario`, placas, fechas de nacimiento ni códigos de accidentado.
- Las personas van en columnas marcadas como "derivado de actor vial" y no se suman con siniestros.
- Las coordenadas solo se escriben si son válidas; si no, se indica el motivo (no se imputan).
- Formato "excel": separador ';' y coma decimal (Excel en español de Colombia abre el archivo en columnas).
  Formato "estandar": separador ',' y punto decimal (pandas, R, QGIS...).
- Se neutralizan los textos que empiezan por = + - @ para que una hoja de cálculo no los ejecute como fórmula.
"""
from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Iterator

BOM = "﻿"
FORMATOS = {"excel": (";", ","), "estandar": (",", ".")}
MOTIVOS = {
    "sin_coordenada": "sin coordenada",
    "fuera_de_rango": "fuera de rango",
    "fuera_de_bogota": "fuera de Bogotá",
    "sospechosa": "no coincide con la localidad",
}

# (encabezado, función que extrae el valor de la fila pública)
COLUMNAS: list[tuple[str, object]] = [
    ("fuente", lambda f: f["fuente"]),
    ("id_registro", lambda f: f["id_registro"]),
    ("fecha", lambda f: f["fecha"]),
    ("anio", lambda f: f["anio"]),
    ("mes", lambda f: f["mes"]),
    ("dia_semana", lambda f: f["dia_semana"]),
    ("hora", lambda f: hora_texto(f.get("hora"), f.get("minuto"))),
    ("localidad", lambda f: f.get("localidad_nombre") or ""),
    ("clase", lambda f: f.get("clase")),
    ("gravedad", lambda f: f.get("gravedad")),
    ("gravedad_tradicional", lambda f: f.get("gravedad_tradicional")),
    ("direccion", lambda f: f.get("direccion")),
    ("barrio", lambda f: f.get("barrio")),
    ("via", lambda f: f.get("via")),
    ("coordenada_valida", lambda f: "si" if f.get("coordenada_valida") else "no"),
    ("latitud", lambda f: f.get("latitud") if f.get("coordenada_valida") else None),
    ("longitud", lambda f: f.get("longitud") if f.get("coordenada_valida") else None),
    ("motivo_sin_coordenada", lambda f: "" if f.get("coordenada_valida")
     else MOTIVOS.get(f.get("motivo_sin_coordenada") or "", f.get("motivo_sin_coordenada"))),
    ("personas_heridas_derivado_actor_vial", lambda f: f["personas"]["heridas"]),
    ("personas_fallecidas_derivado_actor_vial", lambda f: f["personas"]["fallecidas"]),
    ("personas_ilesas_derivado_actor_vial", lambda f: f["personas"]["ilesas"]),
]
ENCABEZADOS = [c for c, _ in COLUMNAS]
PROHIBIDAS = {"formulario", "placa", "fecha_nacimiento", "codigo_accidentado"}
assert not PROHIBIDAS & set(ENCABEZADOS)


def hora_texto(hora: int | None, minuto: int | None) -> str:
    if hora is None:
        return ""
    return f"{hora:02d}:{(minuto or 0):02d}"


def celda(valor: object, decimal: str) -> str:
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "si" if valor else "no"
    if isinstance(valor, float):
        texto = f"{valor:.6f}".rstrip("0").rstrip(".")
        return texto.replace(".", decimal)
    if isinstance(valor, int):
        return str(valor)
    texto = str(valor).replace("\r", " ").replace("\n", " ")
    if texto[:1] in ("=", "+", "-", "@", "\t"):
        texto = "'" + texto  # evita la inyección de fórmulas en hojas de cálculo
    return texto


def generar_csv(filas: Iterable[dict], formato: str = "excel", bloque: int = 500) -> Iterator[str]:
    """Produce el CSV por trozos de texto (para enviarlo sin cargarlo entero en memoria)."""
    if formato not in FORMATOS:
        raise ValueError(f"Formato desconocido: {formato}")
    separador, decimal = FORMATOS[formato]
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=separador, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    escritor.writerow(ENCABEZADOS)
    pendientes = 0
    primero = True
    for fila in filas:
        escritor.writerow([celda(extraer(fila), decimal) for _, extraer in COLUMNAS])
        pendientes += 1
        if pendientes >= bloque:
            texto = salida.getvalue()
            yield (BOM + texto) if primero else texto
            primero = False
            salida.seek(0)
            salida.truncate()
            pendientes = 0
    texto = salida.getvalue()
    if texto or primero:
        yield (BOM + texto) if primero else texto


def nombre_archivo(codigo_fuente: str, hoy: str) -> str:
    seguro = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in codigo_fuente)
    return f"via-segura_{seguro}_{hoy}.csv"
