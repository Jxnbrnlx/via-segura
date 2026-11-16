"""Filtros comunes a todos los endpoints públicos (validados con Pydantic).

Todos los filtros se combinan con Y. Las listas se envían repitiendo el parámetro:
    ?localidad=SUBA&localidad=Usaquén&gravedad=Con Muertos
Gravedad por defecto: "Con Heridos" y "Con Muertos" (serie comparable, decisión 3).
Para incluir "Solo Daños" use gravedad=todas o nómbrela explícitamente.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..services import calidad

GRAVEDADES = ("Con Muertos", "Con Heridos", "Solo Daños")
GRAVEDAD_POR_DEFECTO = ("Con Heridos", "Con Muertos")


class Filtros(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fuente: str | None = Field(None, max_length=60)
    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    anio: list[int] = Field(default_factory=list, max_length=40)
    mes: list[int] = Field(default_factory=list, max_length=12)
    localidad: list[str] = Field(default_factory=list, max_length=20)
    clase: list[str] = Field(default_factory=list, max_length=20)
    gravedad: list[str] = Field(default_factory=list, max_length=4)
    actor: list[str] = Field(default_factory=list, max_length=10)
    todas_las_gravedades: bool = False

    @model_validator(mode="before")
    @classmethod
    def _todas(cls, datos):
        if isinstance(datos, dict):
            gravedad = [g for g in (datos.get("gravedad") or []) if g is not None]
            if any(str(g).strip().lower() == "todas" for g in gravedad):
                datos = dict(datos, gravedad=[g for g in gravedad if str(g).strip().lower() != "todas"],
                             todas_las_gravedades=True)
        return datos

    @field_validator("anio")
    @classmethod
    def _anio(cls, v):
        for a in v:
            if not 1990 <= a <= 2100:
                raise ValueError(f"año fuera de rango: {a}")
        return sorted(set(v))

    @field_validator("mes")
    @classmethod
    def _mes(cls, v):
        for m in v:
            if not 1 <= m <= 12:
                raise ValueError(f"mes fuera de rango: {m}")
        return sorted(set(v))

    @field_validator("localidad")
    @classmethod
    def _localidad(cls, v):
        salida = []
        for texto in v:
            try:
                clave = calidad.normalizar_localidad(texto)
            except calidad.ValorNoReconocido:
                raise ValueError(f"localidad desconocida: {texto!r}") from None
            if clave and clave not in salida:
                salida.append(clave)
        return sorted(salida)

    @field_validator("clase")
    @classmethod
    def _clase(cls, v):
        salida = []
        for texto in v:
            if len(texto) > 40:
                raise ValueError("clase demasiado larga")
            clase, _ = calidad.normalizar_clase(texto)
            if clase and clase not in salida:
                salida.append(clase)
        return sorted(salida)

    @field_validator("gravedad")
    @classmethod
    def _gravedad(cls, v):
        salida = []
        for texto in v:
            try:
                g = calidad.normalizar_gravedad(texto)
            except calidad.ValorNoReconocido:
                raise ValueError(f"gravedad desconocida: {texto!r}. Use {', '.join(GRAVEDADES)} o 'todas'") from None
            if g and g not in salida:
                salida.append(g)
        return sorted(salida)

    @field_validator("actor")
    @classmethod
    def _actor(cls, v):
        salida = []
        for texto in v:
            if len(texto) > 60:
                raise ValueError("condición de actor vial demasiado larga")
            k = calidad.clave(texto)
            if k and k not in salida:
                salida.append(k)
        return sorted(salida)

    @model_validator(mode="after")
    def _rango(self):
        if self.fecha_desde and self.fecha_hasta and self.fecha_desde > self.fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")
        return self

    @property
    def gravedades_efectivas(self) -> tuple[str, ...] | None:
        """None = sin filtro de gravedad."""
        if self.todas_las_gravedades:
            return None
        return tuple(self.gravedad) if self.gravedad else GRAVEDAD_POR_DEFECTO

    @property
    def usa_gravedad_por_defecto(self) -> bool:
        return not self.todas_las_gravedades and not self.gravedad

    @property
    def incluye_solo_danos(self) -> bool:
        g = self.gravedades_efectivas
        return g is None or "Solo Daños" in g

    def como_dict(self) -> dict:
        return {
            "fecha_desde": self.fecha_desde.isoformat() if self.fecha_desde else None,
            "fecha_hasta": self.fecha_hasta.isoformat() if self.fecha_hasta else None,
            "anio": self.anio, "mes": self.mes, "localidad": self.localidad, "clase": self.clase,
            "gravedad": list(self.gravedades_efectivas) if self.gravedades_efectivas else "todas",
            "gravedad_por_defecto": self.usa_gravedad_por_defecto,
            "actor": self.actor,
        }


class Paginacion(BaseModel):
    model_config = ConfigDict(frozen=True)
    pagina: int = Field(1, ge=1, le=100_000)
    tamano: int = Field(50, ge=1, le=200)

    @property
    def desplazamiento(self) -> int:
        return (self.pagina - 1) * self.tamano
