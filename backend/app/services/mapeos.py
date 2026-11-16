"""Mapeos configurables columna original -> campo lógico (archivos JSON en app/data/mapeos/).

Cada campo lógico lista columnas candidatas; se usa la primera que exista en el archivo. La
comparación ignora mayúsculas, tildes y espacios ("Gravedad_indicador_30d" = "GRAVEDAD INDICADOR 30D").
El administrador puede sobrescribir cualquier campo con el nombre exacto de una columna.
Las columnas con datos personales nunca se leen, aunque estén en el archivo o se pidan.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from .calidad import quitar_tildes

DIRECTORIO_MAPEOS = Path(__file__).resolve().parents[1] / "data" / "mapeos"

TiposHoja = Literal["siniestros", "actores", "vehiculos", "poblacion"]

# Campo lógico -> obligatorio. Solo es obligatorio lo indispensable para guardar un registro.
CAMPOS_LOGICOS: dict[str, dict[str, bool]] = {
    "siniestros": {
        "id_registro": True, "fecha_evento": True, "formulario": False, "anio_control": False,
        "mes_control": False, "dia_control": False, "hora": False, "minuto": False, "localidad": False,
        "direccion": False, "clase_siniestro": False, "gravedad": False, "gravedad_tradicional": False,
        "latitud": False, "longitud": False,
    },
    "actores": {
        "id_registro": True, "consecutivo_victima": True, "codigo_vehiculo": False, "estado": False,
        "condicion": False, "condicion_especifica": False, "sexo": False, "edad": False, "muerte_posterior": False,
    },
    "vehiculos": {"id_registro": True, "codigo_vehiculo": True, "clase": False, "servicio": False, "modalidad": False},
    "poblacion": {"anio": True, "codigo_localidad": False, "nombre_localidad": False, "poblacion": True},
}

# Columnas que jamás se leen (claves normalizadas).
COLUMNAS_PERSONALES = frozenset({
    "PLACA", "FECHA_NACIMIENTO", "CODIGO_ACCIDENTADO", "NOMBRE", "NOMBRES", "APELLIDO", "APELLIDOS",
    "DOCUMENTO", "NUMERO_DOCUMENTO", "NRO_DOCUMENTO", "TIPO_DOCUMENTO", "CEDULA", "IDENTIFICACION",
    "TELEFONO", "CELULAR", "CORREO", "EMAIL", "DIRECCION_RESIDENCIA",
})


def clave_columna(nombre: str) -> str:
    """'Gravedad indicador 30d' -> 'GRAVEDAD_INDICADOR_30D'; 'AÑO' -> 'ANO'; 'Vehículos' -> 'VEHICULOS'."""
    texto = quitar_tildes(str(nombre), conservar_enie=False).upper()
    return re.sub(r"[^A-Z0-9]+", "_", texto).strip("_")


def es_personal(nombre: str) -> bool:
    return clave_columna(nombre) in COLUMNAS_PERSONALES


class HojaMapeo(BaseModel):
    tipo: TiposHoja
    nombres_hoja: list[str] = Field(default_factory=list)
    formatos_fecha: list[str] = Field(default_factory=lambda: ["%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y"])
    campos: dict[str, list[str]]
    columnas_atributos: list[str] = Field(default_factory=list)
    prefijos_banderas: list[str] = Field(default_factory=list)
    notas: str | None = None

    @model_validator(mode="after")
    def _validar(self):
        validos = CAMPOS_LOGICOS[self.tipo]
        desconocidos = set(self.campos) - set(validos)
        if desconocidos:
            raise ValueError(f"Campos lógicos desconocidos para '{self.tipo}': {sorted(desconocidos)}")
        for campo, obligatorio in validos.items():
            if obligatorio and not self.campos.get(campo):
                raise ValueError(f"El campo obligatorio '{campo}' no tiene columnas candidatas")
        personales = [c for cols in self.campos.values() for c in cols if es_personal(c)]
        personales += [c for c in self.columnas_atributos if es_personal(c)]
        if personales:
            raise ValueError(f"El mapeo no puede usar columnas con datos personales: {personales}")
        return self


class Mapeo(BaseModel):
    codigo: str
    fuente_codigo: str
    descripcion: str
    verificado: str
    hojas: dict[str, HojaMapeo]


class ErrorMapeo(ValueError):
    pass


@lru_cache
def cargar_mapeo(codigo: str, directorio: Path = DIRECTORIO_MAPEOS) -> Mapeo:
    if not re.fullmatch(r"[a-z0-9_]{1,60}", codigo or ""):
        raise ErrorMapeo("Código de mapeo inválido.")
    ruta = Path(directorio) / f"{codigo}.json"
    if not ruta.is_file():
        raise ErrorMapeo(f"No existe el mapeo '{codigo}'. Disponibles: {', '.join(listar_mapeos(directorio))}")
    try:
        return Mapeo.model_validate(json.loads(ruta.read_text(encoding="utf-8")))
    except (ValidationError, json.JSONDecodeError) as exc:
        raise ErrorMapeo(f"El mapeo '{codigo}' no es válido: {exc}") from exc


def listar_mapeos(directorio: Path = DIRECTORIO_MAPEOS) -> list[str]:
    return sorted(p.stem for p in Path(directorio).glob("*.json"))


@dataclass
class ResolucionMapeo:
    campos: dict[str, str]                       # campo lógico -> nombre ORIGINAL de la columna
    faltantes_obligatorios: list[str]
    sin_columna: list[str]                       # campos opcionales ausentes en el archivo
    personales_omitidas: list[str]
    atributos: list[str]                         # columnas que van a `atributos`
    no_usadas: list[str] = field(default_factory=list)

    @property
    def completo(self) -> bool:
        return not self.faltantes_obligatorios


def resolver_hoja(mapeo: Mapeo, tipo: str, nombre_hoja: str | None, hojas_libro: list[str]) -> str | None:
    """Elige la hoja del libro para el tipo pedido (por nombre configurado), o valida la indicada."""
    if not hojas_libro:
        return None  # CSV
    if nombre_hoja:
        if nombre_hoja not in hojas_libro:
            raise ErrorMapeo(f"La hoja '{nombre_hoja}' no existe. Hojas: {', '.join(hojas_libro)}")
        return nombre_hoja
    hoja_mapeo = mapeo.hojas.get(tipo)
    candidatas = {clave_columna(n) for n in (hoja_mapeo.nombres_hoja if hoja_mapeo else [])}
    for h in hojas_libro:
        if clave_columna(h) in candidatas:
            return h
    raise ErrorMapeo(f"No se encontró la hoja de '{tipo}'. Indíquela. Hojas: {', '.join(hojas_libro)}")


def resolver_columnas(hoja: HojaMapeo, columnas: list[str], sobrescribir: dict[str, str] | None = None) -> ResolucionMapeo:
    por_clave = {clave_columna(c): c for c in columnas if not es_personal(c)}
    personales = [c for c in columnas if es_personal(c)]
    campos: dict[str, str] = {}
    for campo, candidatas in hoja.campos.items():
        for candidata in candidatas:
            original = por_clave.get(clave_columna(candidata))
            if original:
                campos[campo] = original
                break
    for campo, columna in (sobrescribir or {}).items():
        if campo not in CAMPOS_LOGICOS[hoja.tipo]:
            raise ErrorMapeo(f"Campo '{campo}' desconocido para hojas de tipo '{hoja.tipo}'.")
        if columna in (None, ""):
            campos.pop(campo, None)
            continue
        if es_personal(columna):
            raise ErrorMapeo(f"La columna '{columna}' contiene datos personales y no se importa.")
        if columna not in columnas:
            raise ErrorMapeo(f"La columna '{columna}' no existe en el archivo.")
        campos[campo] = columna
    obligatorios = [c for c, o in CAMPOS_LOGICOS[hoja.tipo].items() if o and c not in campos]
    opcionales = [c for c, o in CAMPOS_LOGICOS[hoja.tipo].items() if not o and c not in campos]
    usadas = set(campos.values())
    claves_atributos = {clave_columna(c) for c in hoja.columnas_atributos}
    # "Con_" -> "CON_" (se conserva el guion bajo final para no capturar "CONDICION")
    prefijos = tuple(clave_columna(p) + ("_" if p.endswith(("_", " ")) else "") for p in hoja.prefijos_banderas)
    atributos = [c for c in columnas if c not in usadas and not es_personal(c)
                 and (clave_columna(c) in claves_atributos or (prefijos and clave_columna(c).startswith(prefijos)))]
    no_usadas = [c for c in columnas if c not in usadas and c not in atributos and not es_personal(c)]
    return ResolucionMapeo(campos, obligatorios, opcionales, personales, atributos, no_usadas)
