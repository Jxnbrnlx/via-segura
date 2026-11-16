"""Persistencia de la sincronización con SQLAlchemy 2 (PostgreSQL o SQLite).

Implementa el protocolo `Repositorio` de arcgis_sync.py. Las escrituras son masivas (bulk) por
página para que una carga completa (cientos de miles de siniestros) sea viable.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime, timezone

from sqlalchemy import case, delete, func, insert, or_, select, update
from sqlalchemy.orm import Session, aliased

from .. import models
from ..seed_fuentes import FUENTES_INICIALES, ficha_fuente
from .arcgis_sync import FuenteInfo, RegistroSiniestro

SE = models.SiniestroEvento
_BLOQUE = 500  # elementos por cláusula IN (seguro para SQLite y PostgreSQL)
_SIN_SINCRONIZAR = {"synchronize_session": False}


def _bloques(secuencia: Sequence, tamano: int = _BLOQUE) -> Iterable[Sequence]:
    for i in range(0, len(secuencia), tamano):
        yield secuencia[i:i + tamano]


def asegurar_fuente(sesion: Session, codigo: str) -> models.FuenteDatos:
    """Devuelve la fila de la fuente; si no existe la crea con la ficha de seed_fuentes.py.
    El periodo NO se inventa: queda vacío hasta que una importación calcule el mín./máx. real."""
    fuente = sesion.scalar(select(models.FuenteDatos).where(models.FuenteDatos.codigo == codigo))
    if fuente is not None:
        return fuente
    ficha = ficha_fuente(codigo)
    if ficha is None:
        raise LookupError(f"No hay ficha para la fuente '{codigo}' en seed_fuentes.py")
    fuente = models.FuenteDatos(**ficha)
    sesion.add(fuente)
    sesion.flush()
    return fuente


def sembrar_fuentes(sesion: Session) -> int:
    """Crea las fichas que falten. Devuelve cuántas creó."""
    existentes = set(sesion.scalars(select(models.FuenteDatos.codigo)))
    creadas = 0
    for ficha in FUENTES_INICIALES:
        if ficha["codigo"] not in existentes:
            sesion.add(models.FuenteDatos(**ficha))
            creadas += 1
    sesion.flush()
    return creadas


class RepositorioSQL:
    def __init__(self, sesion: Session):
        self.s = sesion

    # ------------------------------------------------------------------ fuente e importación
    def obtener_fuente(self, codigo: str) -> FuenteInfo:
        fuente = asegurar_fuente(self.s, codigo)
        return FuenteInfo(id=fuente.id, codigo=fuente.codigo, prioridad=fuente.prioridad)

    def crear_importacion(self, fuente_id: int, modo: str, usuario_id: int | None, mapeo: dict) -> int:
        importacion = models.Importacion(fuente_id=fuente_id, usuario_id=usuario_id, tipo="arcgis", modo=modo,
                                         estado="en_proceso", mapeo=mapeo)
        self.s.add(importacion)
        self.s.flush()
        return importacion.id

    def actualizar_importacion(self, importacion_id: int, **campos) -> None:
        self.s.execute(
            update(models.Importacion).where(models.Importacion.id == importacion_id).values(**campos)
            .execution_options(**_SIN_SINCRONIZAR))

    def actualizar_fuente(self, fuente_id: int, **campos) -> None:
        """Actualiza solo los campos indicados de la ficha (periodo, fecha de descarga, URL, publicación)."""
        permitidos = {"periodo_inicio", "periodo_fin", "fecha_descarga", "fecha_publicacion", "url"}
        valores = {k: v for k, v in campos.items() if k in permitidos}
        if not valores:
            return
        self.s.execute(
            update(models.FuenteDatos).where(models.FuenteDatos.id == fuente_id).values(**valores)
            .execution_options(**_SIN_SINCRONIZAR))

    def crear_importacion_archivo(self, *, fuente_id: int, modo: str, archivo: str, hoja: str | None, mapeo: dict,
                                  resumen: dict, usuario_id: int | None) -> int:
        importacion = models.Importacion(fuente_id=fuente_id, usuario_id=usuario_id, tipo="excel", modo=modo,
                                         archivo=archivo, hoja=hoja, estado="previsualizada", mapeo=mapeo,
                                         resumen=resumen)
        self.s.add(importacion)
        self.s.flush()
        return importacion.id

    def reservar_importacion(self, importacion_id: int, estados: tuple[str, ...]) -> bool:
        """UPDATE condicional: solo una petición concurrente logra pasarla a 'en_proceso'."""
        resultado = self.s.execute(
            update(models.Importacion)
            .where(models.Importacion.id == importacion_id, models.Importacion.estado.in_(estados))
            .values(estado="en_proceso").execution_options(**_SIN_SINCRONIZAR))
        return resultado.rowcount == 1

    def obtener_importacion(self, importacion_id: int) -> dict | None:
        imp = self.s.get(models.Importacion, importacion_id, populate_existing=True)
        if imp is None:
            return None
        return {c.name: getattr(imp, c.name) for c in models.Importacion.__table__.columns}

    # ------------------------------------------------------------------ consultas
    def fecha_maxima(self, fuente_id: int) -> date | None:
        return self.s.scalar(select(func.max(SE.fecha_evento)).where(SE.fuente_id == fuente_id))

    def periodo_real(self, fuente_id: int) -> tuple[date | None, date | None]:
        fila = self.s.execute(
            select(func.min(SE.fecha_evento), func.max(SE.fecha_evento)).where(SE.fuente_id == fuente_id)).one()
        return fila[0], fila[1]

    def contar_registros(self, fuente_id: int) -> int:
        return self.s.scalar(select(func.count()).select_from(SE).where(SE.fuente_id == fuente_id)) or 0

    def ids_desde(self, fuente_id: int, desde: date | None) -> set[int]:
        consulta = select(SE.id_registro).where(SE.fuente_id == fuente_id)
        if desde is not None:
            consulta = consulta.where(SE.fecha_evento >= desde)
        return set(self.s.scalars(consulta))

    def mapa_ids(self, fuente_id: int, ids: Sequence[int]) -> dict[int, int]:
        """id_registro de la fuente -> id interno, solo para los que existen."""
        return self._mapa_ids(fuente_id, ids)

    def _mapa_ids(self, fuente_id: int, ids: Sequence[int]) -> dict[int, int]:
        mapa: dict[int, int] = {}
        for bloque in _bloques(list(ids)):
            filas = self.s.execute(
                select(SE.id_registro, SE.id).where(SE.fuente_id == fuente_id, SE.id_registro.in_(bloque)))
            mapa.update({id_registro: id_ for id_registro, id_ in filas})
        return mapa

    # ------------------------------------------------------------------ escritura por lote
    def guardar_lote(self, fuente_id: int, importacion_id: int, registros: list[RegistroSiniestro],
                     reemplazar_hijos: bool = True) -> tuple[int, int]:
        """Upsert por (fuente_id, id_registro). Con reemplazar_hijos (ArcGIS) también reemplaza personas,
        vehículos y causas; sin él (hoja Siniestros de un anuario) las deja intactas."""
        if not registros:
            return 0, 0
        ids = [r.id_registro for r in registros]
        existentes = self._mapa_ids(fuente_id, ids)
        ahora = datetime.now(timezone.utc)

        nuevos: list[dict] = []
        actualizar: list[dict] = []
        for r in registros:
            datos = dict(r.siniestro, fuente_id=fuente_id, importacion_id=importacion_id)
            if r.id_registro in existentes:
                actualizar.append(dict(datos, id=existentes[r.id_registro], actualizado_en=ahora))
            else:
                nuevos.append(datos)

        if actualizar:
            self.s.execute(update(SE), actualizar)  # ORM bulk UPDATE por clave primaria
        if nuevos:
            self.s.execute(insert(SE), nuevos)

        if not reemplazar_hijos:
            return len(nuevos), len(actualizar)
        mapa = self._mapa_ids(fuente_id, ids)
        ids_internos = [mapa[i] for i in ids]
        for modelo in (models.ActorVial, models.VehiculoEvento, models.CausaEvento):
            for bloque in _bloques(ids_internos):
                self.s.execute(delete(modelo).where(modelo.siniestro_id.in_(bloque))
                               .execution_options(**_SIN_SINCRONIZAR))

        for modelo, atributo in ((models.ActorVial, "actores"), (models.VehiculoEvento, "vehiculos"),
                                 (models.CausaEvento, "causas")):
            filas = [dict(h, siniestro_id=mapa[r.id_registro]) for r in registros for h in getattr(r, atributo)]
            if filas:
                self.s.execute(insert(modelo), filas)
        return len(nuevos), len(actualizar)

    _MODELOS_HIJOS = {"actores": models.ActorVial, "vehiculos": models.VehiculoEvento, "causas": models.CausaEvento}

    def reemplazar_hijos(self, tipo: str, filas: list[dict], limpiar: list[int]) -> None:
        """Borra las filas hijas de los siniestros en `limpiar` e inserta `filas` (con siniestro_id)."""
        modelo = self._MODELOS_HIJOS[tipo]
        for bloque in _bloques(list(limpiar)):
            self.s.execute(delete(modelo).where(modelo.siniestro_id.in_(bloque)).execution_options(**_SIN_SINCRONIZAR))
        if filas:
            self.s.execute(insert(modelo), filas)

    def siniestros_sin_hijos(self, fuente_id: int, tipo: str) -> int:
        modelo = self._MODELOS_HIJOS[tipo]
        con_hijos = select(modelo.siniestro_id)
        return self.s.scalar(select(func.count()).select_from(SE).where(
            SE.fuente_id == fuente_id, SE.id.not_in(con_hijos))) or 0

    def upsert_denominadores(self, fuente_id: int, filas: list[tuple[str, int, int]]) -> tuple[int, int]:
        D = models.DenominadorOficial
        existentes = {(loc, anio): id_ for id_, loc, anio in
                      self.s.execute(select(D.id, D.localidad, D.anio).where(D.fuente_id == fuente_id))}
        nuevos, actualizar = [], []
        for localidad, anio, poblacion in filas:
            if (localidad, anio) in existentes:
                actualizar.append({"id": existentes[(localidad, anio)], "poblacion": poblacion})
            else:
                nuevos.append({"fuente_id": fuente_id, "localidad": localidad, "anio": anio, "poblacion": poblacion})
        if actualizar:
            self.s.execute(update(D), actualizar)
        if nuevos:
            self.s.execute(insert(D), nuevos)
        return len(nuevos), len(actualizar)

    # ------------------------------------------------------------------ coherencia de coordenadas
    def puntos_para_coherencia(self, fuente_id: int) -> list[tuple[int, str | None, float, float]]:
        consulta = select(SE.id_registro, SE.localidad, SE.latitud, SE.longitud).where(
            SE.fuente_id == fuente_id,
            SE.latitud.is_not(None),
            SE.longitud.is_not(None),
            or_(SE.coordenada_valida.is_(True), SE.motivo_coordenada == "sospechosa"),
        )
        return [tuple(fila) for fila in self.s.execute(consulta)]

    def aplicar_coherencia(self, fuente_id: int, sospechosas: set[int]) -> int:
        """Recalcula la marca 'sospechosa' de toda la fuente (se borra la anterior y se aplica la nueva)."""
        self.s.execute(
            update(SE).where(SE.fuente_id == fuente_id, SE.motivo_coordenada == "sospechosa")
            .values(coordenada_valida=True, motivo_coordenada=None).execution_options(**_SIN_SINCRONIZAR))
        lista = sorted(sospechosas)
        for bloque in _bloques(lista):
            self.s.execute(
                update(SE).where(SE.fuente_id == fuente_id, SE.id_registro.in_(bloque), SE.latitud.is_not(None),
                                 SE.longitud.is_not(None))
                .values(coordenada_valida=False, motivo_coordenada="sospechosa")
                .execution_options(**_SIN_SINCRONIZAR))
        return len(lista)

    # ------------------------------------------------------------------ otras fuentes
    def coincidencias_otras_fuentes(self, fuente_id: int) -> list[dict]:
        """Mismo id_registro en otras fuentes. No se suman ni se fusionan: solo se informa cuál
        prevalece (menor número de prioridad) y cuántos difieren en fecha o gravedad."""
        propia = self.s.get(models.FuenteDatos, fuente_id)
        otras = self.s.execute(
            select(models.FuenteDatos.id, models.FuenteDatos.codigo, models.FuenteDatos.prioridad)
            .where(models.FuenteDatos.id != fuente_id)).all()
        a, b = aliased(SE), aliased(SE)
        resultado: list[dict] = []
        for otra_id, codigo, prioridad in otras:
            base = (select(a.id_registro).select_from(a)
                     .join(b, (b.id_registro == a.id_registro) & (b.fuente_id == otra_id))
                     .where(a.fuente_id == fuente_id))
            fila = self.s.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(case((a.fecha_evento != b.fecha_evento, 1), else_=0)), 0),
                    func.coalesce(func.sum(case((func.coalesce(a.gravedad, "") != func.coalesce(b.gravedad, ""), 1),
                                                else_=0)), 0),
                ).select_from(a).join(b, (b.id_registro == a.id_registro) & (b.fuente_id == otra_id))
                .where(a.fuente_id == fuente_id)).one()
            coincidencias, fecha_distinta, gravedad_distinta = int(fila[0]), int(fila[1]), int(fila[2])
            if not coincidencias:
                continue
            ejemplos = self.s.execute(
                base.add_columns(a.fecha_evento, b.fecha_evento).where(a.fecha_evento != b.fecha_evento).limit(20)
            ).all()
            resultado.append({
                "fuente": codigo,
                "prioridad": prioridad,
                "coincidencias": coincidencias,
                "fecha_distinta": fecha_distinta,
                "gravedad_distinta": gravedad_distinta,
                "prevalece": propia.codigo if propia.prioridad <= prioridad else codigo,
                "ejemplos_fecha_distinta": [
                    {"id_registro": e[0], "esta_fuente": e[1].isoformat(), "otra_fuente": e[2].isoformat()}
                    for e in ejemplos],
                "nota": "La gravedad de ArcGIS (GRAVEDAD) y la del anuario (indicador 30 días) usan criterios "
                        "distintos; una diferencia no implica error.",
            })
        return resultado

    # ------------------------------------------------------------------ transacción
    def confirmar(self) -> None:
        self.s.commit()

    def revertir(self) -> None:
        self.s.rollback()
