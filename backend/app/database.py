"""Motor, sesión y base declarativa (con convención de nombres para Alembic)."""
from collections.abc import Iterator

from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

CONVENCION_NOMBRES = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=CONVENCION_NOMBRES)


def crear_motor(url: str) -> Engine:
    """Crea un motor. En SQLite activa las claves foráneas (vienen desactivadas por defecto)."""
    es_sqlite = url.startswith("sqlite")
    motor = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False} if es_sqlite else {},
    )
    if es_sqlite:

        @event.listens_for(motor, "connect")
        def _activar_fk(conexion, _registro):
            cursor = conexion.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return motor


engine = crear_motor(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """Dependencia de FastAPI: una sesión por petición."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
