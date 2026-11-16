"""Errores JSON coherentes en toda la API:

    {"error": {"codigo": "parametros_invalidos", "mensaje": "...", "detalles": [...]}}

Nunca se devuelven trazas, rutas internas, secretos ni el valor enviado en un campo (podría ser una
contraseña): solo el nombre del campo y el motivo.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..services.consultas import ErrorConsulta

log = logging.getLogger("via_segura.api")

_CODIGOS_HTTP = {400: "peticion_invalida", 401: "no_autenticado", 403: "prohibido", 404: "no_encontrado",
                 405: "metodo_no_permitido", 409: "conflicto", 413: "archivo_demasiado_grande",
                 422: "parametros_invalidos", 429: "demasiadas_peticiones"}


class ErrorApi(Exception):
    def __init__(self, estado: int, codigo: str, mensaje: str, detalles: list | None = None,
                 cabeceras: dict | None = None):
        super().__init__(mensaje)
        self.estado, self.codigo, self.mensaje = estado, codigo, mensaje
        self.detalles, self.cabeceras = detalles, cabeceras


def respuesta_error(estado: int, codigo: str, mensaje: str, detalles: list | None = None,
                    cabeceras: dict | None = None) -> JSONResponse:
    cuerpo = {"error": {"codigo": codigo, "mensaje": mensaje}}
    if detalles:
        cuerpo["error"]["detalles"] = detalles
    return JSONResponse(cuerpo, status_code=estado, headers=cabeceras)


def detalles_validacion(errores: list[dict]) -> list[dict]:
    salida = []
    for e in errores:
        campo = ".".join(str(p) for p in e.get("loc", ()) if p not in ("query", "body", "path", "form"))
        salida.append({"campo": campo or None, "mensaje": str(e.get("msg", "valor inválido")).replace("Value error, ", "")})
    return salida


def registrar_manejadores(app: FastAPI) -> None:
    @app.exception_handler(ErrorApi)
    async def _api(_request: Request, exc: ErrorApi):
        return respuesta_error(exc.estado, exc.codigo, exc.mensaje, exc.detalles, exc.cabeceras)

    @app.exception_handler(ErrorConsulta)
    async def _consulta(_request: Request, exc: ErrorConsulta):
        return respuesta_error(exc.estado, exc.codigo, exc.mensaje)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_request: Request, exc: StarletteHTTPException):
        mensaje = exc.detail if isinstance(exc.detail, str) else "Error en la petición."
        if exc.status_code == 404 and mensaje == "Not Found":
            mensaje = "El recurso solicitado no existe."
        if exc.status_code == 405:
            mensaje = "Método no permitido para este recurso."
        return respuesta_error(exc.status_code, _CODIGOS_HTTP.get(exc.status_code, "error_http"), mensaje,
                               cabeceras=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validacion(_request: Request, exc: RequestValidationError):
        return respuesta_error(422, "parametros_invalidos", "Hay parámetros inválidos en la petición.",
                               detalles_validacion(exc.errors()))

    @app.exception_handler(Exception)
    async def _interno(request: Request, exc: Exception):
        log.exception("Error interno en %s %s", request.method, request.url.path)
        return respuesta_error(500, "error_interno", "Ocurrió un error interno. Intente más tarde.")
