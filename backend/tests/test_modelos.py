"""Reglas críticas de integridad a nivel de base de datos."""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import models
from tests.conftest import nuevo_siniestro


def test_no_duplica_registro_en_la_misma_fuente(sesion, fuente):
    sesion.add_all([nuevo_siniestro(fuente.id, 10), nuevo_siniestro(fuente.id, 10)])
    with pytest.raises(IntegrityError):
        sesion.commit()


def test_mismo_id_en_fuentes_distintas_es_valido(sesion, fuente):
    otra = models.FuenteDatos(codigo="otra", entidad="X", nombre="Otra", formato="json")
    sesion.add(otra)
    sesion.commit()
    sesion.add_all([nuevo_siniestro(fuente.id, 10), nuevo_siniestro(otra.id, 10)])
    sesion.commit()


def test_coordenada_valida_exige_latitud_y_longitud(sesion, fuente):
    sesion.add(nuevo_siniestro(fuente.id, 1, coordenada_valida=True, motivo_coordenada=None))
    with pytest.raises(IntegrityError):
        sesion.commit()


def test_coordenada_invalida_exige_motivo(sesion, fuente):
    sesion.add(nuevo_siniestro(fuente.id, 1, coordenada_valida=False, motivo_coordenada=None))
    with pytest.raises(IntegrityError):
        sesion.commit()


def test_coordenada_valida_completa_se_acepta(sesion, fuente):
    sesion.add(nuevo_siniestro(fuente.id, 1, coordenada_valida=True, motivo_coordenada=None,
                               latitud=4.6, longitud=-74.1))
    sesion.commit()


def test_latitud_fuera_de_rango_se_rechaza(sesion, fuente):
    sesion.add(nuevo_siniestro(fuente.id, 1, latitud=95.0, longitud=-74.1))
    with pytest.raises(IntegrityError):
        sesion.commit()


def test_gravedad_solo_admite_categorias_conocidas(sesion, fuente):
    sesion.add(nuevo_siniestro(fuente.id, 1, gravedad="Muy grave"))
    with pytest.raises(IntegrityError):
        sesion.commit()


def test_edad_atipica_no_se_acepta(sesion, fuente):
    s = nuevo_siniestro(fuente.id, 1)
    s.actores.append(models.ActorVial(codigo_vehiculo=1, consecutivo_victima=0, estado="HERIDO", edad=2021))
    sesion.add(s)
    with pytest.raises(IntegrityError):
        sesion.commit()


def test_estado_de_persona_valido(sesion, fuente):
    s = nuevo_siniestro(fuente.id, 1)
    s.actores.append(models.ActorVial(codigo_vehiculo=1, consecutivo_victima=0, estado="DESCONOCIDO"))
    sesion.add(s)
    with pytest.raises(IntegrityError):
        sesion.commit()


def test_eliminar_siniestro_elimina_sus_personas_y_vehiculos(sesion, fuente):
    s = nuevo_siniestro(fuente.id, 1)
    s.actores.append(models.ActorVial(codigo_vehiculo=1, consecutivo_victima=0, estado="ILESO"))
    s.vehiculos.append(models.VehiculoEvento(codigo_vehiculo=1, clase="Automovil"))
    sesion.add(s)
    sesion.commit()
    sesion.delete(s)
    sesion.commit()
    assert sesion.scalars(select(models.ActorVial)).all() == []
    assert sesion.scalars(select(models.VehiculoEvento)).all() == []


def test_el_modelo_no_almacena_datos_personales_sensibles():
    columnas = {c.name for t in models.Base.metadata.tables.values() for c in t.columns}
    prohibidas = {"placa", "fecha_nacimiento", "nombre_victima", "documento", "codigo_accidentado"}
    assert columnas.isdisjoint(prohibidas)
