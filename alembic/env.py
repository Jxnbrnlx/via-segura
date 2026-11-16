"""Entorno de Alembic. La URL sale de DATABASE_URL (.env) salvo que se fije sqlalchemy.url."""
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import models  # noqa: E402,F401  (registra las tablas en Base.metadata)
from app.config import get_settings  # noqa: E402
from app.database import Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

url = config.get_main_option("sqlalchemy.url") or get_settings().database_url
target_metadata = Base.metadata


def _opciones() -> dict:
    # render_as_batch permite ALTER TABLE en SQLite
    return {"target_metadata": target_metadata, "compare_type": True, "render_as_batch": url.startswith("sqlite")}


def run_migrations_offline() -> None:
    context.configure(url=url, literal_binds=True, dialect_opts={"paramstyle": "named"}, **_opciones())
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    seccion = config.get_section(config.config_ini_section, {})
    seccion["sqlalchemy.url"] = url
    motor = engine_from_config(seccion, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with motor.connect() as conexion:
        context.configure(connection=conexion, **_opciones())
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
