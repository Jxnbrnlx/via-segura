"""Importador contra la base de datos real (SQLite temporal). Datos SINTÉTICOS de prueba."""
import io
from datetime import date

from sqlalchemy import func, select

from app import models
from app.services.archivos import recibir_archivo
from app.services.importador_excel import ImportadorArchivos
from app.services.repositorio_sql import RepositorioSQL
from tests.test_importador import ENC_ACTOR, fila_2025, siniestros_csv


def importador(sesion, tmp_path):
    return ImportadorArchivos(RepositorioSQL(sesion), tmp_path / "cargas", tmp_path / "geo",
                              hoy=date(2026, 11, 16), bloque=2)


def subir(tmp_path, texto, nombre="datos.csv"):
    return recibir_archivo(io.BytesIO(texto.encode("utf-8")), nombre, "text/csv", tmp_path / "cargas",
                           max_bytes=2**20)


def contar(sesion, modelo):
    return sesion.scalar(select(func.count()).select_from(modelo))


def importar(imp, tmp_path, texto, tipo, mapeo):
    pv = imp.previsualizar(subir(tmp_path, texto), tipo=tipo, mapeo_codigo=mapeo)
    return pv, imp.confirmar(pv.importacion_id)


def test_flujo_completo_anuario(sesion, tmp_path):
    imp = importador(sesion, tmp_path)
    pv, r = importar(imp, tmp_path, siniestros_csv(fila_2025(1), fila_2025(2, lat="", lon=""), fila_2025(3)),
                     "siniestros", "anuario_sdm_2025")
    assert r.estado == "completada", r.mensaje
    registro = sesion.get(models.Importacion, pv.importacion_id)
    sesion.refresh(registro)
    assert registro.estado == "completada" and registro.tipo == "excel" and registro.modo == "siniestros"
    assert registro.filas_validas == 3 and registro.fecha_max_evento == date(2025, 9, 2)
    sin_coord = sesion.scalars(select(models.SiniestroEvento).where(models.SiniestroEvento.id_registro == 2)).one()
    assert sin_coord.latitud is None and sin_coord.motivo_coordenada == "sin_coordenada"

    actores = ENC_ACTOR + "\n1,1,0,CONDUCTOR,HERIDO,Masculino,34,\n1,,1,PEATON,MUERTO,Femenino,70,\n2,1,0,X,ILESO,,,\n"
    _, r = importar(imp, tmp_path, actores, "actores", "anuario_sdm_2025")
    assert r.estado == "completada", r.mensaje
    assert contar(sesion, models.ActorVial) == 3

    # Reimportar siniestros conserva las personas; reimportar personas no las duplica.
    importar(imp, tmp_path, siniestros_csv(fila_2025(1), fila_2025(2, lat="", lon=""), fila_2025(3)),
             "siniestros", "anuario_sdm_2025")
    importar(imp, tmp_path, actores, "actores", "anuario_sdm_2025")
    assert contar(sesion, models.SiniestroEvento) == 3 and contar(sesion, models.ActorVial) == 3

    vehiculos = "Codigo_Siniestro,Codigo_Vehiculo,Clase,Placa\n1,1,AUTOMOVIL,ABC123\n3,1,BUS,\n"
    _, r = importar(imp, tmp_path, vehiculos, "vehiculos", "anuario_sdm_2025")
    assert r.filas_validas == 2 and contar(sesion, models.VehiculoEvento) == 2


def test_poblacion_en_denominadores(sesion, tmp_path):
    imp = importador(sesion, tmp_path)
    texto = ("ANO;CODIGO_LOCALIDAD;NOMBRE_LOCALIDAD;POBLACION\n2025;0;Bogotá;70\n2025;1;Usaquén;30\n"
             "2025;17;La Candelaria;40\n")
    _, r = importar(imp, tmp_path, texto, "poblacion", "poblacion_osb_localidad")
    assert r.estado == "completada", r.mensaje
    filas = {(d.localidad, d.anio): d.poblacion for d in sesion.scalars(select(models.DenominadorOficial))}
    assert filas == {("BOGOTA", 2025): 70, ("USAQUEN", 2025): 30, ("CANDELARIA", 2025): 40}
    # reimportar actualiza, no duplica
    importar(imp, tmp_path, texto.replace(";30", ";31"), "poblacion", "poblacion_osb_localidad")
    assert contar(sesion, models.DenominadorOficial) == 3
    assert sesion.scalar(select(models.DenominadorOficial.poblacion)
                         .where(models.DenominadorOficial.localidad == "USAQUEN")) == 31
