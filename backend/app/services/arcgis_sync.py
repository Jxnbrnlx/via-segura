"""Sincronización de la fuente principal (ArcGIS SIMUR) con la base de datos.

Flujo de una sincronización:
1. Verifica que el servicio responda y que existan los campos esperados (si cambió el esquema,
   se detiene con un mensaje claro en lugar de importar datos incompletos).
2. Calcula el filtro: completa (todo, o desde un año) o incremental (relee una ventana de
   ARCGIS_VENTANA_DIAS hacia atrás desde la fecha máxima guardada, porque las muertes
   posteriores y las correcciones cambian registros ya publicados).
3. Recorre la capa 2 (ACCIDENTE) en páginas de hasta 2000 ordenadas por OBJECTID. Por cada página
   pide a las tablas 3, 5 y 4 las filas relacionadas por FORMULARIO (clave de las relaciones
   publicadas en el servicio), normaliza y guarda con upsert por (fuente_id, id_registro),
   reemplazando personas, vehículos y causas del siniestro. Confirma (commit) página a página.
4. Al terminar: periodo real (mín./máx.) de la fuente, revisión de coherencia de coordenadas,
   coincidencias con otras fuentes y registros guardados que ya no aparecen en el servicio
   (se informan, NO se borran).
5. Si el servicio falla: la importación queda "fallida" con un error legible y se conservan los
   datos guardados previamente.

Este módulo no importa SQLAlchemy: trabaja contra un `Repositorio` (ver repositorio_sql.py), lo
que permite probar la lógica completa con un repositorio en memoria.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

from . import calidad
from .arcgis_client import (
    CAMPOS_ACCIDENTE, CAMPOS_ACTOR_VIAL, CAMPOS_CAUSA, CAMPOS_VEHICULO, CAPA_ACCIDENTE, TABLA_ACTOR_VIAL,
    TABLA_CAUSA, TABLA_VEHICULO, ClienteArcGIS, ErrorArcGIS, sql_lista_texto,
)

log = logging.getLogger("via_segura.sync")

CODIGO_FUENTE_ARCGIS = "arcgis_simur_accidentalidad"
MAX_ERRORES_GUARDADOS = 200
MAX_EJEMPLOS = 20
_FORMULARIO_VALIDO = re.compile(r"^[A-Za-z0-9_-]{1,20}$")

# Campo lógico -> nombre ORIGINAL en el servicio (se guarda en importaciones.mapeo).
MAPEO_ARCGIS = {
    "id_registro": "CODIGO_ACCIDENTE (capa 2)",
    "formulario": "FORMULARIO (capa 2; clave de relación con tablas 3, 4 y 5)",
    "fecha_evento": "FECHA_OCURRENCIA_ACC (epoch ms, medianoche UTC = fecha local)",
    "anio / mes / dia_semana": "derivados de fecha_evento (se contrastan con ANO_/MES_/DIA_OCURRENCIA_ACC)",
    "hora / minuto": "HORA_OCURRENCIA_ACC (texto HH:MM:SS)",
    "localidad": "LOCALIDAD",
    "direccion": "DIRECCION",
    "barrio": "BARRIO",
    "via_nombre": "MVINOMBRE",
    "clase_siniestro": "CLASE_ACC",
    "gravedad": "GRAVEDAD",
    "latitud / longitud": "LATITUD / LONGITUD",
    "actores_viales": "tabla 3 VM_ACC_ACTOR_VIAL: CODIGO_VICTIMA, CODIGO_VEHICULO, CONDICION, CONDICION_A, "
                      "ESTADO, MUERTE_POSTERIOR, GENERO, EDAD",
    "vehiculos_evento": "tabla 5 VM_ACC_VEHICULO: CODIGO_VEHICULO, CLASE, SERVICIO, MODALIDAD",
    "causas_evento": "tabla 4 VM_ACC_CAUSA: CODIGO_VEHICULO, CODIGO_CAUSA, NOMBRE, TIPO_CAUSA",
    "no_importados": "PLACA, FECHA_NACIMIENTO, CODIGO_ACCIDENTADO (datos personales)",
}

# Largo máximo de cada columna de texto (igual que models.py).
_LARGO = {
    "formulario": 20, "localidad": 60, "direccion": 150, "barrio": 255, "via_nombre": 255,
    "clase_siniestro": 40, "condicion": 60, "condicion_especifica": 80, "sexo": 20,
    "clase": 40, "servicio": 40, "modalidad": 60, "codigo_causa": 15, "nombre": 80, "tipo_causa": 200,
}


# =====================================================================================
# Estructuras
# =====================================================================================

@dataclass
class RegistroSiniestro:
    """Un siniestro normalizado listo para guardar, con sus filas hijas."""

    siniestro: dict
    actores: list[dict] = field(default_factory=list)
    vehiculos: list[dict] = field(default_factory=list)
    causas: list[dict] = field(default_factory=list)

    @property
    def id_registro(self) -> int:
        return self.siniestro["id_registro"]

    @property
    def formulario(self) -> str | None:
        return self.siniestro.get("formulario")


@dataclass
class FuenteInfo:
    id: int
    codigo: str
    prioridad: int


@dataclass
class ResultadoSync:
    importacion_id: int | None
    estado: str  # completada | fallida
    modo: str
    filas_revisadas: int = 0
    filas_validas: int = 0
    filas_rechazadas: int = 0
    nuevos: int = 0
    actualizados: int = 0
    fecha_min: date | None = None
    fecha_max: date | None = None
    mensaje: str = ""
    resumen: dict = field(default_factory=dict)


class Repositorio(Protocol):
    """Operaciones de persistencia que necesita la sincronización."""

    def obtener_fuente(self, codigo: str) -> FuenteInfo: ...
    def crear_importacion(self, fuente_id: int, modo: str, usuario_id: int | None, mapeo: dict) -> int: ...
    def actualizar_importacion(self, importacion_id: int, **campos) -> None: ...
    def fecha_maxima(self, fuente_id: int) -> date | None: ...
    def periodo_real(self, fuente_id: int) -> tuple[date | None, date | None]: ...
    def contar_registros(self, fuente_id: int) -> int: ...
    def guardar_lote(self, fuente_id: int, importacion_id: int, registros: list[RegistroSiniestro],
                     reemplazar_hijos: bool = True) -> tuple[int, int]: ...
    def ids_desde(self, fuente_id: int, desde: date | None) -> set[int]: ...
    def puntos_para_coherencia(self, fuente_id: int) -> Iterable[tuple[int, str | None, float, float]]: ...
    def aplicar_coherencia(self, fuente_id: int, sospechosas: set[int]) -> int: ...
    def coincidencias_otras_fuentes(self, fuente_id: int) -> list[dict]: ...
    def actualizar_fuente(self, fuente_id: int, **campos) -> None: ...
    def confirmar(self) -> None: ...
    def revertir(self) -> None: ...


class Contadores:
    """Acumula banderas de calidad sin guardar datos personales."""

    def __init__(self) -> None:
        self.c: Counter = Counter()
        self.categorias: dict[str, Counter] = {}
        self.errores: list[str] = []
        self.errores_totales = 0

    def sumar(self, clave: str, n: int = 1) -> None:
        self.c[clave] += n

    def categoria(self, grupo: str, valor: object) -> None:
        self.categorias.setdefault(grupo, Counter())[str(valor)] += 1

    def error(self, mensaje: str) -> None:
        self.errores_totales += 1
        if len(self.errores) < MAX_ERRORES_GUARDADOS:
            self.errores.append(mensaje)


# =====================================================================================
# Transformación (pura)
# =====================================================================================

def _texto(valor: object, columna: str, cont: Contadores) -> str | None:
    texto, recortado = calidad.recortar(calidad.limpiar_texto(valor), _LARGO[columna])
    if recortado:
        cont.sumar(f"texto_recortado.{columna}")
    return texto


def transformar_accidente(atributos: dict, hoy: date, cont: Contadores) -> RegistroSiniestro | None:
    """Capa 2 -> siniestro normalizado. Devuelve None (y anota el motivo) si no se puede guardar."""
    id_registro = calidad.convertir_entero(atributos.get("CODIGO_ACCIDENTE"))
    if id_registro is None or id_registro <= 0:
        cont.sumar("rechazo.sin_codigo_accidente")
        cont.error(f"Registro OBJECTID={atributos.get('OBJECTID')}: CODIGO_ACCIDENTE vacío o no entero.")
        return None

    fecha = calidad.fecha_desde_epoch_ms(atributos.get("FECHA_OCURRENCIA_ACC"))
    if fecha is None:
        cont.sumar("rechazo.sin_fecha")
        cont.error(f"Siniestro {id_registro}: sin FECHA_OCURRENCIA_ACC.")
        return None
    if fecha > hoy:
        cont.sumar("rechazo.fecha_futura")
        cont.error(f"Siniestro {id_registro}: fecha {fecha.isoformat()} posterior a hoy; no se importa.")
        return None

    try:
        gravedad = calidad.normalizar_gravedad(atributos.get("GRAVEDAD"))
    except calidad.ValorNoReconocido:
        cont.sumar("rechazo.gravedad_no_reconocida")
        cont.categoria("gravedad_no_reconocida", atributos.get("GRAVEDAD"))
        cont.error(f"Siniestro {id_registro}: GRAVEDAD no reconocida {atributos.get('GRAVEDAD')!r}.")
        return None
    if gravedad is None:
        cont.sumar("gravedad_vacia")

    atributos_extra: dict = {}

    try:
        localidad = calidad.normalizar_localidad(atributos.get("LOCALIDAD"))
    except calidad.ValorNoReconocido:
        localidad = None
        atributos_extra["localidad_original"] = calidad.limpiar_texto(atributos.get("LOCALIDAD"))
        cont.categoria("localidad_no_reconocida", atributos.get("LOCALIDAD"))
    if localidad is None:
        cont.sumar("localidad_vacia_o_no_reconocida")

    clase, reconocida = calidad.normalizar_clase(atributos.get("CLASE_ACC"))
    if not reconocida:
        cont.categoria("clase_no_reconocida", clase)
    clase, recortada = calidad.recortar(clase, _LARGO["clase_siniestro"])
    if recortada:
        cont.sumar("texto_recortado.clase_siniestro")

    hora, minuto = calidad.hora_desde_texto(atributos.get("HORA_OCURRENCIA_ACC"))
    if hora is None:
        cont.sumar("hora_vacia_o_invalida")

    coordenada = calidad.validar_coordenada(atributos.get("LATITUD"), atributos.get("LONGITUD"))
    if not coordenada.valida:
        cont.sumar(f"coordenada.{coordenada.motivo}")

    # Contraste con los campos derivados que publica la fuente (no se usan: se calculan de la fecha).
    anio_fuente = calidad.convertir_entero(atributos.get("ANO_OCURRENCIA_ACC"))
    if anio_fuente is not None and anio_fuente != fecha.year:
        cont.sumar("discrepancia.anio")
    dia_fuente = calidad.clave(atributos.get("DIA_OCURRENCIA_ACC"))
    dia_calculado = calidad.dia_semana(fecha)
    if dia_fuente and dia_fuente != calidad.clave(dia_calculado):
        cont.sumar("discrepancia.dia_semana")
    mes_fuente = calidad.clave(atributos.get("MES_OCURRENCIA_ACC"))
    if mes_fuente and mes_fuente != calidad.clave(calidad.MESES[fecha.month - 1]):
        cont.sumar("discrepancia.mes")

    for origen, destino in (("CIV", "civ"), ("PK_CALZADA", "pk_calzada")):
        valor = calidad.convertir_entero(atributos.get(origen))
        if valor is not None:
            atributos_extra[destino] = valor
    municipio = calidad.clave(atributos.get("MUNICIPIO"))
    if municipio and municipio not in ("BOGOTA DC", "BOGOTA D.C.", "BOGOTA"):
        atributos_extra["municipio"] = municipio
        cont.categoria("municipio_distinto", municipio)

    formulario = _texto(atributos.get("FORMULARIO"), "formulario", cont)

    return RegistroSiniestro(siniestro={
        "id_registro": id_registro,
        "formulario": formulario,
        "fecha_evento": fecha,
        "anio": fecha.year,
        "mes": fecha.month,
        "dia_semana": dia_calculado,
        "hora": hora,
        "minuto": minuto,
        "localidad": localidad,
        "direccion": _texto(atributos.get("DIRECCION"), "direccion", cont),
        "barrio": _texto(atributos.get("BARRIO"), "barrio", cont),
        "via_nombre": _texto(atributos.get("MVINOMBRE"), "via_nombre", cont),
        "clase_siniestro": clase,
        "gravedad": gravedad,
        "gravedad_tradicional": None,  # no existe en ArcGIS
        "latitud": coordenada.latitud,
        "longitud": coordenada.longitud,
        "coordenada_valida": coordenada.valida,
        "motivo_coordenada": coordenada.motivo,
        "atributos": atributos_extra or None,
    })


def transformar_actor(atributos: dict, cont: Contadores) -> dict | None:
    """Tabla 3 -> persona. No se solicita ni se guarda CODIGO_ACCIDENTADO ni FECHA_NACIMIENTO."""
    consecutivo = calidad.convertir_entero(atributos.get("CODIGO_VICTIMA"))
    if consecutivo is None:
        cont.sumar("actor.rechazo_sin_codigo_victima")
        return None
    try:
        estado = calidad.normalizar_estado_persona(atributos.get("ESTADO"))
    except calidad.ValorNoReconocido:
        estado = None
        cont.categoria("actor.estado_no_reconocido", atributos.get("ESTADO"))
    try:
        sexo = calidad.normalizar_sexo(atributos.get("GENERO"))
    except calidad.ValorNoReconocido:
        sexo = None
        cont.categoria("actor.sexo_no_reconocido", atributos.get("GENERO"))
    edad_original = calidad.convertir_numero(atributos.get("EDAD"))
    edad = calidad.normalizar_edad(edad_original)
    if edad_original is not None and edad is None:
        cont.sumar("actor.edad_atipica_a_null")
    codigo_vehiculo = calidad.convertir_entero(atributos.get("CODIGO_VEHICULO"))
    if codigo_vehiculo is None:
        cont.sumar("actor.sin_codigo_vehiculo")
    condicion, rec1 = calidad.recortar(calidad.normalizar_categoria(atributos.get("CONDICION")), _LARGO["condicion"])
    especifica, rec2 = calidad.recortar(calidad.normalizar_categoria(atributos.get("CONDICION_A")),
                                        _LARGO["condicion_especifica"])
    if rec1 or rec2:
        cont.sumar("texto_recortado.condicion")
    return {
        "codigo_vehiculo": codigo_vehiculo,
        "consecutivo_victima": consecutivo,
        "estado": estado,
        "condicion": condicion,
        "condicion_especifica": especifica,
        "sexo": sexo,
        "edad": edad,
        "rango_edad": calidad.rango_edad(edad),
        "muerte_posterior": calidad.normalizar_si_no(atributos.get("MUERTE_POSTERIOR")),
    }


def transformar_vehiculo(atributos: dict, cont: Contadores) -> dict | None:
    """Tabla 5 -> vehículo. La PLACA no se solicita ni se guarda."""
    codigo = calidad.convertir_entero(atributos.get("CODIGO_VEHICULO"))
    if codigo is None:
        cont.sumar("vehiculo.rechazo_sin_codigo_vehiculo")
        return None
    salida = {"codigo_vehiculo": codigo}
    for origen, destino in (("CLASE", "clase"), ("SERVICIO", "servicio"), ("MODALIDAD", "modalidad")):
        valor, recortado = calidad.recortar(calidad.normalizar_categoria(atributos.get(origen)), _LARGO[destino])
        if recortado:
            cont.sumar(f"texto_recortado.vehiculo_{destino}")
        salida[destino] = valor
    return salida


def transformar_causa(atributos: dict, cont: Contadores) -> dict | None:
    codigo_causa = _texto(atributos.get("CODIGO_CAUSA"), "codigo_causa", cont)
    if codigo_causa is None:
        cont.sumar("causa.rechazo_sin_codigo")
        return None
    return {
        "codigo_vehiculo": calidad.convertir_entero(atributos.get("CODIGO_VEHICULO")),
        "codigo_causa": codigo_causa,
        "nombre": _texto(atributos.get("NOMBRE"), "nombre", cont),
        "tipo_causa": _texto(atributos.get("TIPO_CAUSA"), "tipo_causa", cont),
    }


def _sin_duplicados(filas: list[dict], llave: Callable[[dict], tuple], etiqueta: str, cont: Contadores) -> list[dict]:
    vistas, salida = set(), []
    for fila in filas:
        k = llave(fila)
        if k in vistas:
            cont.sumar(f"duplicado.{etiqueta}")
            continue
        vistas.add(k)
        salida.append(fila)
    return salida


def _prefijo_codigo(valor: object) -> int | None:
    """'11237188-2' (CODIGO de la tabla 3) -> 11237188 (CODIGO_ACCIDENTE)."""
    texto = calidad.limpiar_texto(valor)
    if not texto:
        return None
    return calidad.convertir_entero(texto.split("-", 1)[0])


# =====================================================================================
# Orquestación
# =====================================================================================

class SincronizadorArcGIS:
    def __init__(
        self,
        cliente: ClienteArcGIS,
        repositorio: Repositorio,
        *,
        ventana_dias: int = 90,
        lote_formularios: int = 500,
        coherencia_percentil: float = 0.001,
        coherencia_margen: float = 0.03,
        hoy: date | None = None,
        progreso: Callable[[str], None] | None = None,
    ):
        self.cliente = cliente
        self.repo = repositorio
        self.ventana_dias = ventana_dias
        self.lote_formularios = max(1, lote_formularios)
        self.coherencia_percentil = coherencia_percentil
        self.coherencia_margen = coherencia_margen
        self.hoy = hoy or calidad.hoy_bogota()
        self._progreso = progreso or (lambda _m: None)

    # ------------------------------------------------------------------ utilidades
    def _avisar(self, mensaje: str) -> None:
        log.info(mensaje)
        self._progreso(mensaje)

    def verificar_esquema(self) -> dict[int, dict[str, str]]:
        """Comprueba que el servicio responde y que existen todos los campos que se solicitan."""
        esquema: dict[int, dict[str, str]] = {}
        faltantes: list[str] = []
        for capa, campos in ((CAPA_ACCIDENTE, CAMPOS_ACCIDENTE), (TABLA_ACTOR_VIAL, CAMPOS_ACTOR_VIAL),
                             (TABLA_VEHICULO, CAMPOS_VEHICULO), (TABLA_CAUSA, CAMPOS_CAUSA)):
            disponibles = self.cliente.campos_de(capa)
            esquema[capa] = disponibles
            faltantes += [f"{capa}.{c}" for c in campos if c not in disponibles]
        if faltantes:
            raise ErrorArcGIS("El esquema del servicio cambió: faltan los campos " + ", ".join(faltantes)
                              + ". No se importa nada para no guardar datos incompletos.")
        return esquema

    def _relacionadas(self, capa: int, campos: tuple[str, ...], formularios: list[str]) -> dict[str, list[dict]]:
        agrupadas: dict[str, list[dict]] = {}
        for i in range(0, len(formularios), self.lote_formularios):
            bloque = formularios[i:i + self.lote_formularios]
            where = f"FORMULARIO IN {sql_lista_texto(bloque)}"
            for fila in self.cliente.consultar_todo(capa, where, campos):
                agrupadas.setdefault(str(fila.get("FORMULARIO")), []).append(fila)
        return agrupadas

    def _completar_hijos(self, registros: list[RegistroSiniestro], cont: Contadores) -> None:
        por_formulario: dict[str, RegistroSiniestro] = {}
        for r in registros:
            f = r.formulario
            if f is None or not _FORMULARIO_VALIDO.match(f):
                cont.sumar("relacion.formulario_invalido_sin_hijos")
                continue
            if f in por_formulario:
                cont.sumar("relacion.formulario_repetido")
                cont.error(f"FORMULARIO repetido en siniestros {por_formulario[f].id_registro} y "
                           f"{r.id_registro}; los registros relacionados se asignan solo al primero.")
                continue
            por_formulario[f] = r
        if not por_formulario:
            return
        formularios = list(por_formulario)

        for f, filas in self._relacionadas(TABLA_ACTOR_VIAL, CAMPOS_ACTOR_VIAL, formularios).items():
            r = por_formulario.get(f)
            if r is None:
                continue
            actores = []
            for fila in filas:
                prefijo = _prefijo_codigo(fila.get("CODIGO"))
                if prefijo is not None and prefijo != r.id_registro:
                    cont.sumar("relacion.actor_codigo_no_coincide")
                actor = transformar_actor(fila, cont)
                if actor:
                    actores.append(actor)
            r.actores = _sin_duplicados(actores, lambda a: (a["codigo_vehiculo"], a["consecutivo_victima"]),
                                        "actor", cont)

        for f, filas in self._relacionadas(TABLA_VEHICULO, CAMPOS_VEHICULO, formularios).items():
            r = por_formulario.get(f)
            if r is None:
                continue
            vehiculos = [v for v in (transformar_vehiculo(fila, cont) for fila in filas) if v]
            r.vehiculos = _sin_duplicados(vehiculos, lambda v: (v["codigo_vehiculo"],), "vehiculo", cont)

        for f, filas in self._relacionadas(TABLA_CAUSA, CAMPOS_CAUSA, formularios).items():
            r = por_formulario.get(f)
            if r is None:
                continue
            causas = []
            for fila in filas:
                codigo_acc = calidad.convertir_entero(fila.get("CODIGO_ACCIDENTE"))
                if codigo_acc is not None and codigo_acc != r.id_registro:
                    cont.sumar("relacion.causa_codigo_no_coincide")
                causa = transformar_causa(fila, cont)
                if causa:
                    causas.append(causa)
            # VM_ACC_CAUSA trae filas idénticas repetidas (verificado): se guardan una sola vez.
            r.causas = _sin_duplicados(causas, lambda c: (c["codigo_vehiculo"], c["codigo_causa"]), "causa", cont)

        for r in registros:
            if not r.actores:
                cont.sumar("relacion.siniestro_sin_actores")

    # ------------------------------------------------------------------ ejecución
    def ejecutar(
        self,
        modo: str = "incremental",
        *,
        desde_anio: int | None = None,
        max_paginas: int | None = None,
        usuario_id: int | None = None,
    ) -> ResultadoSync:
        if modo not in ("completa", "incremental"):
            raise ValueError("modo debe ser 'completa' o 'incremental'")

        fuente = self.repo.obtener_fuente(CODIGO_FUENTE_ARCGIS)
        importacion_id = self.repo.crear_importacion(fuente.id, modo, usuario_id, MAPEO_ARCGIS)
        self.repo.confirmar()

        cont = Contadores()
        resultado = ResultadoSync(importacion_id=importacion_id, estado="en_proceso", modo=modo)
        resumen: dict = {"modo_solicitado": modo, "fuente": fuente.codigo}
        vistos: set[int] = set()
        fecha_min: date | None = None
        fecha_max: date | None = None
        paginas = 0
        parcial = False

        try:
            # 1. Verificación previa
            self.verificar_esquema()
            resumen["fecha_mas_reciente_en_servicio"] = _fecha_iso(
                self.cliente.valor_extremo(CAPA_ACCIDENTE, "FECHA_OCURRENCIA_ACC", maximo=True))

            # 2. Filtro
            desde: date | None = None
            modo_efectivo = modo
            if modo == "incremental":
                ultima = self.repo.fecha_maxima(fuente.id)
                if ultima is None:
                    modo_efectivo = "completa"
                    resumen["nota"] = "No había datos guardados de esta fuente: se ejecutó una carga completa."
                else:
                    desde = ultima - timedelta(days=self.ventana_dias)
                    resumen["ventana"] = {"fecha_maxima_guardada": ultima.isoformat(),
                                          "dias": self.ventana_dias, "desde": desde.isoformat()}
            if modo_efectivo == "completa" and desde_anio:
                desde = date(desde_anio, 1, 1)
            where = f"FECHA_OCURRENCIA_ACC >= DATE '{desde.isoformat()}'" if desde else "1=1"
            resumen["modo_efectivo"] = modo_efectivo
            resumen["filtro"] = where
            resultado.modo = modo_efectivo

            total = self.cliente.contar(CAPA_ACCIDENTE, where)
            resumen["registros_en_servicio_para_el_filtro"] = total
            self._avisar(f"Registros a revisar en el servicio: {total}")

            # 3. Páginas
            for pagina in self.cliente.iterar_paginas(CAPA_ACCIDENTE, where, CAMPOS_ACCIDENTE):
                paginas += 1
                registros: list[RegistroSiniestro] = []
                for atributos in pagina:
                    resultado.filas_revisadas += 1
                    registro = transformar_accidente(atributos, self.hoy, cont)
                    if registro is None:
                        resultado.filas_rechazadas += 1
                        continue
                    if registro.id_registro in vistos:
                        cont.sumar("duplicado.siniestro_en_servicio")
                        cont.error(f"CODIGO_ACCIDENTE {registro.id_registro} repetido en el servicio; "
                                   "se conserva la primera aparición.")
                        resultado.filas_rechazadas += 1
                        continue
                    vistos.add(registro.id_registro)
                    registros.append(registro)

                self._completar_hijos(registros, cont)
                nuevos, actualizados = self.repo.guardar_lote(fuente.id, importacion_id, registros)
                resultado.nuevos += nuevos
                resultado.actualizados += actualizados
                resultado.filas_validas += len(registros)
                for r in registros:
                    f = r.siniestro["fecha_evento"]
                    fecha_min = f if fecha_min is None or f < fecha_min else fecha_min
                    fecha_max = f if fecha_max is None or f > fecha_max else fecha_max
                cont.sumar("actores_guardados", sum(len(r.actores) for r in registros))
                cont.sumar("vehiculos_guardados", sum(len(r.vehiculos) for r in registros))
                cont.sumar("causas_guardadas", sum(len(r.causas) for r in registros))
                self.repo.actualizar_importacion(
                    importacion_id, filas_revisadas=resultado.filas_revisadas,
                    filas_validas=resultado.filas_validas, filas_rechazadas=resultado.filas_rechazadas)
                self.repo.confirmar()
                self._avisar(f"Página {paginas}: {resultado.filas_revisadas}/{total} revisados, "
                             f"{resultado.filas_validas} guardados, {resultado.filas_rechazadas} rechazados.")
                if max_paginas and paginas >= max_paginas:
                    parcial = True
                    break

            # 4. Cierre
            resumen["paginas"] = paginas
            resumen["peticiones_http"] = self.cliente.peticiones
            resumen["parcial"] = parcial
            if parcial:
                resumen["nota_parcial"] = f"Se detuvo tras {paginas} páginas por --max-paginas: la carga está incompleta."
            elif resultado.filas_revisadas < total:
                resumen["advertencia_conteo"] = (f"El servicio informó {total} registros y se leyeron "
                                                 f"{resultado.filas_revisadas}; pudo cambiar durante la lectura.")

            if not parcial:
                ausentes = self.repo.ids_desde(fuente.id, desde) - vistos
                resumen["guardados_que_ya_no_aparecen_en_el_servicio"] = {
                    "cantidad": len(ausentes),
                    "ejemplos_id_registro": sorted(ausentes)[:MAX_EJEMPLOS],
                    "accion": "ninguna (no se borran automáticamente; revisar manualmente)",
                }

            sospechosas = calidad.detectar_coordenadas_sospechosas(
                self.repo.puntos_para_coherencia(fuente.id),
                percentil=self.coherencia_percentil, margen_grados=self.coherencia_margen)
            resumen["coherencia_coordenadas"] = {
                "metodo": "caja por localidad entre percentiles, ampliada (heurística; sin polígonos oficiales)",
                "percentil": self.coherencia_percentil, "margen_grados": self.coherencia_margen,
                "marcadas_sospechosas": self.repo.aplicar_coherencia(fuente.id, sospechosas),
            }

            inicio, fin = self.repo.periodo_real(fuente.id)
            self.repo.actualizar_fuente(fuente.id, periodo_inicio=inicio, periodo_fin=fin,
                                        fecha_descarga=datetime.now(timezone.utc))
            resumen["periodo_real_guardado"] = {"inicio": _iso(inicio), "fin": _iso(fin)}
            resumen["coincidencias_otras_fuentes"] = self.repo.coincidencias_otras_fuentes(fuente.id)

            resultado.estado = "completada"
            resultado.fecha_min, resultado.fecha_max = fecha_min, fecha_max
            resultado.mensaje = (
                f"Sincronización {modo_efectivo} {'PARCIAL ' if parcial else ''}terminada: "
                f"{resultado.filas_revisadas} revisados, {resultado.nuevos} nuevos, "
                f"{resultado.actualizados} actualizados, {resultado.filas_rechazadas} rechazados. "
                f"Periodo guardado: {_iso(inicio)} a {_iso(fin)}.")
            self._finalizar(resultado, resumen, cont)
            return resultado

        except ErrorArcGIS as exc:
            self.repo.revertir()
            guardados = self.repo.contar_registros(fuente.id)
            inicio, fin = self.repo.periodo_real(fuente.id)
            cont.error(exc.mensaje)
            for detalle in exc.detalles:
                cont.error(f"Detalle ArcGIS: {detalle}")
            resumen.update({"paginas": paginas, "peticiones_http": self.cliente.peticiones,
                            "registros_conservados": guardados,
                            "periodo_conservado": {"inicio": _iso(inicio), "fin": _iso(fin)}})
            resultado.estado = "fallida"
            resultado.fecha_min, resultado.fecha_max = fecha_min, fecha_max
            resultado.mensaje = (
                f"No fue posible completar la sincronización con ArcGIS: {exc.mensaje} "
                + (f"Se conservan {guardados} registros guardados (periodo {_iso(inicio)} a {_iso(fin)}); "
                   f"de ellos, {resultado.filas_validas} se leyeron en esta ejecución antes del fallo."
                   if guardados else "No hay datos guardados de esta fuente."))
            self._finalizar(resultado, resumen, cont)
            return resultado

        except Exception:
            self.repo.revertir()
            cont.error("Error interno inesperado durante la sincronización (ver registro del servidor).")
            resultado.estado = "fallida"
            resultado.mensaje = "Error interno inesperado durante la sincronización."
            resumen.update({"paginas": paginas})
            self._finalizar(resultado, resumen, cont)
            raise

    def _finalizar(self, resultado: ResultadoSync, resumen: dict, cont: Contadores) -> None:
        resumen["calidad"] = dict(sorted(cont.c.items()))
        if cont.categorias:
            resumen["categorias_no_reconocidas"] = {
                grupo: dict(contador.most_common(30)) for grupo, contador in cont.categorias.items()}
        resumen["errores_totales"] = cont.errores_totales
        resumen["nuevos"] = resultado.nuevos
        resumen["actualizados"] = resultado.actualizados
        resultado.resumen = resumen
        self.repo.actualizar_importacion(
            resultado.importacion_id,
            estado=resultado.estado,
            finalizada_en=datetime.now(timezone.utc),
            filas_revisadas=resultado.filas_revisadas,
            filas_validas=resultado.filas_validas,
            filas_rechazadas=resultado.filas_rechazadas,
            fecha_min_evento=resultado.fecha_min,
            fecha_max_evento=resultado.fecha_max,
            errores=cont.errores or None,
            resumen=resumen,
        )
        self.repo.confirmar()


def _iso(valor: date | None) -> str | None:
    return valor.isoformat() if valor else None


def _fecha_iso(ms: object) -> str | None:
    return _iso(calidad.fecha_desde_epoch_ms(ms))
