"""Importador de archivos del administrador: anuarios (CSV/XLSX), población (CSV) y polígonos (GeoJSON).

Flujo en dos pasos:
1. previsualizar(): valida el archivo, elige la hoja, resuelve el mapeo de columnas, muestra las
   primeras filas (sin columnas personales), infiere tipos y valida una muestra. Registra la
   importación en estado "previsualizada". No escribe datos.
2. confirmar(): vuelve a comprobar el archivo (huella SHA-256), procesa por bloques y registra el
   resultado: "completada" o "fallida". Estados: previsualizada -> en_proceso -> completada | fallida;
   o previsualizada -> cancelada.

Tipos de carga (columna importaciones.modo): siniestros, actores, vehiculos, poblacion, localidades.
En importaciones.tipo se usa "excel" para toda carga manual de archivo (CSV, XLSX o GeoJSON).
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Protocol

from . import calidad, geo_localidades
from .archivos import ArchivoRecibido, ErrorArchivo, eliminar_recibido, ruta_de_token, sha256_de
from .arcgis_sync import (
    Contadores, FuenteInfo, RegistroSiniestro, transformar_actor, transformar_vehiculo,
)
from .lectores import abrir_tabla
from .mapeos import ErrorMapeo, HojaMapeo, ResolucionMapeo, cargar_mapeo, resolver_columnas, resolver_hoja

log = logging.getLogger("via_segura.importador")

TIPOS = ("siniestros", "actores", "vehiculos", "poblacion", "localidades")
FILAS_MUESTRA = 20
FILAS_VALIDACION_PREVIA = 1000
CODIGO_FUENTE_LOCALIDADES = "localidades_bogota"
CLAVE_TOTAL_BOGOTA = "BOGOTA"  # denominador de toda la ciudad (código 0 del archivo de población)

_MESES = {calidad.clave(m): i + 1 for i, m in enumerate(calidad.MESES)}
_MESES["SETIEMBRE"] = 9


class ErrorImportacion(ValueError):
    """Error con mensaje apto para el administrador."""


# =============================================================================== protocolo

class RepositorioImportacion(Protocol):
    def obtener_fuente(self, codigo: str) -> FuenteInfo: ...
    def crear_importacion_archivo(self, *, fuente_id: int, modo: str, archivo: str, hoja: str | None,
                                  mapeo: dict, resumen: dict, usuario_id: int | None) -> int: ...
    def obtener_importacion(self, importacion_id: int) -> dict | None: ...
    def reservar_importacion(self, importacion_id: int, estados: tuple[str, ...]) -> bool: ...
    def actualizar_importacion(self, importacion_id: int, **campos) -> None: ...
    def guardar_lote(self, fuente_id: int, importacion_id: int, registros: list[RegistroSiniestro],
                     reemplazar_hijos: bool = True) -> tuple[int, int]: ...
    def mapa_ids(self, fuente_id: int, ids: list[int]) -> dict[int, int]: ...
    def reemplazar_hijos(self, tipo: str, filas: list[dict], limpiar: list[int]) -> None: ...
    def siniestros_sin_hijos(self, fuente_id: int, tipo: str) -> int: ...
    def upsert_denominadores(self, fuente_id: int, filas: list[tuple[str, int, int]]) -> tuple[int, int]: ...
    def periodo_real(self, fuente_id: int) -> tuple[date | None, date | None]: ...
    def puntos_para_coherencia(self, fuente_id: int): ...
    def aplicar_coherencia(self, fuente_id: int, sospechosas: set[int]) -> int: ...
    def coincidencias_otras_fuentes(self, fuente_id: int) -> list[dict]: ...
    def actualizar_fuente(self, fuente_id: int, **campos) -> None: ...
    def confirmar(self) -> None: ...
    def revertir(self) -> None: ...


# =============================================================================== resultados

@dataclass
class Previsualizacion:
    importacion_id: int
    archivo: str
    tipo: str
    hojas: list[str]
    hoja: str | None
    columnas: list[dict]
    filas_muestra: list[dict]
    mapeo: dict[str, str]
    faltantes_obligatorios: list[str]
    campos_sin_columna: list[str]
    columnas_personales_omitidas: list[str]
    columnas_atributos: list[str]
    columnas_no_usadas: list[str]
    filas_estimadas: int | None
    validacion: dict
    advertencias: list[str] = field(default_factory=list)

    @property
    def puede_confirmar(self) -> bool:
        return not self.faltantes_obligatorios and self.validacion.get("validas", 0) > 0

    def como_dict(self) -> dict:
        d = dict(self.__dict__)
        d["puede_confirmar"] = self.puede_confirmar
        return d


@dataclass
class ResultadoImportacion:
    importacion_id: int
    estado: str
    tipo: str
    filas_revisadas: int = 0
    filas_validas: int = 0
    filas_rechazadas: int = 0
    nuevos: int = 0
    actualizados: int = 0
    fecha_min: date | None = None
    fecha_max: date | None = None
    mensaje: str = ""
    resumen: dict = field(default_factory=dict)


# =============================================================================== transformaciones (puras)

def _v(fila: dict, res: ResolucionMapeo, campo: str) -> object:
    columna = res.campos.get(campo)
    return fila.get(columna) if columna else None


def _mes(valor: object) -> int | None:
    numero = calidad.convertir_entero(valor)
    if numero is not None:
        return numero if 1 <= numero <= 12 else None
    return _MESES.get(calidad.clave(valor) or "")


def interpretar_fecha(valor: object, formatos: list[str], anio: int | None = None, mes: int | None = None,
                      dia: int | None = None) -> tuple[date | None, str | None]:
    """Devuelve (fecha, error). Con columnas de control (año/mes/día) elige el formato coherente:
    así '02/09/2015' con mes 'Febrero' se lee 9-feb y no 2-sep. Sin controles usa el primer formato."""
    if valor is None:
        return None, "fecha vacía"
    if isinstance(valor, datetime):
        candidatas = [valor.date()]
    elif isinstance(valor, date):
        candidatas = [valor]
    else:
        texto = calidad.limpiar_texto(valor) or ""
        texto = texto.split(" ")[0] if " " in texto and ":" in texto else texto  # '2015-02-09 00:00:00'
        candidatas = []
        for formato in formatos:
            try:
                f = datetime.strptime(texto, formato).date()
            except ValueError:
                continue
            if f not in candidatas:
                candidatas.append(f)
        if not candidatas:
            return None, f"fecha '{texto}' no tiene un formato reconocido"
    coherentes = [f for f in candidatas
                  if (anio is None or f.year == anio) and (mes is None or f.month == mes) and (dia is None or f.day == dia)]
    if not coherentes:
        return None, (f"fecha '{valor}' incoherente con las columnas de control "
                      f"(año={anio}, mes={mes}, día={dia})")
    return coherentes[0], None


def _banderas(fila: dict, res: ResolucionMapeo, hoja: HojaMapeo) -> dict:
    atributos: dict = {}
    prefijos = tuple(p.lower() for p in hoja.prefijos_banderas)
    for columna in res.atributos:
        valor = fila.get(columna)
        if valor is None:
            continue
        clave = columna.strip().lower().replace(" ", "_")
        if prefijos and clave.startswith(prefijos):
            if calidad.clave(valor) in ("SI", "S", "1", "TRUE", "X"):
                atributos[clave] = True
        else:
            atributos[clave] = calidad.limpiar_texto(valor)
    return atributos


def transformar_siniestro(numero: int, fila: dict, res: ResolucionMapeo, hoja: HojaMapeo, hoy: date,
                          cont: Contadores) -> RegistroSiniestro | None:
    id_registro = calidad.convertir_entero(_v(fila, res, "id_registro"))
    if id_registro is None or id_registro <= 0:
        cont.sumar("rechazo.id_invalido")
        cont.error(f"Fila {numero}: identificador del siniestro vacío o no entero.")
        return None
    fecha, error = interpretar_fecha(
        _v(fila, res, "fecha_evento"), hoja.formatos_fecha,
        anio=calidad.convertir_entero(_v(fila, res, "anio_control")),
        mes=_mes(_v(fila, res, "mes_control")),
        dia=calidad.convertir_entero(_v(fila, res, "dia_control")))
    if fecha is None:
        cont.sumar("rechazo.fecha")
        cont.error(f"Fila {numero} (siniestro {id_registro}): {error}.")
        return None
    if fecha > hoy:
        cont.sumar("rechazo.fecha_futura")
        cont.error(f"Fila {numero} (siniestro {id_registro}): fecha {fecha.isoformat()} posterior a hoy.")
        return None
    try:
        gravedad = calidad.normalizar_gravedad(_v(fila, res, "gravedad"))
    except calidad.ValorNoReconocido:
        cont.sumar("rechazo.gravedad_no_reconocida")
        cont.categoria("gravedad_no_reconocida", _v(fila, res, "gravedad"))
        cont.error(f"Fila {numero} (siniestro {id_registro}): gravedad no reconocida {_v(fila, res, 'gravedad')!r}.")
        return None
    if gravedad is None:
        cont.sumar("gravedad_vacia")
    try:
        gravedad_trad = calidad.normalizar_gravedad(_v(fila, res, "gravedad_tradicional"))
    except calidad.ValorNoReconocido:
        gravedad_trad = None
        cont.categoria("gravedad_tradicional_no_reconocida", _v(fila, res, "gravedad_tradicional"))

    atributos = _banderas(fila, res, hoja)
    try:
        localidad = calidad.normalizar_localidad(_v(fila, res, "localidad"))
    except calidad.ValorNoReconocido:
        localidad = None
        atributos["localidad_original"] = calidad.limpiar_texto(_v(fila, res, "localidad"))
        cont.categoria("localidad_no_reconocida", _v(fila, res, "localidad"))
    if localidad is None:
        cont.sumar("localidad_vacia_o_no_reconocida")

    clase, reconocida = calidad.normalizar_clase(_v(fila, res, "clase_siniestro"))
    if not reconocida:
        cont.categoria("clase_no_reconocida", clase)
    clase, _ = calidad.recortar(clase, 40)

    hora_valor = _v(fila, res, "hora")
    if isinstance(hora_valor, str) and ":" in hora_valor:
        hora, minuto = calidad.hora_desde_texto(hora_valor)
    else:
        hora, minuto = calidad.hora_desde_enteros(hora_valor, _v(fila, res, "minuto"))
    if hora is None:
        cont.sumar("hora_vacia_o_invalida")

    coordenada = calidad.validar_coordenada(_v(fila, res, "latitud"), _v(fila, res, "longitud"))
    if not coordenada.valida:
        cont.sumar(f"coordenada.{coordenada.motivo}")

    return RegistroSiniestro(siniestro={
        "id_registro": id_registro,
        "formulario": calidad.recortar(calidad.limpiar_texto(_v(fila, res, "formulario")), 20)[0],
        "fecha_evento": fecha,
        "anio": fecha.year,
        "mes": fecha.month,
        "dia_semana": calidad.dia_semana(fecha),
        "hora": hora,
        "minuto": minuto,
        "localidad": localidad,
        "direccion": calidad.recortar(calidad.limpiar_texto(_v(fila, res, "direccion")), 150)[0],
        "barrio": None,
        "via_nombre": None,
        "clase_siniestro": clase,
        "gravedad": gravedad,
        "gravedad_tradicional": gravedad_trad,
        "latitud": coordenada.latitud,
        "longitud": coordenada.longitud,
        "coordenada_valida": coordenada.valida,
        "motivo_coordenada": coordenada.motivo,
        "atributos": atributos or None,
    })


def transformar_hijo(tipo: str, numero: int, fila: dict, res: ResolucionMapeo,
                     cont: Contadores) -> tuple[int, dict] | None:
    """Fila de Actor vial o Vehículos -> (id_registro del siniestro, fila normalizada).
    Reutiliza las mismas reglas que la sincronización ArcGIS."""
    id_registro = calidad.convertir_entero(_v(fila, res, "id_registro"))
    if id_registro is None or id_registro <= 0:
        cont.sumar("rechazo.id_invalido")
        cont.error(f"Fila {numero}: identificador del siniestro vacío o no entero.")
        return None
    if tipo == "actores":
        hijo = transformar_actor({
            "CODIGO_VICTIMA": _v(fila, res, "consecutivo_victima"),
            "CODIGO_VEHICULO": _v(fila, res, "codigo_vehiculo"),
            "ESTADO": _v(fila, res, "estado"),
            "CONDICION": _v(fila, res, "condicion"),
            "CONDICION_A": _v(fila, res, "condicion_especifica"),
            "GENERO": _v(fila, res, "sexo"),
            "EDAD": _v(fila, res, "edad"),
            "MUERTE_POSTERIOR": _v(fila, res, "muerte_posterior"),
        }, cont)
    else:
        hijo = transformar_vehiculo({
            "CODIGO_VEHICULO": _v(fila, res, "codigo_vehiculo"),
            "CLASE": _v(fila, res, "clase"),
            "SERVICIO": _v(fila, res, "servicio"),
            "MODALIDAD": _v(fila, res, "modalidad"),
        }, cont)
    if hijo is None:
        cont.error(f"Fila {numero} (siniestro {id_registro}): falta el código de persona o de vehículo.")
        return None
    return id_registro, hijo


def transformar_poblacion(numero: int, fila: dict, res: ResolucionMapeo,
                          cont: Contadores) -> tuple[str, int, int] | None:
    anio = calidad.convertir_entero(_v(fila, res, "anio"))
    poblacion = calidad.convertir_entero(_v(fila, res, "poblacion"))
    if anio is None or not 1900 <= anio <= 2100:
        cont.sumar("rechazo.anio")
        cont.error(f"Fila {numero}: año inválido {_v(fila, res, 'anio')!r}.")
        return None
    if poblacion is None or poblacion < 0:
        cont.sumar("rechazo.poblacion")
        cont.error(f"Fila {numero}: población inválida {_v(fila, res, 'poblacion')!r}.")
        return None
    codigo = calidad.convertir_entero(_v(fila, res, "codigo_localidad"))
    nombre = _v(fila, res, "nombre_localidad")
    por_codigo = CLAVE_TOTAL_BOGOTA if codigo == 0 else calidad.CODIGO_LOCALIDAD.get(codigo) if codigo else None
    por_nombre = None
    if nombre is not None:
        if calidad.clave(nombre) in ("BOGOTA", "BOGOTA D.C.", "BOGOTA DC", "TOTAL BOGOTA"):
            por_nombre = CLAVE_TOTAL_BOGOTA
        else:
            try:
                por_nombre = calidad.normalizar_localidad(nombre)
            except calidad.ValorNoReconocido:
                por_nombre = None
    if por_codigo and por_nombre and por_codigo != por_nombre:
        cont.sumar("rechazo.codigo_y_nombre_no_coinciden")
        cont.error(f"Fila {numero}: el código {codigo} no corresponde a '{nombre}'.")
        return None
    localidad = por_codigo or por_nombre
    if localidad is None:
        cont.sumar("rechazo.localidad")
        cont.categoria("localidad_no_reconocida", nombre if nombre is not None else codigo)
        return None
    return localidad, anio, poblacion


def _tipo_valor(valor: object) -> str:
    if valor is None:
        return "vacío"
    if isinstance(valor, bool):
        return "texto"
    if isinstance(valor, (datetime, date)):
        return "fecha"
    if isinstance(valor, int):
        return "entero"
    if isinstance(valor, float):
        return "entero" if valor.is_integer() else "decimal"
    texto = str(valor)
    if calidad.convertir_entero(texto) is not None and "," not in texto:
        return "entero"
    if calidad.convertir_numero(texto) is not None:
        return "decimal con coma" if "," in texto else "decimal"
    if "/" in texto and len(texto) <= 10 and texto.replace("/", "").isdigit():
        return "fecha (texto)"
    return "texto"


def inferir_tipos(columnas: list[str], filas: list[dict]) -> dict[str, str]:
    salida = {}
    for c in columnas:
        tipos = Counter(_tipo_valor(f.get(c)) for f in filas)
        tipos.pop("vacío", None)
        if not tipos:
            salida[c] = "vacío"
        elif len(tipos) == 1:
            salida[c] = next(iter(tipos))
        elif set(tipos) <= {"entero", "decimal"}:
            salida[c] = "decimal"
        else:
            salida[c] = "mixto: " + ", ".join(t for t, _ in tipos.most_common(3))
    return salida


# =============================================================================== orquestación

class ImportadorArchivos:
    def __init__(
        self,
        repositorio: RepositorioImportacion,
        directorio_cargas: Path,
        directorio_geo: Path,
        *,
        hoy: date | None = None,
        bloque: int = 2000,
        tolerancia_geo: float = 0.00005,
        coherencia_percentil: float = 0.001,
        coherencia_margen: float = 0.03,
        conservar_archivo: bool = False,
        progreso: Callable[[str], None] | None = None,
    ):
        self.repo = repositorio
        self.directorio_cargas = Path(directorio_cargas)
        self.directorio_geo = Path(directorio_geo)
        self.hoy = hoy or calidad.hoy_bogota()
        self.bloque = bloque
        self.tolerancia_geo = tolerancia_geo
        self.coherencia_percentil = coherencia_percentil
        self.coherencia_margen = coherencia_margen
        self.conservar_archivo = conservar_archivo
        self._progreso = progreso or (lambda _m: None)

    # ------------------------------------------------------------------ previsualización
    def previsualizar(
        self,
        recibido: ArchivoRecibido,
        *,
        tipo: str,
        mapeo_codigo: str | None = None,
        hoja: str | None = None,
        sobrescribir: dict[str, str] | None = None,
        usuario_id: int | None = None,
    ) -> Previsualizacion:
        if tipo not in TIPOS:
            raise ErrorImportacion(f"Tipo de carga desconocido '{tipo}'. Opciones: {', '.join(TIPOS)}")
        info_archivo = {"token": recibido.token, "nombre": recibido.nombre, "sha256": recibido.sha256,
                        "tamano": recibido.tamano, "extension": recibido.extension}
        try:
            if tipo == "localidades":
                return self._previsualizar_geo(recibido, info_archivo, usuario_id)
            if recibido.extension not in (".csv", ".xlsx"):
                raise ErrorImportacion(f"Para '{tipo}' se espera un CSV o XLSX, no {recibido.extension}.")
            if not mapeo_codigo:
                raise ErrorImportacion("Indique el mapeo de columnas (por ejemplo, anuario_sdm_2025).")
            return self._previsualizar_tabla(recibido, info_archivo, tipo, mapeo_codigo, hoja, sobrescribir,
                                             usuario_id)
        except (ErrorImportacion, ErrorMapeo, ErrorArchivo, geo_localidades.ErrorGeo):
            eliminar_recibido(self.directorio_cargas, recibido.token)
            raise

    def _previsualizar_tabla(self, recibido, info_archivo, tipo, mapeo_codigo, hoja, sobrescribir, usuario_id):
        mapeo = cargar_mapeo(mapeo_codigo)
        if tipo not in mapeo.hojas:
            raise ErrorImportacion(f"El mapeo '{mapeo_codigo}' no define una hoja de tipo '{tipo}'. "
                                   f"Tipos disponibles: {', '.join(mapeo.hojas)}")
        hoja_mapeo = mapeo.hojas[tipo]
        lector = abrir_tabla(recibido.ruta)
        try:
            hoja_elegida = resolver_hoja(mapeo, tipo, hoja, lector.hojas)
            columnas = lector.columnas(hoja_elegida)
            res = resolver_columnas(hoja_mapeo, columnas, sobrescribir)
            primeras: list[tuple[int, dict]] = []
            for bloque in lector.filas(hoja_elegida, bloque=FILAS_VALIDACION_PREVIA, limite=FILAS_VALIDACION_PREVIA):
                primeras.extend(bloque)
            filas_estimadas = lector.contar_filas(hoja_elegida)
        finally:
            lector.cerrar()

        visibles = [c for c in columnas if c not in res.personales_omitidas]
        tipos = inferir_tipos(visibles, [f for _, f in primeras[:200]])
        muestra = [{c: _a_texto(f.get(c)) for c in visibles} for _, f in primeras[:FILAS_MUESTRA]]
        validacion = self._validar_muestra(tipo, primeras, res, hoja_mapeo) if res.completo else {
            "revisadas": 0, "validas": 0, "rechazadas": 0, "motivos": {},
            "nota": "No se validó: faltan columnas obligatorias."}
        advertencias = []
        if res.personales_omitidas:
            advertencias.append("Columnas con datos personales omitidas (no se leen ni se guardan): "
                                + ", ".join(res.personales_omitidas))
        if res.faltantes_obligatorios:
            advertencias.append("Faltan columnas obligatorias: " + ", ".join(res.faltantes_obligatorios)
                                + ". Indíquelas en el mapeo para poder confirmar.")
        if res.sin_columna:
            advertencias.append("Campos sin columna en este archivo (quedarán vacíos, no se inventan): "
                                + ", ".join(res.sin_columna))

        fuente = self.repo.obtener_fuente(mapeo.fuente_codigo)
        importacion_id = self.repo.crear_importacion_archivo(
            fuente_id=fuente.id, modo=tipo, archivo=recibido.nombre, hoja=hoja_elegida, mapeo=res.campos,
            usuario_id=usuario_id,
            resumen={"archivo": info_archivo, "tipo": tipo, "mapeo_codigo": mapeo_codigo,
                     "sobrescribir": sobrescribir or {}, "previsualizacion": validacion,
                     "columnas_atributos": res.atributos, "advertencias": advertencias})
        self.repo.confirmar()
        return Previsualizacion(
            importacion_id=importacion_id, archivo=recibido.nombre, tipo=tipo, hojas=list(lector.hojas),
            hoja=hoja_elegida, columnas=[{"nombre": c, "tipo_inferido": tipos.get(c, "omitida (dato personal)"),
                                          "personal": c in res.personales_omitidas} for c in columnas],
            filas_muestra=muestra, mapeo=res.campos, faltantes_obligatorios=res.faltantes_obligatorios,
            campos_sin_columna=res.sin_columna, columnas_personales_omitidas=res.personales_omitidas,
            columnas_atributos=res.atributos, columnas_no_usadas=res.no_usadas, filas_estimadas=filas_estimadas,
            validacion=validacion, advertencias=advertencias)

    def _validar_muestra(self, tipo, primeras, res, hoja_mapeo) -> dict:
        cont = Contadores()
        validas = 0
        for numero, fila in primeras:
            if tipo == "siniestros":
                ok = transformar_siniestro(numero, fila, res, hoja_mapeo, self.hoy, cont) is not None
            elif tipo == "poblacion":
                ok = transformar_poblacion(numero, fila, res, cont) is not None
            else:
                ok = transformar_hijo(tipo, numero, fila, res, cont) is not None
            validas += ok
        return {"revisadas": len(primeras), "validas": validas, "rechazadas": len(primeras) - validas,
                "motivos": dict(cont.c), "ejemplos_error": cont.errores[:10],
                "nota": f"Validación de las primeras {len(primeras)} filas; el resultado final puede variar."}

    def _previsualizar_geo(self, recibido, info_archivo, usuario_id):
        if recibido.extension not in (".geojson", ".json"):
            raise ErrorImportacion("Para 'localidades' se espera un archivo .geojson.")
        resultado = geo_localidades.cargar_y_validar(recibido.ruta, self.tolerancia_geo)
        fuente = self.repo.obtener_fuente(CODIGO_FUENTE_LOCALIDADES)
        resumen_geo = resultado.resumen()
        importacion_id = self.repo.crear_importacion_archivo(
            fuente_id=fuente.id, modo="localidades", archivo=recibido.nombre, hoja=None,
            mapeo={"localidad": resultado.propiedad_localidad}, usuario_id=usuario_id,
            resumen={"archivo": info_archivo, "tipo": "localidades", "previsualizacion": resumen_geo})
        self.repo.confirmar()
        return Previsualizacion(
            importacion_id=importacion_id, archivo=recibido.nombre, tipo="localidades", hojas=[], hoja=None,
            columnas=[], filas_muestra=[{"localidad": k} for k in resultado.localidades],
            mapeo={"localidad": resultado.propiedad_localidad}, faltantes_obligatorios=[], campos_sin_columna=[],
            columnas_personales_omitidas=[], columnas_atributos=[], columnas_no_usadas=[],
            filas_estimadas=resultado.poligonos_originales,
            validacion={"revisadas": resultado.poligonos_originales, "validas": len(resultado.localidades),
                        "rechazadas": 0, "motivos": {}, **resumen_geo},
            advertencias=resultado.advertencias)

    # ------------------------------------------------------------------ cancelación
    def cancelar(self, importacion_id: int) -> None:
        imp = self._importacion(importacion_id)
        if imp["estado"] != "previsualizada":
            raise ErrorImportacion(f"Solo se cancela una importación previsualizada (estado actual: {imp['estado']}).")
        eliminar_recibido(self.directorio_cargas, imp["resumen"]["archivo"]["token"])
        self.repo.actualizar_importacion(importacion_id, estado="cancelada", finalizada_en=datetime.now(timezone.utc))
        self.repo.confirmar()

    def _importacion(self, importacion_id: int) -> dict:
        imp = self.repo.obtener_importacion(importacion_id)
        if imp is None or imp.get("tipo") != "excel":
            raise ErrorImportacion(f"No existe la importación de archivo n.º {importacion_id}.")
        return imp

    # ------------------------------------------------------------------ confirmación
    _CONFIRMABLES = ("previsualizada", "fallida")

    def _verificar_archivo(self, imp: dict) -> Path:
        archivo = (imp.get("resumen") or {})["archivo"]
        ruta = ruta_de_token(self.directorio_cargas, archivo["token"], archivo["nombre"])
        if not ruta.is_file():
            raise ErrorImportacion("El archivo de esta importación ya no está disponible; súbalo de nuevo.")
        if sha256_de(ruta) != archivo["sha256"]:
            raise ErrorImportacion("El archivo cambió después de la previsualización; súbalo de nuevo.")
        return ruta

    def reservar(self, importacion_id: int) -> dict:
        """Verifica y marca la importación 'en_proceso' de forma atómica (para procesarla en segundo plano).
        Si dos peticiones confirman a la vez, solo una la reserva."""
        imp = self._importacion(importacion_id)
        if imp["estado"] not in self._CONFIRMABLES:
            raise ErrorImportacion(f"La importación n.º {importacion_id} está '{imp['estado']}'; "
                                   "solo se confirma una previsualizada (o se reintenta una fallida).")
        self._verificar_archivo(imp)
        if not self.repo.reservar_importacion(importacion_id, self._CONFIRMABLES):
            raise ErrorImportacion(f"La importación n.º {importacion_id} ya se está procesando.")
        self.repo.confirmar()
        return imp

    def confirmar(self, importacion_id: int, *, metadatos_fuente: dict | None = None,
                  reservada: bool = False) -> ResultadoImportacion:
        imp = self._importacion(importacion_id)
        esperados = ("en_proceso",) if reservada else self._CONFIRMABLES
        if imp["estado"] not in esperados:
            raise ErrorImportacion(f"La importación n.º {importacion_id} está '{imp['estado']}'; "
                                   "solo se confirma una previsualizada (o se reintenta una fallida).")
        resumen = dict(imp.get("resumen") or {})
        archivo = resumen["archivo"]
        try:
            ruta = self._verificar_archivo(imp)
        except ErrorImportacion as exc:
            if reservada:  # ya estaba marcada en proceso: se deja constancia del fallo
                self.repo.actualizar_importacion(importacion_id, estado="fallida", errores=[str(exc)],
                                                 finalizada_en=datetime.now(timezone.utc))
                self.repo.confirmar()
            raise

        tipo = resumen["tipo"]
        resultado = ResultadoImportacion(importacion_id=importacion_id, estado="en_proceso", tipo=tipo)
        self.repo.actualizar_importacion(importacion_id, estado="en_proceso", filas_revisadas=0, filas_validas=0,
                                         filas_rechazadas=0)
        self.repo.confirmar()
        cont = Contadores()
        try:
            if tipo == "localidades":
                self._confirmar_geo(ruta, imp, resultado)
            else:
                mapeo = cargar_mapeo(resumen["mapeo_codigo"])
                hoja_mapeo = mapeo.hojas[tipo]
                lector = abrir_tabla(ruta)
                try:
                    res = resolver_columnas(hoja_mapeo, lector.columnas(imp["hoja"]), resumen.get("sobrescribir"))
                    if not res.completo:
                        raise ErrorImportacion("Faltan columnas obligatorias: " + ", ".join(res.faltantes_obligatorios)
                                               + ". Suba el archivo de nuevo indicando el mapeo.")
                    if res.campos != imp["mapeo"]:
                        raise ErrorImportacion("El mapeo de columnas ya no coincide con la previsualización.")
                    if tipo == "siniestros":
                        self._confirmar_siniestros(lector, imp, res, hoja_mapeo, cont, resultado)
                    elif tipo == "poblacion":
                        self._confirmar_poblacion(lector, imp, res, cont, resultado)
                    else:
                        self._confirmar_hijos(tipo, lector, imp, res, cont, resultado)
                finally:
                    lector.cerrar()
            if metadatos_fuente:
                self.repo.actualizar_fuente(imp["fuente_id"], **{k: v for k, v in metadatos_fuente.items()
                                                                 if k in ("url", "fecha_publicacion", "fecha_descarga")
                                                                 and v is not None})
            resultado.estado = "completada"
        except (ErrorImportacion, ErrorArchivo, ErrorMapeo, geo_localidades.ErrorGeo) as exc:
            self.repo.revertir()
            cont.error(str(exc))
            resultado.estado = "fallida"
            resultado.mensaje = f"La importación falló: {exc}"
        except Exception:
            self.repo.revertir()
            cont.error("Error interno inesperado durante la importación (ver registro del servidor).")
            resultado.estado = "fallida"
            resultado.mensaje = "Error interno inesperado durante la importación."
            self._finalizar(imp, resumen, resultado, cont)
            raise

        if resultado.estado == "completada":
            resultado.mensaje = resultado.mensaje or (
                f"Importación de {tipo} completada: {resultado.filas_revisadas} filas revisadas, "
                f"{resultado.filas_validas} válidas, {resultado.filas_rechazadas} rechazadas.")
            if not self.conservar_archivo:
                eliminar_recibido(self.directorio_cargas, archivo["token"])
        self._finalizar(imp, resumen, resultado, cont)
        return resultado

    def _finalizar(self, imp, resumen, resultado: ResultadoImportacion, cont: Contadores) -> None:
        resumen = dict(resumen)
        resumen["resultado"] = {**resultado.resumen, "calidad": dict(sorted(cont.c.items())),
                                "errores_totales": cont.errores_totales,
                                "nuevos": resultado.nuevos, "actualizados": resultado.actualizados}
        if cont.categorias:
            resumen["resultado"]["categorias_no_reconocidas"] = {
                g: dict(c.most_common(30)) for g, c in cont.categorias.items()}
        resultado.resumen = resumen["resultado"]
        self.repo.actualizar_importacion(
            imp["id"], estado=resultado.estado, finalizada_en=datetime.now(timezone.utc),
            filas_revisadas=resultado.filas_revisadas, filas_validas=resultado.filas_validas,
            filas_rechazadas=resultado.filas_rechazadas, errores=cont.errores or None, resumen=resumen,
            fecha_min_evento=resultado.fecha_min, fecha_max_evento=resultado.fecha_max)
        self.repo.confirmar()

    def _avance(self, imp, resultado: ResultadoImportacion) -> None:
        self.repo.actualizar_importacion(imp["id"], filas_revisadas=resultado.filas_revisadas,
                                         filas_validas=resultado.filas_validas,
                                         filas_rechazadas=resultado.filas_rechazadas)
        self.repo.confirmar()
        self._progreso(f"{resultado.filas_revisadas} filas revisadas, {resultado.filas_validas} válidas, "
                       f"{resultado.filas_rechazadas} rechazadas.")

    # ---------------------------------------------------------------- siniestros
    def _confirmar_siniestros(self, lector, imp, res, hoja_mapeo, cont, resultado) -> None:
        fuente_id = imp["fuente_id"]
        vistos: set[int] = set()
        fmin = fmax = None
        for bloque in lector.filas(imp["hoja"], bloque=self.bloque):
            registros = []
            for numero, fila in bloque:
                resultado.filas_revisadas += 1
                r = transformar_siniestro(numero, fila, res, hoja_mapeo, self.hoy, cont)
                if r is None:
                    resultado.filas_rechazadas += 1
                    continue
                if r.id_registro in vistos:
                    resultado.filas_rechazadas += 1
                    cont.sumar("duplicado.siniestro_en_archivo")
                    cont.error(f"Fila {numero}: el siniestro {r.id_registro} está repetido en el archivo; "
                               "se conserva la primera aparición.")
                    continue
                vistos.add(r.id_registro)
                registros.append(r)
                f = r.siniestro["fecha_evento"]
                fmin = f if fmin is None or f < fmin else fmin
                fmax = f if fmax is None or f > fmax else fmax
            nuevos, actualizados = self.repo.guardar_lote(fuente_id, imp["id"], registros, reemplazar_hijos=False)
            resultado.nuevos += nuevos
            resultado.actualizados += actualizados
            resultado.filas_validas += len(registros)
            self._avance(imp, resultado)

        sospechosas = calidad.detectar_coordenadas_sospechosas(
            self.repo.puntos_para_coherencia(fuente_id), percentil=self.coherencia_percentil,
            margen_grados=self.coherencia_margen)
        inicio, fin = self.repo.periodo_real(fuente_id)
        self.repo.actualizar_fuente(fuente_id, periodo_inicio=inicio, periodo_fin=fin)
        resultado.resumen.update({
            "coherencia_coordenadas": {"marcadas_sospechosas": self.repo.aplicar_coherencia(fuente_id, sospechosas),
                                       "percentil": self.coherencia_percentil, "margen_grados": self.coherencia_margen},
            "periodo_real_guardado": {"inicio": inicio.isoformat() if inicio else None,
                                      "fin": fin.isoformat() if fin else None},
            "coincidencias_otras_fuentes": self.repo.coincidencias_otras_fuentes(fuente_id),
        })
        resultado.fecha_min, resultado.fecha_max = fmin, fmax

    # ---------------------------------------------------------------- personas y vehículos
    def _confirmar_hijos(self, tipo, lector, imp, res, cont, resultado) -> None:
        fuente_id = imp["fuente_id"]
        limpiados: set[int] = set()
        claves_vistas: set[tuple] = set()
        huerfanos: Counter = Counter()
        for bloque in lector.filas(imp["hoja"], bloque=self.bloque):
            transformadas = []
            for numero, fila in bloque:
                resultado.filas_revisadas += 1
                t = transformar_hijo(tipo, numero, fila, res, cont)
                if t is None:
                    resultado.filas_rechazadas += 1
                    continue
                transformadas.append((numero, *t))
            mapa = self.repo.mapa_ids(fuente_id, sorted({t[1] for t in transformadas}))
            filas = []
            for numero, id_registro, hijo in transformadas:
                interno = mapa.get(id_registro)
                if interno is None:
                    resultado.filas_rechazadas += 1
                    huerfanos[id_registro] += 1
                    cont.sumar("rechazo.siniestro_no_importado")
                    if len(huerfanos) <= 20:
                        cont.error(f"Fila {numero}: el siniestro {id_registro} no existe en esta fuente; "
                                   "importe primero la hoja de siniestros.")
                    continue
                llave = ((interno, hijo["codigo_vehiculo"], hijo["consecutivo_victima"]) if tipo == "actores"
                         else (interno, hijo["codigo_vehiculo"]))
                if llave in claves_vistas:
                    resultado.filas_rechazadas += 1
                    cont.sumar(f"duplicado.{tipo}_en_archivo")
                    continue
                claves_vistas.add(llave)
                filas.append(dict(hijo, siniestro_id=interno))
            limpiar = sorted({f["siniestro_id"] for f in filas} - limpiados)
            self.repo.reemplazar_hijos(tipo, filas, limpiar)
            limpiados.update(limpiar)
            resultado.filas_validas += len(filas)
            self._avance(imp, resultado)
        resultado.resumen.update({
            "siniestros_con_filas_en_este_archivo": len(limpiados),
            "siniestros_de_la_fuente_sin_" + tipo: self.repo.siniestros_sin_hijos(fuente_id, tipo),
            "filas_de_siniestros_no_importados": sum(huerfanos.values()),
        })

    # ---------------------------------------------------------------- población
    def _confirmar_poblacion(self, lector, imp, res, cont, resultado) -> None:
        sumas: dict[tuple[str, int], int] = defaultdict(int)
        for bloque in lector.filas(imp["hoja"], bloque=self.bloque):
            for numero, fila in bloque:
                resultado.filas_revisadas += 1
                t = transformar_poblacion(numero, fila, res, cont)
                if t is None:
                    resultado.filas_rechazadas += 1
                    continue
                localidad, anio, poblacion = t
                sumas[(localidad, anio)] += poblacion
                resultado.filas_validas += 1
        if not sumas:
            raise ErrorImportacion("No quedó ninguna fila válida de población.")
        # Coherencia: la suma de las localidades debe ser igual al total de Bogotá del mismo año.
        diferencias = {}
        for anio in sorted({a for _, a in sumas}):
            total = sumas.get((CLAVE_TOTAL_BOGOTA, anio))
            suma_loc = sum(v for (loc, a), v in sumas.items() if a == anio and loc != CLAVE_TOTAL_BOGOTA)
            if total is not None and total != suma_loc:
                diferencias[str(anio)] = {"total_bogota": total, "suma_localidades": suma_loc}
        filas = [(loc, anio, pob) for (loc, anio), pob in sorted(sumas.items(), key=lambda kv: (kv[0][1], kv[0][0]))
                 if pob > 0]
        nuevos, actualizados = self.repo.upsert_denominadores(imp["fuente_id"], filas)
        resultado.nuevos, resultado.actualizados = nuevos, actualizados
        anios = sorted({a for _, a in sumas})
        anio_actual = self.hoy.year
        resultado.resumen.update({
            "denominadores_guardados": len(filas),
            "anios": [anios[0], anios[-1]],
            "localidades": sorted({loc for loc, _ in sumas}),
            "anios_proyectados": [a for a in anios if a > anio_actual],
            "nota_proyecciones": f"Los años posteriores a {anio_actual} son proyecciones del archivo, no conteos.",
            "suma_localidades_distinta_del_total": diferencias,
        })
        self.repo.actualizar_fuente(imp["fuente_id"], periodo_inicio=date(anios[0], 1, 1),
                                    periodo_fin=date(anios[-1], 12, 31))
        self._avance(imp, resultado)

    # ---------------------------------------------------------------- localidades
    def _confirmar_geo(self, ruta, imp, resultado) -> None:
        r = geo_localidades.cargar_y_validar(ruta, self.tolerancia_geo)
        destino = geo_localidades.guardar(r.coleccion, self.directorio_geo)
        resultado.filas_revisadas = r.poligonos_originales
        resultado.filas_validas = len(r.localidades)
        resultado.resumen.update({**r.resumen(), "archivo_publicado": destino.name})


def _a_texto(valor: object) -> object:
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    return valor
