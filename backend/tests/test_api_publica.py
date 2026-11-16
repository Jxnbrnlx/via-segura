"""API pública con FastAPI TestClient y datos SINTÉTICOS (ver api_comun.py)."""
import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.api_comun import preparar


@pytest.fixture
def cliente(tmp_path):
    motor, fabrica, cfg = preparar(tmp_path, con_admin=False)
    with TestClient(create_app(cfg, fabrica, ejecutor_sync=lambda **kw: None)) as c:
        c.cfg = cfg
        yield c
    motor.dispose()


def test_health(cliente):
    assert cliente.get("/api/v1/health").json() == {"estado": "ok", "base_de_datos": "ok", "version": "0.7.0"}


def test_fuentes(cliente):
    datos = {f["codigo"]: f for f in cliente.get("/api/v1/sources").json()["datos"]}
    assert datos["arcgis_simur_accidentalidad"]["registros"] == 5 and datos["arcgis_simur_accidentalidad"]["por_defecto"]
    assert datos["anuario_sdm_2025"]["registros"] == 1
    assert datos["poblacion_osb_localidad"]["tipo"] == "denominador" and datos["poblacion_osb_localidad"]["registros"] == 2


def test_resumen_por_defecto_cuenta_heridos_o_muertos_y_separa_personas(cliente):
    r = cliente.get("/api/v1/dashboard/summary").json()
    kpis = {k["clave"]: k for k in r["datos"]["kpis"]}
    assert kpis["siniestros"]["valor"] == 4 and kpis["siniestros"]["unidad"] == "siniestros"
    assert kpis["siniestros_con_muertos"]["valor"] == 1
    assert kpis["personas_heridas"]["valor"] == 2 and kpis["personas_heridas"]["derivado"] == "actor vial"
    assert kpis["personas_fallecidas"]["valor"] == 1 and kpis["personas_fallecidas"]["unidad"] == "personas"
    assert r["datos"]["solo_danos_aparte"]["valor"] == 1
    assert r["datos"]["coordenadas"] == {"validas": 3, "sin_coordenada_valida": 1}
    assert r["fuente"]["codigo"] == "arcgis_simur_accidentalidad"
    assert r["periodo"] == {"inicio": "2024-12-31", "fin": "2025-05-05", "registros": 4}
    assert r["filtros"]["gravedad_por_defecto"] is True
    assert any("Solo Daños" in a for a in r["advertencias"])
    assert r["datos"]["tasa_siniestros"]["disponible"] is False      # falta población 2024
    assert "Falta población" in r["datos"]["tasa_siniestros"]["motivo"]


def test_tasa_con_denominador_oficial(cliente):
    tasa = cliente.get("/api/v1/dashboard/summary", params={"anio": 2025}).json()["datos"]["tasa_siniestros"]
    assert tasa["disponible"] and tasa["numerador"] == 3 and tasa["denominador"] == 8_000_000
    assert tasa["valor"] == pytest.approx(0.04) and "100.000" in tasa["unidad"] and tasa["formula"]
    assert tasa["fuente_denominador"]["codigo"] == "poblacion_osb_localidad"


def test_las_fuentes_no_se_mezclan(cliente):
    r = cliente.get("/api/v1/dashboard/summary", params={"fuente": "anuario_2025"}).json()
    assert r["fuente"]["codigo"] == "anuario_sdm_2025"
    assert {k["clave"]: k["valor"] for k in r["datos"]["kpis"]}["siniestros"] == 1
    assert r["datos"]["personas"] is None and any("Actor vial" in a for a in r["advertencias"])


def test_gravedad_todas_y_filtros_combinados(cliente):
    def total(**p):
        return cliente.get("/api/v1/accidents", params=p).json()["paginacion"]["total"]
    assert total(gravedad="todas") == 5
    assert total(gravedad="Solo Daños") == 1
    assert total(localidad="Kennedy", mes=3) == 2
    assert total(localidad=["kennedy", "Usaquén"], anio=2025) == 2
    assert total(clase="ATROPELLO") == 1
    assert total(fecha_desde="2025-03-02", fecha_hasta="2025-04-30", gravedad="todas") == 2


@pytest.mark.parametrize("params, campo", [({"localidad": "Soacha"}, "localidad"), ({"mes": 13}, "mes"),
                                          ({"gravedad": "grave"}, "gravedad"), ({"tamano": 500}, "tamano"),
                                          ({"fecha_desde": "2025-02-01", "fecha_hasta": "2025-01-01"}, None)])
def test_parametros_invalidos_dan_error_json(cliente, params, campo):
    r = cliente.get("/api/v1/accidents", params=params)
    assert r.status_code == 422
    error = r.json()["error"]
    assert error["codigo"] == "parametros_invalidos" and error["mensaje"]
    if campo:
        assert any(campo in (d["campo"] or "") for d in error["detalles"])


def test_fuente_invalida(cliente):
    r = cliente.get("/api/v1/dashboard/summary", params={"fuente": "poblacion_osb_localidad"})
    assert r.status_code == 400 and r.json()["error"]["codigo"] == "fuente_invalida"


def test_tabla_paginada_sin_datos_internos(cliente):
    r = cliente.get("/api/v1/accidents", params={"tamano": 2}).json()
    assert r["paginacion"] == {"pagina": 1, "tamano": 2, "total": 4, "paginas": 2}
    primero = r["datos"][0]
    assert primero["id_registro"] == 5 and primero["latitud"] is None and primero["coordenada_valida"] is False
    assert primero["motivo_sin_coordenada"] == "sospechosa"
    texto = json.dumps(r)
    assert "SECRETO" not in texto and "formulario" not in texto and '"edad"' not in texto
    kennedy = cliente.get("/api/v1/accidents", params={"orden": "fecha", "localidad": "KENNEDY"}).json()["datos"]
    assert [s["id_registro"] for s in kennedy] == [1, 2]
    assert kennedy[0]["personas"] == {"heridas": 1, "fallecidas": 0, "ilesas": 1, "derivado": "actor vial"}


def test_busqueda_y_orden(cliente):
    assert [s["id_registro"] for s in cliente.get("/api/v1/accidents", params={"q": "prueba 4"}).json()["datos"]] == [4]
    assert cliente.get("/api/v1/accidents", params={"orden": "placa"}).status_code == 400
    assert cliente.get("/api/v1/accidents", params={"q": "%"}).json()["paginacion"]["total"] == 0


def test_detalle_sin_datos_personales(cliente):
    d = cliente.get("/api/v1/accidents/4").json()["datos"]
    assert d["personas"] == [{"condicion": "MOTOCICLISTA", "estado": "HERIDO", "sexo": "MASCULINO", "rango_edad": "18-28",
                              "codigo_vehiculo": 1, "muerte_posterior": None}]
    assert d["vehiculos"][0]["clase"] == "MOTOCICLETA" and d["causas"][0]["codigo_causa"] == "102"
    assert d["barrio"] == "BARRIO DEMO"
    assert cliente.get("/api/v1/accidents/999").status_code == 404


def test_geojson_solo_coordenadas_validas(cliente):
    r = cliente.get("/api/v1/accidents/geojson").json()
    assert r["type"] == "FeatureCollection" and len(r["features"]) == 3
    assert {f["properties"]["id_registro"] for f in r["features"]} == {1, 2, 4}
    assert r["features"][0]["geometry"]["coordinates"][0] < -70  # [longitud, latitud]
    assert r["metadatos"]["sin_coordenada_valida"] == 1 and r["metadatos"]["fuente"]["codigo"]
    assert any("no tienen coordenada válida" in a for a in r["metadatos"]["advertencias"])
    todas = cliente.get("/api/v1/accidents/geojson", params={"gravedad": "todas"}).json()
    assert len(todas["features"]) == 3 and todas["metadatos"]["sin_coordenada_valida"] == 2
    corto = cliente.get("/api/v1/accidents/geojson", params={"limite": 1}).json()["metadatos"]
    assert corto["truncado"] is True and corto["devueltos"] == 1
    caja = cliente.get("/api/v1/accidents/geojson", params={"bbox": "-74.05,4.69,-74.0,4.71"}).json()
    assert [f["properties"]["id_registro"] for f in caja["features"]] == [4]
    assert cliente.get("/api/v1/accidents/geojson", params={"bbox": "1,2,3"}).status_code == 422


def test_por_localidad_con_tasa_y_texto_neutral(cliente):
    r = cliente.get("/api/v1/analytics/by-locality", params={"anio": 2025}).json()
    filas = {f["localidad"]: f for f in r["datos"]["localidades"]}
    assert r["datos"]["localidades"][0]["localidad"] == "KENNEDY"
    assert filas["KENNEDY"]["siniestros"] == 2 and filas["KENNEDY"]["personas_fallecidas"] == 1
    assert filas["KENNEDY"]["tasa_siniestros"]["valor"] == pytest.approx(0.2)
    assert filas["SUBA"]["tasa_siniestros"]["disponible"] is False
    assert r["datos"]["sin_localidad"] == 1
    assert "peligros" not in json.dumps(r, ensure_ascii=False).lower()
    assert any("no necesariamente mayor riesgo" in a for a in r["advertencias"])


def test_series_y_matrices(cliente):
    serie = cliente.get("/api/v1/analytics/by-period").json()["datos"]["serie"]
    assert [(p["periodo"], p["siniestros"]) for p in serie] == [("2024", 1), ("2025", 3)]
    assert serie[1]["personas_fallecidas"] == 1
    meses = cliente.get("/api/v1/analytics/by-period", params={"agrupacion": "mes"}).json()["datos"]["serie"]
    assert [p["periodo"] for p in meses] == ["2024-12", "2025-03", "2025-05"]
    assert cliente.get("/api/v1/analytics/by-period", params={"agrupacion": "semana"}).status_code == 422
    hd = cliente.get("/api/v1/analytics/by-hour-day", params={"gravedad": "todas"}).json()["datos"]
    assert hd["sin_hora"] == 1 and len(hd["matriz"]) == 7
    sabado = next(m for m in hd["matriz"] if m["dia"] == "sábado")  # 2025-03-01 fue sábado
    assert sabado["conteos"][8] == 1


def test_por_actor_y_filtro_de_actor(cliente):
    grupos = {g["valor"]: g for g in cliente.get("/api/v1/analytics/by-actor").json()["datos"]["grupos"]}
    assert grupos["PEATON"]["fallecidas"] == 1 and grupos["CONDUCTOR"]["personas"] == 2
    edades = cliente.get("/api/v1/analytics/by-actor", params={"dimension": "rango_edad"}).json()["datos"]["grupos"]
    assert {g["valor"] for g in edades} >= {"60+", "18-28"}
    r = cliente.get("/api/v1/dashboard/summary", params={"actor": "Peatón"}).json()
    kpis = {k["clave"]: k["valor"] for k in r["datos"]["kpis"]}
    assert kpis["siniestros"] == 1 and kpis["personas_fallecidas"] == 1 and kpis["personas_heridas"] == 0


def test_gravedad_y_clase(cliente):
    d = cliente.get("/api/v1/analytics/by-severity").json()["datos"]
    assert d["siniestros_por_gravedad"] == {"Con Heridos": 3, "Con Muertos": 1}
    assert d["solo_danos_aparte"]["valor"] == 1 and d["personas_por_estado"]["fallecidas"] == 1
    clases = cliente.get("/api/v1/analytics/by-class").json()["datos"]["clases"]
    assert clases[0] == {"clase": "Choque", "siniestros": 3}


def test_concentracion_por_celdas(cliente):
    d = cliente.get("/api/v1/analytics/concentration").json()["datos"]
    assert d["tamano_celda_m"] == 250 and d["registros_con_coordenada_valida"] == 3
    assert d["celdas"][0]["conteo"] == 2  # los dos siniestros de Kennedy caen en la misma celda
    c = d["celdas"][0]
    assert c["lat_min"] <= 4.63 <= c["lat_max"] and c["lon_min"] <= -74.15 <= c["lon_max"]
    assert "puntos" not in json.dumps(d)
    assert len(cliente.get("/api/v1/analytics/concentration", params={"minimo": 2}).json()["datos"]["celdas"]) == 1
    assert cliente.get("/api/v1/analytics/concentration", params={"tamano_celda_m": 50}).status_code == 422


def test_mapa_por_localidad_sin_y_con_poligonos(cliente):
    r = cliente.get("/api/v1/localities/geojson").json()
    assert r["metadatos"]["tipo_geometria"] == "centroide_de_puntos_reales"
    por = {f["properties"]["localidad"]: f for f in r["features"]}
    assert set(por) == {"KENNEDY", "USAQUEN"} and por["KENNEDY"]["geometry"]["type"] == "Point"
    assert any("no es un límite oficial" in a.lower() for a in r["metadatos"]["advertencias"])
    geo = cliente.cfg.geo_directorio
    geo.mkdir(parents=True, exist_ok=True)
    (geo / "localidades.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"localidad": "KENNEDY", "nombre": "Kennedy", "codigo": 8},
         "geometry": {"type": "MultiPolygon", "coordinates": [[[[-74.2, 4.6], [-74.1, 4.6], [-74.1, 4.7], [-74.2, 4.6]]]]}}]}),
        encoding="utf-8")
    r = cliente.get("/api/v1/localities/geojson").json()
    assert r["metadatos"]["tipo_geometria"] == "poligonos_oficiales"
    assert r["features"][0]["properties"]["siniestros"] == 2


def test_metadatos_de_campos(cliente):
    d = cliente.get("/api/v1/metadata/fields").json()["datos"]
    dims = {x["clave"]: x for x in d["dimensiones"]}
    assert dims["personas"]["disponible"] and dims["causas"]["disponible"]
    assert dims["gravedad_tradicional"]["disponible"] is False and dims["gravedad_tradicional"]["nota"]
    assert {x["clave"] for x in d["valores_para_filtros"]["localidades"]} == {"KENNEDY", "SUBA", "USAQUEN"}
    assert d["valores_para_filtros"]["anios"] == [2024, 2025]
    assert "formulario (IPAT)" in d["no_publicados"]


def test_cors_cabeceras_y_errores(cliente):
    r = cliente.get("/api/v1/health", headers={"Origin": "http://localhost:8000"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:8000"
    assert "access-control-allow-origin" not in cliente.get("/api/v1/health", headers={"Origin": "http://otro.com"}).headers
    assert r.headers["x-content-type-options"] == "nosniff"
    r = cliente.get("/api/v1/no-existe")
    assert r.status_code == 404 and r.json()["error"]["codigo"] == "no_encontrado"
    assert cliente.post("/api/v1/health").status_code == 405


def test_pagina_principal_y_archivos_estaticos(cliente):
    r = cliente.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"] and "VÍA SEGURA" in r.text
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    js = cliente.get("/static/js/app.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    assert cliente.get("/static/css/estilos.css").status_code == 200
    assert "content-security-policy" not in cliente.get("/api/v1/health").headers
    assert cliente.get("/static/no-existe.js").status_code == 404


# ------------------------------------------------------------------ exportación CSV (Parte 7)

def _csv(respuesta, sep=";"):
    import csv
    import io
    texto = respuesta.content.decode("utf-8")
    assert texto.startswith("﻿")
    filas = list(csv.reader(io.StringIO(texto[1:]), delimiter=sep))
    return [dict(zip(filas[0], f)) for f in filas[1:]], texto


def test_exportar_csv_por_defecto(cliente):
    r = cliente.get("/api/v1/export/accidents.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'filename="via-segura_arcgis_simur_accidentalidad_' in r.headers["content-disposition"]
    assert r.headers["x-total-registros"] == "4"  # sin «Solo daños» por defecto
    datos, texto = _csv(r)
    assert "SECRETO" not in texto and "formulario" not in texto.lower()
    assert [d["id_registro"] for d in datos] == ["4", "1", "2", "5"]  # por fecha ascendente
    s2 = next(d for d in datos if d["id_registro"] == "2")
    assert s2["latitud"] == "4,631" and s2["hora"] == "22:00" and s2["localidad"] == "Kennedy"
    assert s2["personas_fallecidas_derivado_actor_vial"] == "1" and s2["personas_ilesas_derivado_actor_vial"] == "1"
    s5 = next(d for d in datos if d["id_registro"] == "5")
    assert s5["latitud"] == "" and s5["coordenada_valida"] == "no" and s5["motivo_sin_coordenada"]


def test_exportar_csv_respeta_filtros_y_formato(cliente):
    datos, _ = _csv(cliente.get("/api/v1/export/accidents.csv", params={"gravedad": "todas"}))
    assert len(datos) == 5
    r = cliente.get("/api/v1/export/accidents.csv", params={"formato": "estandar", "localidad": "KENNEDY"})
    datos, _ = _csv(r, ",")
    assert [d["id_registro"] for d in datos] == ["1", "2"] and datos[1]["latitud"] == "4.631"
    datos, _ = _csv(cliente.get("/api/v1/export/accidents.csv", params={"actor": "PEATON"}))
    assert [d["id_registro"] for d in datos] == ["2"] and datos[0]["personas_ilesas_derivado_actor_vial"] == "0"
    datos, _ = _csv(cliente.get("/api/v1/export/accidents.csv", params={"fuente": "anuario_2025"}))
    assert [d["fuente"] for d in datos] == ["anuario_sdm_2025"]
    datos, _ = _csv(cliente.get("/api/v1/export/accidents.csv", params={"q": "PRUEBA 4"}))
    assert [d["id_registro"] for d in datos] == ["4"]
    datos, _ = _csv(cliente.get("/api/v1/export/accidents.csv", params={"solo_con_coordenada": True}))
    assert "5" not in [d["id_registro"] for d in datos]


def test_exportar_csv_formato_invalido_y_limite(cliente):
    assert cliente.get("/api/v1/export/accidents.csv", params={"formato": "xml"}).status_code == 422
    cliente.cfg.exportar_max_filas = 3
    r = cliente.get("/api/v1/export/accidents.csv")
    assert r.status_code == 400 and r.json()["error"]["codigo"] == "exportacion_muy_grande"
    assert "Acote los filtros" in r.json()["error"]["mensaje"]


def test_iterar_exportacion_por_bloques(tmp_path):
    from app.schemas.filtros import Filtros
    from app.services import consultas
    motor, fabrica, _cfg = preparar(tmp_path, con_admin=False)
    with fabrica() as s:
        fuente = consultas.resolver_fuente(s, None)
        filas = list(consultas.iterar_exportacion(s, fuente.id, fuente.codigo, Filtros(gravedad=["todas"]),
                                                  None, False, bloque=2))
    motor.dispose()
    assert [f["id_registro"] for f in filas] == [4, 1, 2, 3, 5]
    assert all("formulario" not in f for f in filas)
