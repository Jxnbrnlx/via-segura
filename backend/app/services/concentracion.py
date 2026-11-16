"""Cuadrícula de concentración geográfica (celdas de ~250 m) calculada en el servidor.

Las celdas se definen desde un origen fijo al suroeste de la caja amplia de Bogotá, así una
celda siempre es la misma sin importar los filtros. El tamaño en grados de longitud se corrige
por la latitud de referencia de Bogotá (4,65°). Solo se envía el conteo por celda: nunca los
puntos que la componen. Una celda con más registros indica concentración de REGISTROS, no riesgo.
"""
from __future__ import annotations

import math

from .calidad import CAJA_BOGOTA

METROS_POR_GRADO = 111_320.0
LATITUD_REFERENCIA = 4.65
ORIGEN_LAT = CAJA_BOGOTA.lat_min   # 3.70
ORIGEN_LON = CAJA_BOGOTA.lon_min   # -74.50
TAMANO_MIN_M, TAMANO_MAX_M, TAMANO_DEFECTO_M = 100, 1000, 250


def pasos_grados(tamano_m: float) -> tuple[float, float]:
    """(grados de latitud, grados de longitud) que miden `tamano_m` metros en Bogotá."""
    dlat = tamano_m / METROS_POR_GRADO
    dlon = tamano_m / (METROS_POR_GRADO * math.cos(math.radians(LATITUD_REFERENCIA)))
    return dlat, dlon


def celda_de(latitud: float, longitud: float, tamano_m: float) -> tuple[int, int]:
    dlat, dlon = pasos_grados(tamano_m)
    return math.floor((latitud - ORIGEN_LAT) / dlat), math.floor((longitud - ORIGEN_LON) / dlon)


def limites_celda(fila: int, columna: int, tamano_m: float) -> dict:
    dlat, dlon = pasos_grados(tamano_m)
    lat_min = ORIGEN_LAT + fila * dlat
    lon_min = ORIGEN_LON + columna * dlon
    return {
        "lat_min": round(lat_min, 6), "lat_max": round(lat_min + dlat, 6),
        "lon_min": round(lon_min, 6), "lon_max": round(lon_min + dlon, 6),
        "lat_centro": round(lat_min + dlat / 2, 6), "lon_centro": round(lon_min + dlon / 2, 6),
    }
