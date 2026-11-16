"""Configuración central de VÍA SEGURA. Todos los secretos se leen de .env."""
from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ = Path(__file__).resolve().parents[2]
_SECRETO_POR_DEFECTO = "solo-desarrollo-no-usar-en-produccion"


class Configuracion(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=RAIZ / ".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    entorno: str = "desarrollo"  # "desarrollo" | "produccion"
    database_url: str = f"sqlite:///{(RAIZ / 'via_segura.db').as_posix()}"
    secret_key: str = _SECRETO_POR_DEFECTO
    token_expira_minutos: int = Field(60, ge=5, le=1440)
    cors_origenes: str = "http://localhost:8000,http://127.0.0.1:8000"
    limite_peticiones_por_minuto: int = Field(120, ge=10, le=10000)
    limite_login_por_minuto: int = Field(10, ge=1, le=1000)

    arcgis_base_url: str = (
        "https://sig.simur.gov.co/arcgis/rest/services/Accidentalidad/"
        "AccidentalidadAnalisis/FeatureServer"
    )
    arcgis_pagina: int = Field(2000, ge=100, le=2000)  # MaxRecordCount del servicio = 2000
    arcgis_timeout_s: int = Field(60, ge=5, le=600)
    arcgis_ventana_dias: int = Field(90, ge=0, le=3650)
    arcgis_reintentos: int = Field(4, ge=0, le=10)
    # Cuántos FORMULARIO se piden por consulta a las tablas relacionadas (actor vial, vehículo, causa).
    arcgis_lote_formularios: int = Field(500, ge=1, le=2000)

    # Revisión de coherencia localidad-coordenada (heurística mientras no haya polígonos oficiales).
    coherencia_percentil: float = Field(0.001, ge=0, le=0.05)
    coherencia_margen_grados: float = Field(0.03, ge=0, le=0.5)

    carga_max_mb: int = Field(200, ge=1, le=2000)
    # Límite del contenido descomprimido de un .xlsx (protección contra "bombas ZIP").
    carga_max_descomprimido_mb: int = Field(3000, ge=10, le=20000)
    exportar_max_filas: int = Field(300_000, ge=1000, le=2_000_000)  # CSV público; más filas = acotar filtros
    carga_directorio: Path = RAIZ / "backend" / "app" / "data" / "cargas"
    geo_directorio: Path = RAIZ / "backend" / "app" / "data" / "geo"
    geo_tolerancia_grados: float = Field(0.00005, ge=0, le=0.01)  # simplificación (~5 m)
    importar_bloque: int = Field(2000, ge=100, le=20000)
    conservar_archivo_importado: bool = False
    frontend_directorio: Path = RAIZ / "frontend"

    @model_validator(mode="after")
    def _validar(self):
        # SQLAlchemy + psycopg 3: "postgresql://" -> "postgresql+psycopg://"
        if self.database_url.startswith("postgresql://"):
            self.database_url = self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        if self.entorno == "produccion" and (
            self.secret_key == _SECRETO_POR_DEFECTO or len(self.secret_key) < 32
        ):
            raise ValueError("En producción SECRET_KEY debe definirse en .env con al menos 32 caracteres.")
        return self

    @property
    def cors_lista(self) -> list[str]:
        return [o.strip() for o in self.cors_origenes.split(",") if o.strip()]

    @property
    def es_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Configuracion:
    return Configuracion()
