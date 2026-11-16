"""La migración 0001 debe producir exactamente el esquema de los modelos."""
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from app.config import RAIZ
from app.database import Base, crear_motor


def _config(url: str) -> Config:
    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_upgrade_head_coincide_con_los_modelos(tmp_path):
    url = f"sqlite:///{(tmp_path / 'mig.db').as_posix()}"
    command.upgrade(_config(url), "head")
    motor = crear_motor(url)
    try:
        assert "siniestros_evento" in inspect(motor).get_table_names()
        with motor.connect() as con:
            diferencias = compare_metadata(MigrationContext.configure(con, opts={"compare_type": False}), Base.metadata)
        assert diferencias == [], diferencias
    finally:
        motor.dispose()


def test_downgrade_base_deja_solo_la_tabla_de_version(tmp_path):
    url = f"sqlite:///{(tmp_path / 'mig2.db').as_posix()}"
    cfg = _config(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    motor = crear_motor(url)
    try:
        assert set(inspect(motor).get_table_names()) <= {"alembic_version"}
    finally:
        motor.dispose()
