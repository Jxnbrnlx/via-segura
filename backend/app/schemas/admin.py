"""Esquemas de entrada de la administración."""
from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_CORREO = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$")


def normalizar_correo(valor: str) -> str:
    correo = valor.strip().lower()
    if not _CORREO.match(correo):
        raise ValueError("correo inválido")
    return correo


class LoginEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correo: str = Field(max_length=254)
    contrasena: str = Field(min_length=1, max_length=200)

    @field_validator("correo")
    @classmethod
    def _correo(cls, v: str) -> str:
        return normalizar_correo(v)


class SincronizarEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    modo: Literal["incremental", "completa"] = "incremental"
    desde_anio: int | None = Field(None, ge=2001, le=2100)
    max_paginas: int | None = Field(None, ge=1, le=10_000)


class ConfirmarEntrada(BaseModel):
    """Datos de la ficha de la fuente que el administrador puede registrar al confirmar."""
    model_config = ConfigDict(extra="forbid")
    url: str | None = Field(None, max_length=500)
    fecha_publicacion: date | None = None
    fecha_descarga: date | None = None

    @field_validator("url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        if v and not re.match(r"^https?://[^\s]+$", v):
            raise ValueError("la URL debe empezar por http:// o https://")
        return v or None
