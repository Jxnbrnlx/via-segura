"""Contraseñas (bcrypt) y sesiones de administrador (JWT HS256).

- bcrypt solo admite 72 bytes: contraseñas más largas se rechazan (no se truncan en silencio).
- Política mínima: 12 caracteres, con letras y números.
- Los tokens llevan sub (id del administrador, como texto), rol, iat y exp. Se verifican firma y
  vencimiento; además, en cada petición se comprueba que el administrador siga activo.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import jwt

ALGORITMO = "HS256"
MAX_BYTES_BCRYPT = 72
LARGO_MINIMO = 12
_HASH_FICTICIO: str | None = None


class ErrorToken(Exception):
    pass


def validar_politica(contrasena: str) -> list[str]:
    errores = []
    if len(contrasena) < LARGO_MINIMO:
        errores.append(f"Debe tener al menos {LARGO_MINIMO} caracteres.")
    if len(contrasena.encode("utf-8")) > MAX_BYTES_BCRYPT:
        errores.append(f"No puede superar {MAX_BYTES_BCRYPT} bytes (límite de bcrypt).")
    if not re.search(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]", contrasena) or not re.search(r"\d", contrasena):
        errores.append("Debe combinar letras y números.")
    return errores


def hashear_contrasena(contrasena: str) -> str:
    import bcrypt  # importación diferida

    errores = validar_politica(contrasena)
    if errores:
        raise ValueError(" ".join(errores))
    return bcrypt.hashpw(contrasena.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verificar_contrasena(contrasena: str, hash_guardado: str | None) -> bool:
    """Siempre ejecuta bcrypt (también si el usuario no existe) para no revelar por el tiempo de respuesta
    qué correos están registrados."""
    import bcrypt

    global _HASH_FICTICIO
    if _HASH_FICTICIO is None:
        _HASH_FICTICIO = bcrypt.hashpw(b"contrasena-ficticia-123", bcrypt.gensalt(rounds=12)).decode("ascii")
    datos = contrasena.encode("utf-8")
    if len(datos) > MAX_BYTES_BCRYPT:
        return False
    try:
        valido = bcrypt.checkpw(datos, (hash_guardado or _HASH_FICTICIO).encode("ascii"))
    except ValueError:
        return False
    return valido and hash_guardado is not None


def crear_token(usuario_id: int, rol: str, secreto: str, minutos: int,
                ahora: datetime | None = None) -> tuple[str, datetime]:
    ahora = ahora or datetime.now(timezone.utc)
    expira = ahora + timedelta(minutes=minutos)
    datos = {"sub": str(usuario_id), "rol": rol, "iat": int(ahora.timestamp()), "exp": int(expira.timestamp())}
    return jwt.encode(datos, secreto, algorithm=ALGORITMO), expira


def decodificar_token(token: str, secreto: str) -> dict:
    try:
        datos = jwt.decode(token, secreto, algorithms=[ALGORITMO], options={"require": ["exp", "iat", "sub"]})
    except jwt.ExpiredSignatureError as exc:
        raise ErrorToken("La sesión venció; inicie sesión de nuevo.") from exc
    except jwt.InvalidTokenError as exc:
        raise ErrorToken("Token inválido.") from exc
    if not str(datos.get("sub", "")).isdigit():
        raise ErrorToken("Token inválido.")
    return datos
