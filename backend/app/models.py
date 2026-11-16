"""Modelos SQLAlchemy de VÍA SEGURA.

Principios (ver docs/metodologia.md):
- `siniestros_evento` guarda SOLO eventos individuales; `indicadores_agregados` guarda SOLO
  valores resumidos de anuarios. Nunca se mezclan.
- Siniestros y personas (heridas/fallecidas) viven en tablas distintas y no se suman entre sí.
- No se almacenan placas, fechas de nacimiento ni identificadores personales de las víctimas.
- No se inventan coordenadas: si faltan o son sospechosas, `coordenada_valida` = false y se
  registra el motivo.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON, BigInteger, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index,
    Integer, SmallInteger, String, Text, UniqueConstraint, false, func, true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# Clave primaria grande en PostgreSQL y entera en SQLite (para que autoincremente).
BigPK = BigInteger().with_variant(Integer(), "sqlite")

GRAVEDADES = ("Con Muertos", "Con Heridos", "Solo Daños")
ESTADOS_PERSONA = ("HERIDO", "ILESO", "MUERTO")
TIPOS_IMPORTACION = ("arcgis", "excel")
ESTADOS_IMPORTACION = ("pendiente", "previsualizada", "en_proceso", "completada", "fallida", "cancelada")
MOTIVOS_COORDENADA = ("sin_coordenada", "fuera_de_rango", "fuera_de_bogota", "sospechosa")


def _en(columna: str, valores: tuple[str, ...]) -> str:
    return f"{columna} IN (" + ", ".join(f"'{v}'" for v in valores) + ")"


class MarcaTiempo:
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FuenteDatos(MarcaTiempo, Base):
    """Ficha de procedencia. El periodo se rellena con el mínimo/máximo REAL de lo importado."""

    __tablename__ = "fuentes_datos"
    __table_args__ = (
        CheckConstraint("periodo_fin IS NULL OR periodo_inicio IS NULL OR periodo_fin >= periodo_inicio", name="periodo"),
        CheckConstraint("prioridad >= 1", name="prioridad"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(60), unique=True)  # p. ej. "arcgis_simur_accidentalidad"
    entidad: Mapped[str] = mapped_column(String(150))
    nombre: Mapped[str] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(500))
    fecha_publicacion: Mapped[date | None] = mapped_column(Date)
    fecha_descarga: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    periodo_inicio: Mapped[date | None] = mapped_column(Date)
    periodo_fin: Mapped[date | None] = mapped_column(Date)
    formato: Mapped[str] = mapped_column(String(30))
    prioridad: Mapped[int] = mapped_column(SmallInteger, default=100, server_default="100")  # 1 = máxima
    activa: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    notas: Mapped[str | None] = mapped_column(Text)


class UsuarioAdmin(Base):
    __tablename__ = "usuarios_admin"
    __table_args__ = (CheckConstraint(_en("rol", ("admin",)), name="rol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    correo: Mapped[str] = mapped_column(String(254), unique=True)
    hash_contrasena: Mapped[str] = mapped_column(String(255))
    rol: Mapped[str] = mapped_column(String(20), default="admin", server_default="admin")
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ultimo_acceso: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Importacion(Base):
    """Registro de cada carga (Excel) o sincronización (ArcGIS). Sin datos personales."""

    __tablename__ = "importaciones"
    __table_args__ = (
        CheckConstraint(_en("tipo", TIPOS_IMPORTACION), name="tipo"),
        CheckConstraint(_en("estado", ESTADOS_IMPORTACION), name="estado"),
        CheckConstraint("filas_revisadas >= 0 AND filas_validas >= 0 AND filas_rechazadas >= 0", name="conteos"),
        Index("ix_importaciones_iniciada_en", "iniciada_en"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fuente_id: Mapped[int | None] = mapped_column(ForeignKey("fuentes_datos.id", ondelete="SET NULL"))
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios_admin.id", ondelete="SET NULL"))
    tipo: Mapped[str] = mapped_column(String(10))
    modo: Mapped[str | None] = mapped_column(String(20))  # completa | incremental | carga_manual
    archivo: Mapped[str | None] = mapped_column(String(255))  # nombre saneado, nunca una ruta
    hoja: Mapped[str | None] = mapped_column(String(120))
    estado: Mapped[str] = mapped_column(String(20), default="pendiente", server_default="pendiente")
    iniciada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finalizada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    filas_revisadas: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    filas_validas: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    filas_rechazadas: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    fecha_min_evento: Mapped[date | None] = mapped_column(Date)
    fecha_max_evento: Mapped[date | None] = mapped_column(Date)
    mapeo: Mapped[dict | None] = mapped_column(JSON)  # campo lógico -> nombre ORIGINAL de columna
    errores: Mapped[list | None] = mapped_column(JSON)  # muestra acotada de errores legibles
    resumen: Mapped[dict | None] = mapped_column(JSON)  # banderas de calidad, duplicados, etc.


class SiniestroEvento(MarcaTiempo, Base):
    """Un registro por siniestro. NO contiene conteos de víctimas (ver ActorVial)."""

    __tablename__ = "siniestros_evento"
    __table_args__ = (
        UniqueConstraint("fuente_id", "id_registro", name="uq_siniestros_evento_fuente_registro"),
        CheckConstraint("mes IS NULL OR (mes BETWEEN 1 AND 12)", name="mes"),
        CheckConstraint("hora IS NULL OR (hora BETWEEN 0 AND 23)", name="hora"),
        CheckConstraint("minuto IS NULL OR (minuto BETWEEN 0 AND 59)", name="minuto"),
        CheckConstraint("latitud IS NULL OR (latitud BETWEEN -90 AND 90)", name="lat_rango"),
        CheckConstraint("longitud IS NULL OR (longitud BETWEEN -180 AND 180)", name="lon_rango"),
        CheckConstraint("gravedad IS NULL OR " + _en("gravedad", GRAVEDADES), name="gravedad"),
        CheckConstraint(
            "gravedad_tradicional IS NULL OR " + _en("gravedad_tradicional", GRAVEDADES),
            name="gravedad_trad",
        ),
        CheckConstraint(
            "motivo_coordenada IS NULL OR " + _en("motivo_coordenada", MOTIVOS_COORDENADA),
            name="motivo_coord",
        ),
        CheckConstraint(
            "(coordenada_valida AND motivo_coordenada IS NULL) OR "
            "(NOT coordenada_valida AND motivo_coordenada IS NOT NULL)",
            name="coord_coherente",
        ),
        CheckConstraint(
            "NOT coordenada_valida OR (latitud IS NOT NULL AND longitud IS NOT NULL)",
            name="coord_completa",
        ),
        Index("ix_siniestros_fecha", "fecha_evento"),
        Index("ix_siniestros_fuente_anio_loc", "fuente_id", "anio", "localidad"),
        Index("ix_siniestros_gravedad", "gravedad"),
        Index("ix_siniestros_clase", "clase_siniestro"),
        Index("ix_siniestros_coord", "coordenada_valida", "latitud", "longitud"),
    )

    id: Mapped[int] = mapped_column(BigPK, primary_key=True)
    fuente_id: Mapped[int] = mapped_column(ForeignKey("fuentes_datos.id", ondelete="RESTRICT"))
    importacion_id: Mapped[int | None] = mapped_column(ForeignKey("importaciones.id", ondelete="SET NULL"))
    id_registro: Mapped[int] = mapped_column(BigInteger)  # Codigo_Accidente / CODIGO_ACCIDENTE
    formulario: Mapped[str | None] = mapped_column(String(20))  # IPAT: interno, NO se expone en la API pública
    fecha_evento: Mapped[date] = mapped_column(Date)
    anio: Mapped[int] = mapped_column(SmallInteger)
    mes: Mapped[int | None] = mapped_column(SmallInteger)
    dia_semana: Mapped[str | None] = mapped_column(String(12))
    hora: Mapped[int | None] = mapped_column(SmallInteger)
    minuto: Mapped[int | None] = mapped_column(SmallInteger)
    localidad: Mapped[str | None] = mapped_column(String(60))  # normalizada (MAYÚSCULAS)
    direccion: Mapped[str | None] = mapped_column(String(150))
    barrio: Mapped[str | None] = mapped_column(String(255))
    via_nombre: Mapped[str | None] = mapped_column(String(255))
    clase_siniestro: Mapped[str | None] = mapped_column(String(40))
    # Anuarios: gravedad = Gravedad_indicador_30d. ArcGIS: gravedad = GRAVEDAD (criterio sin documentar).
    gravedad: Mapped[str | None] = mapped_column(String(20))
    gravedad_tradicional: Mapped[str | None] = mapped_column(String(20))  # solo anuario 2015-2024
    latitud: Mapped[float | None] = mapped_column(Float)
    longitud: Mapped[float | None] = mapped_column(Float)
    coordenada_valida: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    motivo_coordenada: Mapped[str | None] = mapped_column(String(20))
    atributos: Mapped[dict | None] = mapped_column(JSON)  # banderas Con_* y nombres originales útiles

    actores: Mapped[list["ActorVial"]] = relationship(
        back_populates="siniestro", cascade="all, delete-orphan", passive_deletes=True
    )
    vehiculos: Mapped[list["VehiculoEvento"]] = relationship(
        back_populates="siniestro", cascade="all, delete-orphan", passive_deletes=True
    )
    causas: Mapped[list["CausaEvento"]] = relationship(
        back_populates="siniestro", cascade="all, delete-orphan", passive_deletes=True
    )


class ActorVial(Base):
    """Persona registrada en un siniestro (incluye ilesos). Sin nombre, documento, placa ni nacimiento."""

    __tablename__ = "actores_viales"
    __table_args__ = (
        UniqueConstraint("siniestro_id", "codigo_vehiculo", "consecutivo_victima",
                         name="uq_actores_viales_siniestro_vehiculo_victima"),
        CheckConstraint("estado IS NULL OR " + _en("estado", ESTADOS_PERSONA), name="estado"),
        CheckConstraint("edad IS NULL OR (edad BETWEEN 0 AND 110)", name="edad"),
        Index("ix_actores_estado", "estado"),
        Index("ix_actores_condicion", "condicion"),
    )

    id: Mapped[int] = mapped_column(BigPK, primary_key=True)
    siniestro_id: Mapped[int] = mapped_column(BigPK, ForeignKey("siniestros_evento.id", ondelete="CASCADE"))
    # Puede faltar: en ArcGIS hay personas sin CODIGO_VEHICULO (p. ej. peatones). No se inventa un código.
    codigo_vehiculo: Mapped[int | None] = mapped_column(Integer)
    consecutivo_victima: Mapped[int] = mapped_column(Integer)
    estado: Mapped[str | None] = mapped_column(String(10))  # HERIDO | ILESO | MUERTO
    condicion: Mapped[str | None] = mapped_column(String(60))  # conductor, peatón, motociclista, ciclista, pasajero
    condicion_especifica: Mapped[str | None] = mapped_column(String(80))
    sexo: Mapped[str | None] = mapped_column(String(20))
    edad: Mapped[int | None] = mapped_column(SmallInteger)  # NULL si falta o es atípica (>110)
    rango_edad: Mapped[str | None] = mapped_column(String(10))
    muerte_posterior: Mapped[bool | None] = mapped_column(Boolean)

    siniestro: Mapped[SiniestroEvento] = relationship(back_populates="actores")


class VehiculoEvento(Base):
    """Vehículo involucrado. No se guarda la placa."""

    __tablename__ = "vehiculos_evento"
    __table_args__ = (
        UniqueConstraint("siniestro_id", "codigo_vehiculo", name="uq_vehiculos_evento_siniestro_vehiculo"),
        Index("ix_vehiculos_clase", "clase"),
    )

    id: Mapped[int] = mapped_column(BigPK, primary_key=True)
    siniestro_id: Mapped[int] = mapped_column(BigPK, ForeignKey("siniestros_evento.id", ondelete="CASCADE"))
    codigo_vehiculo: Mapped[int] = mapped_column(Integer)
    clase: Mapped[str | None] = mapped_column(String(40))
    servicio: Mapped[str | None] = mapped_column(String(40))
    modalidad: Mapped[str | None] = mapped_column(String(60))

    siniestro: Mapped[SiniestroEvento] = relationship(back_populates="vehiculos")


class CausaEvento(Base):
    """Causa/hipótesis (solo existe en ArcGIS, tabla VM_ACC_CAUSA). La sincronización reemplaza el conjunto por siniestro."""

    __tablename__ = "causas_evento"
    __table_args__ = (Index("ix_causas_siniestro", "siniestro_id"), Index("ix_causas_codigo", "codigo_causa"))

    id: Mapped[int] = mapped_column(BigPK, primary_key=True)
    siniestro_id: Mapped[int] = mapped_column(BigPK, ForeignKey("siniestros_evento.id", ondelete="CASCADE"))
    codigo_vehiculo: Mapped[int | None] = mapped_column(Integer)
    codigo_causa: Mapped[str] = mapped_column(String(15))
    nombre: Mapped[str | None] = mapped_column(String(80))
    tipo_causa: Mapped[str | None] = mapped_column(String(200))

    siniestro: Mapped[SiniestroEvento] = relationship(back_populates="causas")


class IndicadorAgregado(Base):
    """Valores resumidos de anuarios/informes. NUNCA se mezclan con eventos individuales."""

    __tablename__ = "indicadores_agregados"
    __table_args__ = (Index("ix_indicadores_busqueda", "fuente_id", "indicador", "periodo_inicio"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fuente_id: Mapped[int] = mapped_column(ForeignKey("fuentes_datos.id", ondelete="RESTRICT"))
    indicador: Mapped[str] = mapped_column(String(80))
    unidad: Mapped[str] = mapped_column(String(40))  # "siniestros" | "personas lesionadas" | "personas fallecidas" ...
    periodo_inicio: Mapped[date | None] = mapped_column(Date)
    periodo_fin: Mapped[date | None] = mapped_column(Date)
    localidad: Mapped[str | None] = mapped_column(String(60))
    categoria: Mapped[str | None] = mapped_column(String(80))
    valor: Mapped[float] = mapped_column(Float)
    notas: Mapped[str | None] = mapped_column(Text)


class DenominadorOficial(Base):
    """Población (u otro denominador) oficial por localidad y año. Sin filas aquí, NO se calculan tasas."""

    __tablename__ = "denominadores_oficiales"
    __table_args__ = (
        UniqueConstraint("fuente_id", "localidad", "anio", name="uq_denominadores_fuente_localidad_anio"),
        CheckConstraint("poblacion > 0", name="poblacion"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fuente_id: Mapped[int] = mapped_column(ForeignKey("fuentes_datos.id", ondelete="RESTRICT"))
    localidad: Mapped[str] = mapped_column(String(60))
    anio: Mapped[int] = mapped_column(SmallInteger)
    poblacion: Mapped[int] = mapped_column(Integer)
