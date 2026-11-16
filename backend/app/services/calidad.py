"""Normalizadores y validaciones de calidad de datos.

Este módulo es Python puro (sin base de datos ni red) para poder probarlo de forma aislada y
reutilizarlo en la sincronización ArcGIS (Parte 2) y en el importador de anuarios (Parte 3).

Reglas que protege:
- Nunca se imputan coordenadas: si faltan o no son confiables se marca el motivo.
- Valores de categoría no reconocidos NO se convierten en otra categoría en silencio.
- Las edades atípicas (fuera de 0-110) se vuelven NULL.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

# --------------------------------------------------------------------------------------
# Texto
# --------------------------------------------------------------------------------------

_ESPACIOS = re.compile(r"\s+")
# En el servicio ArcGIS la Ñ llega dañada como "¿" en algunos valores (p. ej. "ACOMPA¿E").
_ENIE_DANADA = re.compile(r"(?<=[A-Za-z])[¿�](?=[A-Za-z])")


class ValorNoReconocido(ValueError):
    """Un valor de categoría que no corresponde a ninguna categoría conocida."""

    def __init__(self, campo: str, valor: object):
        super().__init__(f"Valor no reconocido en {campo}: {valor!r}")
        self.campo = campo
        self.valor = valor


def limpiar_texto(valor: object) -> str | None:
    """Quita espacios sobrantes. Devuelve None si queda vacío."""
    if valor is None:
        return None
    if isinstance(valor, float) and math.isnan(valor):
        return None
    texto = _ESPACIOS.sub(" ", str(valor)).strip()
    return texto or None


def reparar_enie(texto: str) -> str:
    """Repara la Ñ dañada (¿ entre letras) sin interpretar el significado del valor."""
    return _ENIE_DANADA.sub("Ñ", texto)


def quitar_tildes(texto: str, conservar_enie: bool = True) -> str:
    """Elimina tildes y diéresis. Por defecto conserva la Ñ (ANTONIO NARIÑO)."""
    resultado = []
    for caracter in texto:
        if conservar_enie and caracter in "ñÑ":
            resultado.append(caracter)
            continue
        descompuesto = unicodedata.normalize("NFD", caracter)
        resultado.append("".join(c for c in descompuesto if unicodedata.category(c) != "Mn"))
    return "".join(resultado)


def clave(valor: object) -> str | None:
    """Clave canónica de una categoría abierta: MAYÚSCULAS, sin tildes (salvo Ñ), Ñ reparada."""
    texto = limpiar_texto(valor)
    if texto is None:
        return None
    return quitar_tildes(reparar_enie(texto)).upper()


def recortar(texto: str | None, maximo: int) -> tuple[str | None, bool]:
    """Recorta al largo de la columna. Devuelve (texto, fue_recortado)."""
    if texto is None or len(texto) <= maximo:
        return texto, False
    return texto[:maximo], True


# --------------------------------------------------------------------------------------
# Localidades
# --------------------------------------------------------------------------------------

# Clave canónica (la que se guarda en la base de datos) -> nombre para mostrar.
LOCALIDADES: dict[str, str] = {
    "USAQUEN": "Usaquén",
    "CHAPINERO": "Chapinero",
    "SANTA FE": "Santa Fe",
    "SAN CRISTOBAL": "San Cristóbal",
    "USME": "Usme",
    "TUNJUELITO": "Tunjuelito",
    "BOSA": "Bosa",
    "KENNEDY": "Kennedy",
    "FONTIBON": "Fontibón",
    "ENGATIVA": "Engativá",
    "SUBA": "Suba",
    "BARRIOS UNIDOS": "Barrios Unidos",
    "TEUSAQUILLO": "Teusaquillo",
    "LOS MARTIRES": "Los Mártires",
    "ANTONIO NARIÑO": "Antonio Nariño",
    "PUENTE ARANDA": "Puente Aranda",
    "CANDELARIA": "La Candelaria",
    "RAFAEL URIBE URIBE": "Rafael Uribe Uribe",
    "CIUDAD BOLIVAR": "Ciudad Bolívar",
    "SUMAPAZ": "Sumapaz",
}

# Código oficial de localidad (1-20) -> clave canónica (útil para denominadores de población).
CODIGO_LOCALIDAD: dict[int, str] = {i + 1: k for i, k in enumerate(LOCALIDADES)}

_ALIAS_LOCALIDAD = {
    "LA CANDELARIA": "CANDELARIA",
    "ANTONIO NARINO": "ANTONIO NARIÑO",
    "RAFAEL URIBE": "RAFAEL URIBE URIBE",
    "MARTIRES": "LOS MARTIRES",
    "SANTAFE": "SANTA FE",
}


def normalizar_localidad(valor: object) -> str | None:
    """Devuelve la clave canónica de la localidad o None si viene vacía.

    Lanza ValorNoReconocido si el texto no corresponde a ninguna de las 20 localidades.
    Ejemplos: "USAQUÉN" (anuario), "USAQUEN" (ArcGIS) y "Usaquén" -> "USAQUEN".
    """
    k = clave(valor)
    if k is None:
        return None
    k = _ALIAS_LOCALIDAD.get(k, k)
    if k in LOCALIDADES:
        return k
    raise ValorNoReconocido("localidad", valor)


# --------------------------------------------------------------------------------------
# Categorías del siniestro
# --------------------------------------------------------------------------------------

# Gravedad canónica (coincide con el CHECK de la base de datos).
_GRAVEDAD = {
    "CON MUERTOS": "Con Muertos",
    "CON MUERTO": "Con Muertos",
    "CON HERIDOS": "Con Heridos",
    "CON HERIDO": "Con Heridos",
    "SOLO DANOS": "Solo Daños",
    "SOLO DAÑOS": "Solo Daños",
}


def normalizar_gravedad(valor: object) -> str | None:
    """'CON HERIDOS' (ArcGIS) / 'Con Heridos' (anuario) -> 'Con Heridos'. Vacío -> None."""
    k = clave(valor)
    if k is None:
        return None
    if k in _GRAVEDAD:
        return _GRAVEDAD[k]
    raise ValorNoReconocido("gravedad", valor)


CLASES_SINIESTRO: dict[str, str] = {
    "CHOQUE": "Choque",
    "ATROPELLO": "Atropello",
    "CAIDA DE OCUPANTE": "Caída de ocupante",
    "VOLCAMIENTO": "Volcamiento",
    "INCENDIO": "Incendio",
    "AUTOLESION": "Autolesión",
    "OTRO": "Otro",
}


def normalizar_clase(valor: object) -> tuple[str | None, bool]:
    """Devuelve (clase, reconocida). Una clase desconocida se conserva tal cual, sin reasignarla."""
    k = clave(valor)
    if k is None:
        return None, True
    if k in CLASES_SINIESTRO:
        return CLASES_SINIESTRO[k], True
    return limpiar_texto(valor), False


# --------------------------------------------------------------------------------------
# Personas
# --------------------------------------------------------------------------------------

ESTADOS_PERSONA = ("HERIDO", "ILESO", "MUERTO")


def normalizar_estado_persona(valor: object) -> str | None:
    k = clave(valor)
    if k is None:
        return None
    if k in ESTADOS_PERSONA:
        return k
    raise ValorNoReconocido("estado", valor)


_SEXO = {
    "MASCULINO": "MASCULINO", "M": "MASCULINO", "HOMBRE": "MASCULINO", "HOMBRES": "MASCULINO",
    "FEMENINO": "FEMENINO", "F": "FEMENINO", "MUJER": "FEMENINO", "MUJERES": "FEMENINO",
    "SIN INFORMACION": "SIN INFORMACION", "SIN INFORMACIÓN": "SIN INFORMACION", "NO REPORTADO": "SIN INFORMACION",
}


def normalizar_sexo(valor: object) -> str | None:
    k = clave(valor)
    if k is None:
        return None
    if k in _SEXO:
        return _SEXO[k]
    raise ValorNoReconocido("sexo", valor)


def normalizar_categoria(valor: object) -> str | None:
    """Categoría abierta (condición, clase de vehículo, servicio...): clave canónica sin reasignar."""
    return clave(valor)


EDAD_MINIMA, EDAD_MAXIMA = 0, 110

# Rangos de edad alineados con los cursos de vida del archivo oficial de población por localidad.
RANGOS_EDAD: tuple[tuple[int, int, str], ...] = (
    (0, 5, "0-5"),
    (6, 11, "6-11"),
    (12, 17, "12-17"),
    (18, 28, "18-28"),
    (29, 59, "29-59"),
    (60, EDAD_MAXIMA, "60+"),
)


def normalizar_edad(valor: object) -> int | None:
    """Edad entera entre 0 y 110. Cualquier otro valor (incluido 2021, >110, negativo) -> None."""
    numero = convertir_numero(valor)
    if numero is None or not float(numero).is_integer():
        return None
    edad = int(numero)
    return edad if EDAD_MINIMA <= edad <= EDAD_MAXIMA else None


def rango_edad(edad: int | None) -> str | None:
    if edad is None:
        return None
    for minimo, maximo, etiqueta in RANGOS_EDAD:
        if minimo <= edad <= maximo:
            return etiqueta
    return None


def normalizar_si_no(valor: object) -> bool | None:
    k = clave(valor)
    if k in ("S", "SI", "TRUE", "1"):
        return True
    if k in ("N", "NO", "FALSE", "0"):
        return False
    return None


# --------------------------------------------------------------------------------------
# Números y coordenadas
# --------------------------------------------------------------------------------------


def convertir_numero(valor: object) -> float | None:
    """Convierte a número. Acepta coma decimal ("4,58396") del anuario 2025. Nunca inventa."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return None if (isinstance(valor, float) and (math.isnan(valor) or math.isinf(valor))) else float(valor)
    texto = limpiar_texto(valor)
    if texto is None:
        return None
    if "," in texto and "." not in texto:
        texto = texto.replace(",", ".")
    try:
        numero = float(texto)
    except ValueError:
        return None
    return None if math.isnan(numero) or math.isinf(numero) else numero


def convertir_entero(valor: object) -> int | None:
    numero = convertir_numero(valor)
    if numero is None or not numero.is_integer():
        return None
    return int(numero)


@dataclass(frozen=True)
class CajaGeografica:
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float

    def contiene(self, lat: float, lon: float) -> bool:
        return self.lat_min <= lat <= self.lat_max and self.lon_min <= lon <= self.lon_max


# Caja amplia de Bogotá D.C. Incluye Sumapaz (al sur, hasta ~3.7). No es un límite oficial: solo
# descarta puntos evidentemente fuera del Distrito. La coherencia fina se revisa por localidad.
CAJA_BOGOTA = CajaGeografica(lat_min=3.70, lat_max=4.90, lon_min=-74.50, lon_max=-73.90)

MOTIVOS_COORDENADA = ("sin_coordenada", "fuera_de_rango", "fuera_de_bogota", "sospechosa")


@dataclass(frozen=True)
class ResultadoCoordenada:
    latitud: float | None
    longitud: float | None
    valida: bool
    motivo: str | None


def validar_coordenada(latitud: object, longitud: object, caja: CajaGeografica = CAJA_BOGOTA) -> ResultadoCoordenada:
    """Valida sin imputar. Si la coordenada no es válida se conserva el valor (si está en rango
    mundial) para auditoría, pero queda marcada con su motivo y nunca se muestra en el mapa."""
    lat, lon = convertir_numero(latitud), convertir_numero(longitud)
    if lat is None or lon is None:
        return ResultadoCoordenada(None, None, False, "sin_coordenada")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        # Fuera de rango mundial: no cabe en la columna, se descarta el valor.
        return ResultadoCoordenada(None, None, False, "fuera_de_rango")
    if lat == 0 and lon == 0:
        return ResultadoCoordenada(lat, lon, False, "fuera_de_bogota")
    if not caja.contiene(lat, lon):
        return ResultadoCoordenada(lat, lon, False, "fuera_de_bogota")
    return ResultadoCoordenada(lat, lon, True, None)


def _percentil(valores_ordenados: list[float], p: float) -> float:
    """Percentil por interpolación lineal (valores ya ordenados)."""
    if not valores_ordenados:
        raise ValueError("lista vacía")
    posicion = (len(valores_ordenados) - 1) * p
    inferior = math.floor(posicion)
    superior = math.ceil(posicion)
    if inferior == superior:
        return valores_ordenados[int(posicion)]
    fraccion = posicion - inferior
    return valores_ordenados[inferior] * (1 - fraccion) + valores_ordenados[superior] * fraccion


def detectar_coordenadas_sospechosas(
    puntos: Iterable[tuple[int, str | None, float, float]],
    percentil: float = 0.001,
    margen_grados: float = 0.03,
    minimo_por_localidad: int = 50,
) -> set[int]:
    """Heurística de coherencia localidad-coordenada (mientras no haya polígonos oficiales).

    Para cada localidad con al menos `minimo_por_localidad` puntos se calcula la caja entre los
    percentiles `percentil` y `1 - percentil` de latitud y longitud, ampliada `margen_grados`
    (0.03° ≈ 3,3 km). Un punto fuera de esa caja queda como "sospechosa": no se borra ni se mueve,
    solo deja de mostrarse en el mapa. `puntos` = (id_registro, localidad, latitud, longitud).
    """
    por_localidad: dict[str, list[tuple[int, float, float]]] = defaultdict(list)
    for id_registro, localidad, lat, lon in puntos:
        if localidad is None or lat is None or lon is None:
            continue
        por_localidad[localidad].append((id_registro, lat, lon))

    sospechosas: set[int] = set()
    for filas in por_localidad.values():
        if len(filas) < minimo_por_localidad:
            continue
        lats = sorted(f[1] for f in filas)
        lons = sorted(f[2] for f in filas)
        lat_min = _percentil(lats, percentil) - margen_grados
        lat_max = _percentil(lats, 1 - percentil) + margen_grados
        lon_min = _percentil(lons, percentil) - margen_grados
        lon_max = _percentil(lons, 1 - percentil) + margen_grados
        for id_registro, lat, lon in filas:
            if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
                sospechosas.add(id_registro)
    return sospechosas


# --------------------------------------------------------------------------------------
# Fechas y horas
# --------------------------------------------------------------------------------------

ZONA_BOGOTA = timezone(timedelta(hours=-5), "America/Bogota")  # Colombia no usa horario de verano
_MS_DIA = 86_400_000

DIAS_SEMANA = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre")


def fecha_desde_epoch_ms(ms: object) -> date | None:
    """Convierte un campo fecha de ArcGIS (milisegundos desde 1970, UTC) a fecha local SIN correr el día.

    Verificado en el servicio SIMUR (16-11-2026): FECHA_OCURRENCIA_ACC llega como medianoche UTC
    de la fecha local (1794268800000 = 2026-11-10 00:00 UTC, día "MARTES" en la fuente). Si se
    restaran 5 horas la fecha pasaría al día anterior. Por eso:
    - múltiplo exacto de un día  -> fecha UTC (medianoche UTC = fecha local);
    - cualquier otro valor       -> instante real convertido a hora de Bogotá (UTC-5), lo que
                                    también cubre la medianoche de Bogotá expresada en UTC (05:00).
    """
    numero = convertir_numero(ms)
    if numero is None:
        return None
    entero = int(numero)
    if entero % _MS_DIA == 0:
        return datetime.fromtimestamp(entero / 1000, tz=timezone.utc).date()
    return datetime.fromtimestamp(entero / 1000, tz=ZONA_BOGOTA).date()


_HORA = re.compile(r"^\s*(\d{1,2})\s*[:.hH]\s*(\d{1,2})(?:\s*[:.]\s*(\d{1,2}))?\s*$")


def hora_desde_texto(valor: object) -> tuple[int | None, int | None]:
    """'19:50:00' -> (19, 50). Valores no interpretables -> (None, None). No inventa la hora."""
    texto = limpiar_texto(valor)
    if texto is None:
        return None, None
    coincidencia = _HORA.match(texto)
    if not coincidencia:
        return None, None
    hora, minuto = int(coincidencia.group(1)), int(coincidencia.group(2))
    if 0 <= hora <= 23 and 0 <= minuto <= 59:
        return hora, minuto
    return None, None


def hora_desde_enteros(hora: object, minuto: object) -> tuple[int | None, int | None]:
    """Anuarios: Hora_Acc y Min_Acc en columnas separadas."""
    h, m = convertir_entero(hora), convertir_entero(minuto)
    h = h if h is not None and 0 <= h <= 23 else None
    m = m if m is not None and 0 <= m <= 59 else None
    if h is None:
        return None, None
    return h, m


def dia_semana(fecha: date) -> str:
    return DIAS_SEMANA[fecha.weekday()]


def hoy_bogota() -> date:
    return datetime.now(tz=ZONA_BOGOTA).date()
