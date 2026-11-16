"""Pruebas de aceptación transversales: recorren TODOS los endpoints públicos (descubiertos automáticamente)
y verifican las decisiones del proyecto que no pueden romperse."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.api_comun import preparar

# Valores de formulario de prueba ("SECRETO…") o claves privadas en cualquier respuesta.
PROHIBIDO_EN_RESPUESTA = re.compile(r'SECRETO|"(formulario|placa|fecha_nacimiento|codigo_accidentado|edad)"\s*:',
                                    re.IGNORECASE)
COMBINACIONES = [
    {},
    {"gravedad": "todas"},
    {"fuente": "anuario_2025"},
    {"localidad": "KENNEDY", "anio": 2025},
    {"actor": "PEATON", "gravedad": "Con Muertos"},
    {"fecha_desde": "2025-01-01", "fecha_hasta": "2025-12-31", "clase": "Choque"},
]


@pytest.fixture(scope="module")
def cliente(tmp_path_factory):
    motor, fabrica, cfg = preparar(tmp_path_factory.mktemp("aceptacion"))
    with TestClient(create_app(cfg, fabrica, ejecutor_sync=lambda **kw: None)) as c:
        yield c
    motor.dispose()


def rutas_publicas(cliente):
    salida = []
    for r in cliente.app.routes:
        ruta = getattr(r, "path", "")
        documentacion = ruta.endswith(("/docs", "/redoc", "/openapi.json")) or "/docs/" in ruta
        if ruta.startswith("/api/v1") and "/admin" not in ruta and not documentacion \
                and "GET" in getattr(r, "methods", set()):
            salida.append(ruta.replace("{id_registro}", "1"))
    return sorted(set(salida))


def test_se_descubren_los_endpoints_publicos(cliente):
    rutas = rutas_publicas(cliente)
    for esperada in ("/api/v1/dashboard/summary", "/api/v1/accidents/geojson", "/api/v1/analytics/concentration",
                     "/api/v1/localities/geojson", "/api/v1/export/accidents.csv", "/api/v1/accidents/1"):
        assert esperada in rutas
    assert len(rutas) >= 16


@pytest.mark.parametrize("parametros", COMBINACIONES)
def test_ningun_endpoint_publico_expone_datos_privados_ni_califica_zonas(cliente, parametros):
    for ruta in rutas_publicas(cliente):
        r = cliente.get(ruta, params=parametros)
        assert r.status_code in (200, 404), (ruta, parametros, r.status_code, r.text[:300])
        texto = r.text
        assert not PROHIBIDO_EN_RESPUESTA.search(texto), (ruta, parametros, PROHIBIDO_EN_RESPUESTA.search(texto))
        assert "peligros" not in texto.lower(), (ruta, parametros)
        if r.headers["content-type"].startswith("application/json"):
            r.json()  # JSON válido


def test_errores_siempre_con_el_mismo_formato(cliente):
    for ruta, parametros in (("/api/v1/dashboard/summary", {"fuente": "no_existe"}),
                             ("/api/v1/accidents", {"tamano": 100000}),
                             ("/api/v1/analytics/by-locality", {"gravedad": "Catastrófica"}),
                             ("/api/v1/accidents/geojson", {"bbox": "1,2,3"}),
                             ("/api/v1/export/accidents.csv", {"formato": "pdf"}),
                             ("/api/v1/no-existe", {})):
        r = cliente.get(ruta, params=parametros)
        assert 400 <= r.status_code < 500, (ruta, r.status_code)
        error = r.json()["error"]
        assert error["codigo"] and error["mensaje"], (ruta, error)
        assert "Traceback" not in r.text and "sqlalchemy" not in r.text.lower()


def test_una_sola_fuente_por_consulta_nunca_se_suman(cliente):
    arcgis = cliente.get("/api/v1/dashboard/summary", params={"gravedad": "todas"}).json()
    anuario = cliente.get("/api/v1/dashboard/summary", params={"gravedad": "todas", "fuente": "anuario_2025"}).json()
    assert arcgis["fuente"]["codigo"] == "arcgis_simur_accidentalidad"
    assert anuario["fuente"]["codigo"] == "anuario_sdm_2025"
    assert arcgis["periodo"]["registros"] == 5 and anuario["periodo"]["registros"] == 1
    for ruta in ("/api/v1/accidents", "/api/v1/analytics/by-period", "/api/v1/analytics/by-locality"):
        cuerpo = cliente.get(ruta, params={"gravedad": "todas"}).json()
        assert cuerpo["fuente"]["codigo"] == "arcgis_simur_accidentalidad", ruta


def test_kpi_por_defecto_y_solo_danos_aparte(cliente):
    d = cliente.get("/api/v1/dashboard/summary").json()
    principal = d["datos"]["kpis"][0]
    assert principal["valor"] == 4 and "heridos o muertos" in principal["etiqueta"]
    assert d["datos"]["solo_danos_aparte"]["valor"] == 1 and d["datos"]["solo_danos_aparte"]["advertencia"]
    personas = [k for k in d["datos"]["kpis"] if k["unidad"] == "personas"]
    assert personas and all(k["derivado"] for k in personas)


def test_coordenadas_no_se_imputan_y_concentracion_solo_conteos(cliente):
    geo = cliente.get("/api/v1/accidents/geojson", params={"gravedad": "todas"}).json()
    ids = {f["properties"]["id_registro"] for f in geo["features"]}
    assert 5 not in ids and geo["metadatos"]["sin_coordenada_valida"] >= 1
    celdas = cliente.get("/api/v1/analytics/concentration").json()["datos"]["celdas"]
    assert celdas and all(set(c) <= {"lat_min", "lat_max", "lon_min", "lon_max", "lat_centro", "lon_centro",
                                     "fila", "columna", "conteo"} for c in celdas)


def test_tasas_solo_con_denominador_oficial_y_con_formula(cliente):
    loc = cliente.get("/api/v1/analytics/by-locality").json()["datos"]["localidades"]
    for fila in loc:
        tasa = fila["tasa_siniestros"]
        if tasa["disponible"]:
            assert tasa["formula"] and tasa["fuente_denominador"]
        else:
            assert tasa["motivo"]


def test_portada_con_cabeceras_de_seguridad(cliente):
    r = cliente.get("/")
    assert r.status_code == 200 and "VÍA SEGURA" in r.text
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "unsafe-eval" not in csp
    assert r.headers["x-content-type-options"] == "nosniff"
    salud = cliente.get("/api/v1/health").json()
    assert json.dumps(salud)  # serializable
