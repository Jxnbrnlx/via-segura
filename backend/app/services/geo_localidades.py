"""Polígonos oficiales de localidades (GeoJSON) para el mapa temático.

Valida antes de aceptar:
- Que sea un FeatureCollection de Polygon/MultiPolygon en grados (EPSG:4326/CRS84). Coordenadas
  proyectadas (p. ej. MAGNA-SIRGAS Bogotá en metros) se rechazan con una explicación.
- Que exista una propiedad que identifique la localidad en TODOS los polígonos (nombre o código
  1-20). Se detecta sola; no hace falta configurar el nombre del atributo.
- Antes de leer el archivo completo se revisa el primer polígono: así un archivo equivocado (por
  ejemplo, el de manzanas "MANZ") se rechaza en segundos y sin cargar 100 MB en memoria.
Después: agrupa por localidad (MultiPolygon), simplifica (Douglas-Peucker) y redondea a 6 decimales.
No se crean ni se mueven límites: solo se reduce el detalle por debajo de la tolerancia indicada.
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from . import calidad

NOMBRE_ARCHIVO = "localidades.geojson"
_CRS_GRADOS = ("CRS84", "4326")
_LON, _LAT = (-75.5, -73.0), (3.0, 5.5)  # Bogotá D.C. holgado, en grados


class ErrorGeo(ValueError):
    pass


@dataclass
class ResultadoGeo:
    coleccion: dict
    propiedad_localidad: str
    localidades: list[str]
    faltantes: list[str]
    poligonos_originales: int
    vertices_antes: int
    vertices_despues: int
    advertencias: list[str] = field(default_factory=list)

    def resumen(self) -> dict:
        return {
            "propiedad_localidad": self.propiedad_localidad,
            "localidades_encontradas": self.localidades,
            "localidades_faltantes": self.faltantes,
            "poligonos_originales": self.poligonos_originales,
            "vertices_antes": self.vertices_antes,
            "vertices_despues": self.vertices_despues,
            "advertencias": self.advertencias,
        }


def localidad_desde_valor(valor: object) -> str | None:
    """Nombre ('Usaquén', 'LA CANDELARIA') o código 1-20 -> clave canónica; None si no corresponde."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)) or (isinstance(valor, str) and re.fullmatch(r"\s*0*\d{1,2}(\.0+)?\s*", valor)):
        codigo = calidad.convertir_entero(valor)
        return calidad.CODIGO_LOCALIDAD.get(codigo) if codigo is not None else None
    try:
        return calidad.normalizar_localidad(valor)
    except calidad.ValorNoReconocido:
        return None


def propiedades_primer_poligono(ruta: Path, bytes_a_leer: int = 262_144) -> dict:
    """Lee solo el inicio del archivo y devuelve las propiedades del primer Feature."""
    with Path(ruta).open("rb") as f:
        texto = f.read(bytes_a_leer).decode("utf-8-sig", errors="ignore")
    inicio = re.search(r'"features"\s*:\s*\[', texto)  # evita confundir con "crs": {"properties": ...}
    m = re.compile(r'"properties"\s*:\s*').search(texto, inicio.end()) if inicio else None
    if not m:
        raise ErrorGeo("No se encontraron propiedades en el primer polígono del GeoJSON.")
    try:
        propiedades, _ = json.JSONDecoder().raw_decode(texto, m.end())
    except json.JSONDecodeError as exc:
        raise ErrorGeo("No se pudieron leer las propiedades del primer polígono.") from exc
    return propiedades if isinstance(propiedades, dict) else {}


def precomprobar(ruta: Path) -> None:
    propiedades = propiedades_primer_poligono(ruta)
    if not any(localidad_desde_valor(v) for v in propiedades.values()):
        claves = ", ".join(f"{k}={v!r}" for k, v in list(propiedades.items())[:8]) or "ninguna"
        raise ErrorGeo(
            "Ninguna propiedad del primer polígono identifica una localidad de Bogotá (se esperaba un nombre "
            f"como 'Usaquén' o un código 1-20). Propiedades encontradas: {claves}. Si el archivo es de "
            "manzanas, barrios o UPZ, descargue el conjunto 'Localidad. Bogotá D.C.' de Datos Abiertos Bogotá.")


# --------------------------------------------------------------------------- geometría

def _simplificar_linea(puntos: list[list[float]], tolerancia: float) -> list[list[float]]:
    """Douglas-Peucker iterativo (sin recursión)."""
    if tolerancia <= 0 or len(puntos) < 3:
        return puntos
    conservar = [False] * len(puntos)
    conservar[0] = conservar[-1] = True
    pila = [(0, len(puntos) - 1)]
    while pila:
        inicio, fin = pila.pop()
        (x1, y1), (x2, y2) = puntos[inicio][:2], puntos[fin][:2]
        dx, dy = x2 - x1, y2 - y1
        norma = (dx * dx + dy * dy) ** 0.5
        mayor, indice = -1.0, -1
        for i in range(inicio + 1, fin):
            px, py = puntos[i][:2]
            d = (abs(dy * px - dx * py + x2 * y1 - y2 * x1) / norma if norma
                 else ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5)
            if d > mayor:
                mayor, indice = d, i
        if mayor > tolerancia:
            conservar[indice] = True
            pila.extend([(inicio, indice), (indice, fin)])
    return [p for p, c in zip(puntos, conservar) if c]


def _simplificar_anillo(anillo: list[list[float]], tolerancia: float) -> list[list[float]]:
    if len(anillo) < 4:
        raise ErrorGeo("Hay un anillo de polígono con menos de 4 puntos.")
    # En un anillo cerrado los extremos coinciden: se parte en dos mitades para que DP funcione.
    medio = len(anillo) // 2
    simplificado = _simplificar_linea(anillo[: medio + 1], tolerancia)[:-1] + _simplificar_linea(anillo[medio:], tolerancia)
    if len(simplificado) < 4:
        simplificado = anillo  # demasiado pequeño para simplificar: se conserva igual
    salida = [[round(x, 6), round(y, 6)] for x, y, *_ in simplificado]
    if salida[0] != salida[-1]:
        salida.append(list(salida[0]))
    return salida


def _poligonos(geometria: dict) -> list[list[list[list[float]]]]:
    tipo = (geometria or {}).get("type")
    coordenadas = (geometria or {}).get("coordinates")
    if tipo == "Polygon":
        return [coordenadas]
    if tipo == "MultiPolygon":
        return list(coordenadas)
    raise ErrorGeo(f"Geometría '{tipo}' no admitida: se esperaban polígonos.")


def _verificar_grados(poligonos) -> None:
    for poligono in poligonos:
        for anillo in poligono:
            for x, y, *_ in anillo[:: max(1, len(anillo) // 20)]:
                if not (_LON[0] <= x <= _LON[1] and _LAT[0] <= y <= _LAT[1]):
                    raise ErrorGeo(
                        f"Coordenada ({x}, {y}) fuera de Bogotá en grados. El archivo parece estar en un sistema "
                        "proyectado (metros) o con latitud/longitud invertidas: expórtelo en EPSG:4326 (WGS84).")


# --------------------------------------------------------------------------- carga

def cargar_y_validar(ruta: Path, tolerancia: float = 0.00005) -> ResultadoGeo:
    precomprobar(ruta)
    try:
        datos = json.loads(Path(ruta).read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ErrorGeo(f"El GeoJSON no es un JSON válido: {exc}") from exc
    if not isinstance(datos, dict) or datos.get("type") != "FeatureCollection":
        raise ErrorGeo("Se esperaba un GeoJSON de tipo FeatureCollection.")
    crs = json.dumps(datos.get("crs") or {})
    if datos.get("crs") and not any(c in crs for c in _CRS_GRADOS):
        raise ErrorGeo(f"Sistema de coordenadas no admitido ({crs}). Exporte en EPSG:4326 (WGS84).")
    features = datos.get("features") or []
    if not features:
        raise ErrorGeo("El GeoJSON no contiene polígonos.")

    # Propiedad que identifica la localidad en TODOS los polígonos (se prefieren nombres a códigos).
    candidatas = set.intersection(*(set((f.get("properties") or {}).keys()) for f in features))
    elegida = None
    for clave in sorted(candidatas, key=lambda k: (not re.search(r"nom", k, re.I), k)):
        if all(localidad_desde_valor((f.get("properties") or {}).get(clave)) for f in features):
            elegida = clave
            break
    if elegida is None:
        raise ErrorGeo("Ninguna propiedad identifica la localidad en todos los polígonos. Propiedades comunes: "
                       + (", ".join(sorted(candidatas)) or "ninguna"))

    agrupados: dict[str, list] = defaultdict(list)
    vertices_antes = vertices_despues = 0
    for f in features:
        poligonos = _poligonos(f.get("geometry"))
        _verificar_grados(poligonos)
        localidad = localidad_desde_valor(f["properties"][elegida])
        for poligono in poligonos:
            vertices_antes += sum(len(a) for a in poligono)
            nuevo = [_simplificar_anillo(a, tolerancia) for a in poligono]
            vertices_despues += sum(len(a) for a in nuevo)
            agrupados[localidad].append(nuevo)

    advertencias = []
    repetidas = [k for k, v in agrupados.items() if len(v) > 1]
    if repetidas:
        advertencias.append("Localidades con varios polígonos (se unieron en un MultiPolygon): " + ", ".join(sorted(repetidas)))
    faltantes = [k for k in calidad.LOCALIDADES if k not in agrupados]
    if faltantes:
        advertencias.append("Localidades sin polígono (no aparecerán en el mapa temático): " + ", ".join(faltantes))

    coleccion = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature",
             "properties": {"localidad": k, "nombre": calidad.LOCALIDADES[k],
                            "codigo": next(c for c, v in calidad.CODIGO_LOCALIDAD.items() if v == k)},
             "geometry": {"type": "MultiPolygon", "coordinates": agrupados[k]}}
            for k in calidad.LOCALIDADES if k in agrupados
        ],
    }
    return ResultadoGeo(coleccion, elegida, [k for k in calidad.LOCALIDADES if k in agrupados], faltantes,
                        len(features), vertices_antes, vertices_despues, advertencias)


def guardar(coleccion: dict, directorio: Path) -> Path:
    """Escritura atómica: primero un temporal y luego reemplazo."""
    directorio = Path(directorio)
    directorio.mkdir(parents=True, exist_ok=True)
    destino = directorio / NOMBRE_ARCHIVO
    temporal = directorio / (NOMBRE_ARCHIVO + ".tmp")
    temporal.write_text(json.dumps(coleccion, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temporal, destino)
    return destino


# --------------------------------------------------------------------------- consultas espaciales

def punto_en_anillo(x: float, y: float, anillo: list[list[float]]) -> bool:
    dentro = False
    j = len(anillo) - 1
    for i in range(len(anillo)):
        xi, yi = anillo[i][0], anillo[i][1]
        xj, yj = anillo[j][0], anillo[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-300) + xi:
            dentro = not dentro
        j = i
    return dentro


def punto_en_multipoligono(x: float, y: float, multipoligono: list) -> bool:
    for poligono in multipoligono:
        if punto_en_anillo(x, y, poligono[0]) and not any(punto_en_anillo(x, y, hueco) for hueco in poligono[1:]):
            return True
    return False


def localidad_de_punto(longitud: float, latitud: float, coleccion: dict) -> str | None:
    for f in coleccion.get("features", []):
        if punto_en_multipoligono(longitud, latitud, f["geometry"]["coordinates"]):
            return f["properties"]["localidad"]
    return None


def cargar_guardado(directorio: Path) -> dict | None:
    ruta = Path(directorio) / NOMBRE_ARCHIVO
    if not ruta.is_file():
        return None
    return json.loads(ruta.read_text(encoding="utf-8"))
