"""Crea, restablece o desactiva una cuenta de administrador. La contraseña se pide por consola (no se
escribe en el historial de comandos ni en ningún archivo).

    python scripts/crear_admin.py --correo admin@ejemplo.org
    python scripts/crear_admin.py --correo admin@ejemplo.org --restablecer
    python scripts/crear_admin.py --correo admin@ejemplo.org --desactivar

Sin consola (Docker): la contraseña se lee de una variable de entorno, nunca de la línea de comandos:
    python scripts/crear_admin.py --correo admin@ejemplo.org --contrasena-env ADMIN_CONTRASENA --si-existe-omitir
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))


def pedir_contrasena() -> str:
    from app.seguridad import validar_politica

    for _ in range(3):
        primera = getpass.getpass("Contraseña (mín. 12 caracteres, letras y números): ")
        errores = validar_politica(primera)
        if errores:
            print("  " + " ".join(errores))
            continue
        if getpass.getpass("Repita la contraseña: ") != primera:
            print("  Las contraseñas no coinciden.")
            continue
        return primera
    raise SystemExit("Demasiados intentos.")


def contrasena_de_entorno(variable: str) -> str:
    from app.seguridad import validar_politica

    valor = os.environ.get(variable, "")
    if not valor:
        raise SystemExit(f"La variable de entorno {variable} está vacía.")
    errores = validar_politica(valor)
    if errores:
        raise SystemExit("La contraseña no cumple la política: " + " ".join(errores))
    return valor


def principal() -> int:
    p = argparse.ArgumentParser(description="Gestiona cuentas de administrador de VÍA SEGURA.")
    p.add_argument("--correo", required=True)
    accion = p.add_mutually_exclusive_group()
    accion.add_argument("--restablecer", action="store_true", help="Cambia la contraseña de una cuenta existente")
    accion.add_argument("--desactivar", action="store_true", help="Impide que la cuenta inicie sesión")
    p.add_argument("--contrasena-env", metavar="VARIABLE",
                   help="Leer la contraseña de esta variable de entorno (uso sin consola, p. ej. Docker)")
    p.add_argument("--si-existe-omitir", action="store_true", help="Si la cuenta ya existe, no hacer nada")
    args = p.parse_args()

    from sqlalchemy import inspect, select

    from app import models
    from app.database import SessionLocal, engine
    from app.schemas.admin import normalizar_correo
    from app.seguridad import hashear_contrasena

    if "usuarios_admin" not in inspect(engine).get_table_names():
        print("La base de datos no tiene las tablas. Ejecute primero:  alembic upgrade head")
        return 1
    try:
        correo = normalizar_correo(args.correo)
    except ValueError:
        print("Correo inválido.")
        return 1

    with SessionLocal() as sesion:
        usuario = sesion.scalar(select(models.UsuarioAdmin).where(models.UsuarioAdmin.correo == correo))
        if args.desactivar:
            if usuario is None:
                print("No existe esa cuenta.")
                return 1
            usuario.activo = False
            sesion.commit()
            print(f"Cuenta {correo} desactivada.")
            return 0
        if usuario is not None and not args.restablecer:
            if args.si_existe_omitir:
                print(f"La cuenta {correo} ya existe; no se modifica.")
                return 0
            print("La cuenta ya existe. Use --restablecer para cambiar la contraseña.")
            return 1
        if usuario is None and args.restablecer:
            print("No existe esa cuenta. Créela sin --restablecer.")
            return 1
        hash_ = hashear_contrasena(contrasena_de_entorno(args.contrasena_env) if args.contrasena_env
                                   else pedir_contrasena())
        if usuario is None:
            sesion.add(models.UsuarioAdmin(correo=correo, hash_contrasena=hash_, rol="admin", activo=True))
            mensaje = f"Administrador {correo} creado."
        else:
            usuario.hash_contrasena, usuario.activo = hash_, True
            mensaje = f"Contraseña de {correo} restablecida."
        sesion.commit()
    print(mensaje)
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
