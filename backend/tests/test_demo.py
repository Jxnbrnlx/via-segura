"""Datos DEMO sintéticos: generador, paso por el importador oficial, carga en SQLite y borrado."""
import collections
import csv
from datetime import date

import pytest

from app.services import calidad, demo
from app.services.mapeos import COLUMNAS_PERSONALES, cargar_mapeo, clave_columna


@pytest.fixture(scope="module")
def datos():
    return demo.generar(n=1200, semilla=7)


def test_es_reproducible_y_cambia_con_la_semilla(datos):
    assert demo.generar(n=1200, semilla=7).siniestros == datos.siniestros
    assert demo.generar(n=1200, semilla=8).siniestros != datos.siniestros


def test_codigos_unicos_y_reconocibles(datos):
    codigos = [s["Codigo_Siniestro"] for s in datos.siniestros]
    assert len(set(codigos)) == len(codigos) == 1200
    assert min(codigos) == demo.PRIMER_CODIGO
    assert all(s["Formulario"].startswith("DEMO") for s in datos.siniestros)


def test_fechas_dentro_del_rango_y_valores_reconocidos(datos):
    fechas = [date.fromisoformat(s["Fecha"]) for s in datos.siniestros]
    assert date(2020, 1, 1) <= min(fechas) and max(fechas) <= date(2025, 12, 31)
    for s in datos.siniestros:
        assert calidad.normalizar_gravedad(s["Gravedad"])
        assert calidad.normalizar_clase(s["Clase"])[1]
        assert s["Localidad"] == "" or calidad.normalizar_localidad(s["Localidad"])
    for a in datos.actores:
        assert calidad.normalizar_estado_persona(a["Estado"]) and calidad.normalizar_sexo(a["Sexo"])
        assert a["Edad"] == "" or 0 <= a["Edad"] <= 110


def test_la_peor_consecuencia_coincide_con_la_gravedad(datos):
    estados = collections.defaultdict(set)
    for a in datos.actores:
        estados[a["Codigo_Siniestro"]].add(a["Estado"])
    for s in datos.siniestros:
        e = estados[s["Codigo_Siniestro"]]
        if s["Gravedad"] == "Con Muertos":
            assert "MUERTO" in e
        elif s["Gravedad"] == "Con Heridos":
            assert "HERIDO" in e and "MUERTO" not in e
        else:
            assert e == {"ILESO"}


def test_personas_y_vehiculos_unicos_por_clave(datos):
    llaves = [(a["Codigo_Siniestro"], a["Codigo_Vehiculo"], a["Consecutivo"]) for a in datos.actores]
    assert len(llaves) == len(set(llaves))
    vehiculos = [(v["Codigo_Siniestro"], v["Codigo_Vehiculo"]) for v in datos.vehiculos]
    assert len(vehiculos) == len(set(vehiculos))
    atropellos = {s["Codigo_Siniestro"] for s in datos.siniestros if s["Clase"] == "Atropello"}
    peatones = {a["Codigo_Siniestro"] for a in datos.actores if a["Condicion"] == "PEATON"}
    assert atropellos == peatones


def test_incluye_casos_de_calidad_para_la_demostracion(datos):
    assert any(s["Latitud"] == "" for s in datos.siniestros)          # sin coordenada
    assert any(s["Latitud"] == "4.582000" for s in datos.siniestros)  # fuera de Bogotá
    assert any(s["Localidad"] == "" for s in datos.siniestros)
    assert any(s["Hora"] == "" for s in datos.siniestros)
    con_coordenada = [s for s in datos.siniestros if s["Latitud"] not in ("", "4.582000", "0.000000")]
    assert all(4.4 < float(s["Latitud"]) < 4.85 and -74.25 < float(s["Longitud"]) < -73.98 for s in con_coordenada)


def test_csv_coincide_con_el_mapeo_y_sin_columnas_personales(datos, tmp_path):
    rutas = demo.escribir_csv(datos, tmp_path)
    mapeo = cargar_mapeo(demo.CODIGO_MAPEO)
    assert mapeo.fuente_codigo == demo.CODIGO_FUENTE
    for tipo, ruta in rutas.items():
        with open(ruta, encoding="utf-8", newline="") as f:
            encabezado = next(csv.reader(f))
        assert not {clave_columna(c) for c in encabezado} & COLUMNAS_PERSONALES
        for campo, candidatas in mapeo.hojas[tipo].campos.items():
            assert set(candidatas) & set(encabezado), (tipo, campo)


def test_parametros_invalidos():
    with pytest.raises(ValueError):
        demo.generar(n=0)
    with pytest.raises(ValueError):
        demo.generar(desde=date(2025, 1, 2), hasta=date(2025, 1, 1))


def test_pasa_por_el_importador_oficial(datos, tmp_path):
    from app.services.archivos import recibir_archivo
    from app.services.importador_excel import ImportadorArchivos
    from tests.repositorio_memoria import RepositorioMemoria

    rutas = demo.escribir_csv(demo.generar(n=400, semilla=3), tmp_path / "csv")
    repo = RepositorioMemoria()
    imp = ImportadorArchivos(repo, tmp_path / "cargas", tmp_path / "geo", hoy=date(2026, 11, 16), bloque=100)
    for tipo in ("siniestros", "actores", "vehiculos"):
        with open(rutas[tipo], "rb") as flujo:
            recibido = recibir_archivo(flujo, rutas[tipo].name, "text/csv", tmp_path / "cargas", max_bytes=2**24)
        pv = imp.previsualizar(recibido, tipo=tipo, mapeo_codigo=demo.CODIGO_MAPEO)
        assert pv.puede_confirmar, pv.advertencias
        r = imp.confirmar(pv.importacion_id)
        assert r.estado == "completada" and r.filas_rechazadas == 0, r.mensaje
    siniestros = repo.siniestros()
    assert len(siniestros) == 400
    assert sum(len(s["actores"]) for s in siniestros) > 400
    assert {s["fuente_id"] for s in siniestros} == {repo.obtener_fuente(demo.CODIGO_FUENTE).id}


def test_carga_y_borrado_en_sqlite_sin_tocar_otras_fuentes(tmp_path):
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select

    from app import models
    from app.main import create_app
    from tests.api_comun import preparar

    motor, fabrica, cfg = preparar(tmp_path, con_admin=False)
    with fabrica() as s:
        antes = s.scalar(select(func.count()).select_from(models.SiniestroEvento))
        demo.cargar_demo(s, cfg, n=300, semilla=5, hoy=date(2026, 11, 16))
        # Repetir la carga no duplica: actualiza los mismos códigos.
        demo.cargar_demo(s, cfg, n=300, semilla=5, hoy=date(2026, 11, 16))
        assert s.scalar(select(func.count()).select_from(models.SiniestroEvento)) == antes + 300

    with TestClient(create_app(cfg, fabrica, ejecutor_sync=lambda **kw: None)) as c:
        fuentes = {f["codigo"]: f for f in c.get("/api/v1/sources").json()["datos"]}
        assert fuentes["demo_sintetica"]["registros"] == 300 and "DEMO" in fuentes["demo_sintetica"]["nombre"]
        assert not fuentes["demo_sintetica"]["por_defecto"]
        r = c.get("/api/v1/dashboard/summary", params={"fuente": "demo_sintetica", "gravedad": "todas"}).json()
        assert r["periodo"]["registros"] == 300
        assert c.get("/api/v1/dashboard/summary").json()["fuente"]["codigo"] == "arcgis_simur_accidentalidad"

    with fabrica() as s:
        assert demo.borrar_demo(s) == 300
        assert s.scalar(select(func.count()).select_from(models.SiniestroEvento)) == antes
        assert s.scalar(select(func.count()).select_from(models.ActorVial)
                        .join(models.SiniestroEvento).where(models.SiniestroEvento.id_registro >= demo.PRIMER_CODIGO)) == 0
        assert demo.borrar_demo(s) == 0
    motor.dispose()
