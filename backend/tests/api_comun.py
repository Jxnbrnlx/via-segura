"""Aplicación de prueba con base SQLite temporal y datos SINTÉTICOS (DEMOSTRACIÓN, no son cifras reales)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import models
from app.config import Configuracion
from app.database import Base, crear_motor
from app.services.repositorio_sql import sembrar_fuentes

SECRETO = "clave-de-prueba-" + "x" * 40
CORREO, CONTRASENA = "admin@prueba.org", "clave-segura-2026"


def _fuente(s, codigo) -> int:
    return s.scalar(select(models.FuenteDatos.id).where(models.FuenteDatos.codigo == codigo))


def _siniestro(fuente_id, id_registro, fecha, localidad, gravedad, clase, hora, lat=None, lon=None,
               motivo=None, **extra):
    valida = lat is not None and motivo is None
    return models.SiniestroEvento(
        fuente_id=fuente_id, id_registro=id_registro, fecha_evento=fecha, anio=fecha.year, mes=fecha.month,
        dia_semana=("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")[fecha.weekday()],
        hora=hora, minuto=0 if hora is not None else None, localidad=localidad, gravedad=gravedad,
        clase_siniestro=clase, latitud=lat, longitud=lon, coordenada_valida=valida,
        motivo_coordenada=None if valida else (motivo or "sin_coordenada"), formulario=f"SECRETO{id_registro}",
        direccion=f"AV PRUEBA {id_registro}", **extra)


def cargar_demo(s) -> None:
    sembrar_fuentes(s)
    s.flush()
    arcgis, a2025, pob = (_fuente(s, c) for c in ("arcgis_simur_accidentalidad", "anuario_sdm_2025",
                                                   "poblacion_osb_localidad"))
    s1 = _siniestro(arcgis, 1, date(2025, 3, 1), "KENNEDY", "Con Heridos", "Choque", 8, 4.63, -74.15)
    s1.actores += [models.ActorVial(codigo_vehiculo=1, consecutivo_victima=0, estado="HERIDO", condicion="CONDUCTOR",
                                    sexo="MASCULINO", edad=40, rango_edad="29-59"),
                   models.ActorVial(codigo_vehiculo=1, consecutivo_victima=1, estado="ILESO", condicion="PASAJERO")]
    s2 = _siniestro(arcgis, 2, date(2025, 3, 2), "KENNEDY", "Con Muertos", "Atropello", 22, 4.631, -74.1505)
    s2.actores += [models.ActorVial(codigo_vehiculo=None, consecutivo_victima=0, estado="MUERTO", condicion="PEATON",
                                    sexo="FEMENINO", edad=70, rango_edad="60+"),
                   models.ActorVial(codigo_vehiculo=1, consecutivo_victima=1, estado="ILESO", condicion="CONDUCTOR")]
    s3 = _siniestro(arcgis, 3, date(2025, 4, 10), "SUBA", "Solo Daños", "Choque", None)
    s3.actores.append(models.ActorVial(codigo_vehiculo=1, consecutivo_victima=0, estado="ILESO", condicion="CONDUCTOR"))
    s4 = _siniestro(arcgis, 4, date(2024, 12, 31), "USAQUEN", "Con Heridos", "Choque", 14, 4.70, -74.03,
                    barrio="BARRIO DEMO")
    s4.actores.append(models.ActorVial(codigo_vehiculo=1, consecutivo_victima=0, estado="HERIDO",
                                       condicion="MOTOCICLISTA", sexo="MASCULINO", edad=23, rango_edad="18-28"))
    s4.vehiculos.append(models.VehiculoEvento(codigo_vehiculo=1, clase="MOTOCICLETA", servicio="PARTICULAR"))
    s4.causas.append(models.CausaEvento(codigo_vehiculo=1, codigo_causa="102", nombre="CAUSA DEMO"))
    s5 = _siniestro(arcgis, 5, date(2025, 5, 5), None, "Con Heridos", "Choque", 10, 4.0, -74.2, motivo="sospechosa")
    s6 = _siniestro(a2025, 1, date(2025, 3, 1), "BOSA", "Con Heridos", "Choque", 9, 4.61, -74.19)
    s.add_all([s1, s2, s3, s4, s5, s6])
    s.add_all([models.DenominadorOficial(fuente_id=pob, localidad="KENNEDY", anio=2025, poblacion=1_000_000),
               models.DenominadorOficial(fuente_id=pob, localidad="BOGOTA", anio=2025, poblacion=8_000_000)])
    s.commit()


def preparar(tmp_path, *, limite_login: int = 1000, con_admin: bool = True):
    motor = crear_motor(f"sqlite:///{(tmp_path / 'api.db').as_posix()}")
    Base.metadata.create_all(motor)
    fabrica = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)
    with fabrica() as s:
        cargar_demo(s)
        if con_admin:
            from app.seguridad import hashear_contrasena

            s.add(models.UsuarioAdmin(correo=CORREO, hash_contrasena=hashear_contrasena(CONTRASENA)))
            s.commit()
    cfg = Configuracion(
        entorno="desarrollo", database_url=f"sqlite:///{(tmp_path / 'api.db').as_posix()}", secret_key=SECRETO,
        carga_directorio=tmp_path / "cargas", geo_directorio=tmp_path / "geo", limite_peticiones_por_minuto=10_000,
        limite_login_por_minuto=limite_login, cors_origenes="http://localhost:8000", importar_bloque=100)
    return motor, fabrica, cfg
