from datetime import date

import pytest
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base, crear_motor


@pytest.fixture
def sesion(tmp_path):
    motor = crear_motor(f"sqlite:///{(tmp_path / 'prueba.db').as_posix()}")
    Base.metadata.create_all(motor)
    with sessionmaker(bind=motor, autoflush=False)() as s:
        yield s
    motor.dispose()


@pytest.fixture
def fuente(sesion):
    f = models.FuenteDatos(codigo="fuente_prueba", entidad="Prueba", nombre="Fuente de prueba", formato="xlsx")
    sesion.add(f)
    sesion.commit()
    return f


def nuevo_siniestro(fuente_id, id_registro=1, **extra):
    """Siniestro mínimo válido (datos de PRUEBA, no oficiales)."""
    base = dict(
        fuente_id=fuente_id, id_registro=id_registro, fecha_evento=date(2025, 1, 2), anio=2025,
        coordenada_valida=False, motivo_coordenada="sin_coordenada",
    )
    base.update(extra)
    return models.SiniestroEvento(**base)
