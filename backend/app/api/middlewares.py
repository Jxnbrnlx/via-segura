"""Middlewares ASGI puros (sin dependencias externas, compatibles con Starlette 1.x).

- LimitadorPeticiones: límite por IP y por minuto (ventana deslizante en memoria) para /api/,
  con reglas más estrictas por ruta (p. ej. el inicio de sesión).
  Nota: el conteo vive en la memoria del proceso; con varios procesos cada uno cuenta aparte.
- ProteccionCargas: antes de recibir un archivo exige token Bearer válido y Content-Length dentro del
  límite, para que nadie sin sesión pueda enviar cientos de MB al servidor.
- CabecerasSeguridad: cabeceras defensivas en todas las respuestas y no-store en /admin.
"""
from __future__ import annotations

import json
import time
from collections import deque
from collections.abc import Callable


async def responder_json(send, estado: int, codigo: str, mensaje: str, cabeceras: list | None = None) -> None:
    cuerpo = json.dumps({"error": {"codigo": codigo, "mensaje": mensaje}}, ensure_ascii=False).encode("utf-8")
    await send({"type": "http.response.start", "status": estado,
                "headers": [(b"content-type", b"application/json; charset=utf-8"),
                            (b"content-length", str(len(cuerpo)).encode())] + (cabeceras or [])})
    await send({"type": "http.response.body", "body": cuerpo})


class LimitadorPeticiones:
    def __init__(self, app, limite_por_minuto: int, reglas: dict[str, int] | None = None, *,
                 prefijo: str = "/api/", ventana_s: float = 60.0, reloj: Callable[[], float] = time.monotonic):
        self.app = app
        self.limite = limite_por_minuto
        self.reglas = reglas or {}
        self.prefijo = prefijo
        self.ventana = ventana_s
        self.reloj = reloj
        self._registros: dict[tuple[str, str], deque] = {}
        self._llamadas = 0

    async def __call__(self, scope, receive, send):
        ruta = scope.get("path", "")
        if scope["type"] != "http" or not ruta.startswith(self.prefijo) or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        cliente = scope.get("client")
        ip = cliente[0] if cliente else "desconocido"
        grupo = ruta if ruta in self.reglas else "*"
        limite = self.reglas.get(ruta, self.limite)
        ahora = self.reloj()
        marcas = self._registros.setdefault((ip, grupo), deque())
        while marcas and ahora - marcas[0] >= self.ventana:
            marcas.popleft()
        if len(marcas) >= limite:
            espera = max(1, int(self.ventana - (ahora - marcas[0])) + 1)
            await responder_json(send, 429, "demasiadas_peticiones",
                                 f"Demasiadas peticiones. Intente de nuevo en {espera} segundos.",
                                 [(b"retry-after", str(espera).encode())])
            return
        marcas.append(ahora)
        self._llamadas += 1
        if self._llamadas % 1000 == 0:
            self._limpiar(ahora)
        await self.app(scope, receive, send)

    def _limpiar(self, ahora: float) -> None:
        for clave in [k for k, m in self._registros.items() if not m or ahora - m[-1] >= self.ventana]:
            del self._registros[clave]


class ProteccionCargas:
    def __init__(self, app, ruta: str, max_bytes: int, token_valido: Callable[[str], bool]):
        self.app = app
        self.ruta = ruta.rstrip("/")
        self.max_bytes = max_bytes
        self.token_valido = token_valido

    async def __call__(self, scope, receive, send):
        if (scope["type"] == "http" and scope.get("method") == "POST"
                and scope.get("path", "").rstrip("/") == self.ruta):
            cabeceras = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
            autorizacion = cabeceras.get("authorization", "")
            token = autorizacion[7:].strip() if autorizacion.lower().startswith("bearer ") else ""
            if not token or not self.token_valido(token):
                await responder_json(send, 401, "no_autenticado", "Inicie sesión como administrador para cargar archivos.",
                                     [(b"www-authenticate", b"Bearer")])
                return
            largo = cabeceras.get("content-length")
            if largo is None or not largo.isdigit():
                await responder_json(send, 411, "largo_requerido", "La carga debe indicar Content-Length.")
                return
            if int(largo) > self.max_bytes:
                await responder_json(send, 413, "archivo_demasiado_grande",
                                     f"El archivo supera el máximo permitido ({self.max_bytes // 1_048_576} MB).")
                return
        await self.app(scope, receive, send)


# Política de contenido para las páginas (no para /api/docs, que carga Swagger desde un CDN).
# Leaflet y Chart.js se sirven desde /static (Parte 6); las teselas vienen de OpenStreetMap.
CSP_PAGINAS = (
    "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; font-src 'self'; "
    "img-src 'self' data: https://tile.openstreetmap.org https://*.tile.openstreetmap.org; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)


class CabecerasSeguridad:
    CABECERAS = [
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"strict-origin-when-cross-origin"),
        (b"permissions-policy", b"geolocation=(), camera=(), microphone=()"),
    ]

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        ruta = scope.get("path", "")
        privado = ruta.startswith("/api/v1/admin")
        pagina = not ruta.startswith("/api/")

        async def enviar(mensaje):
            if mensaje["type"] == "http.response.start":
                existentes = {k.lower() for k, _ in mensaje.get("headers", [])}
                extra = [(k, v) for k, v in self.CABECERAS if k not in existentes]
                if privado:
                    extra.append((b"cache-control", b"no-store"))
                if pagina and b"content-security-policy" not in existentes:
                    extra.append((b"content-security-policy", CSP_PAGINAS.encode()))
                mensaje = dict(mensaje, headers=list(mensaje.get("headers", [])) + extra)
            await send(mensaje)

        await self.app(scope, receive, enviar)
