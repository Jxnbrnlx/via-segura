"""Administración: autenticación, carga con previsualización, confirmación, historial y sincronización."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import models
from app.main import create_app
from tests.api_comun import CONTRASENA, CORREO, preparar
from tests.test_importador import fila_2025, siniestros_csv


@pytest.fixture
def entorno(tmp_path):
    motor, fabrica, cfg = preparar(tmp_path)
    llamadas = []
    with TestClient(create_app(cfg, fabrica, ejecutor_sync=lambda **kw: llamadas.append(kw))) as c:
        yield c, fabrica, llamadas
    motor.dispose()


def entrar(c) -> dict:
    r = c.post("/api/v1/admin/auth/login", json={"correo": CORREO.upper(), "contrasena": CONTRASENA})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_login_correcto_y_errores_que_no_revelan_nada(entorno):
    c, fabrica, _ = entorno
    r = c.post("/api/v1/admin/auth/login", json={"correo": CORREO, "contrasena": CONTRASENA})
    assert r.status_code == 200 and r.json()["token_type"] == "bearer" and r.json()["usuario"]["correo"] == CORREO
    malo = c.post("/api/v1/admin/auth/login", json={"correo": CORREO, "contrasena": "otra-clave-9999"})
    nadie = c.post("/api/v1/admin/auth/login", json={"correo": "nadie@prueba.org", "contrasena": "otra-clave-9999"})
    assert malo.status_code == nadie.status_code == 401
    assert malo.json() == nadie.json() == {"error": {"codigo": "credenciales_invalidas",
                                                     "mensaje": "Correo o contraseña incorrectos."}}
    raro = c.post("/api/v1/admin/auth/login", json={"correo": "x", "contrasena": "MiSecreto123456", "extra": 1})
    assert raro.status_code == 422 and "MiSecreto123456" not in raro.text
    with fabrica() as s:
        assert s.scalar(select(models.UsuarioAdmin.ultimo_acceso)) is not None


def test_rutas_admin_exigen_token_valido(entorno):
    c, fabrica, _ = entorno
    assert c.get("/api/v1/admin/me").status_code == 401
    assert c.get("/api/v1/admin/me", headers={"Authorization": "Bearer basura"}).status_code == 401
    cabeceras = entrar(c)
    r = c.get("/api/v1/admin/me", headers=cabeceras)
    assert r.status_code == 200 and r.json()["correo"] == CORREO and r.headers["cache-control"] == "no-store"
    with fabrica() as s:
        s.scalar(select(models.UsuarioAdmin)).activo = False
        s.commit()
    assert c.get("/api/v1/admin/me", headers=cabeceras).status_code == 401  # cuenta desactivada


def test_limite_de_intentos_de_login(tmp_path):
    motor, fabrica, cfg = preparar(tmp_path, limite_login=2)
    with TestClient(create_app(cfg, fabrica, ejecutor_sync=lambda **kw: None)) as c:
        codigos = [c.post("/api/v1/admin/auth/login", json={"correo": CORREO, "contrasena": "x-1234567890"}).status_code
                   for _ in range(3)]
        assert codigos == [401, 401, 429]
    motor.dispose()


def subir(c, cabeceras, contenido: str, nombre="anuario.csv", **datos):
    datos.setdefault("tipo", "siniestros")
    datos.setdefault("mapeo", "anuario_sdm_2025")
    return c.post("/api/v1/admin/imports", headers=cabeceras, data=datos,
                  files={"archivo": (nombre, contenido.encode("utf-8"), "text/csv")})


def test_carga_previsualiza_confirma_y_registra(entorno):
    c, fabrica, _ = entorno
    cab = entrar(c)
    r = subir(c, cab, siniestros_csv(fila_2025(100), fila_2025(101), fila_2025(102, gravedad="Grave")))
    assert r.status_code == 201, r.text
    pv = r.json()["datos"]
    assert pv["puede_confirmar"] and pv["validacion"]["validas"] == 2 and pv["validacion"]["rechazadas"] == 1
    assert pv["mapeo"]["id_registro"] == "Codigo_Siniestro"
    lista = c.get("/api/v1/admin/imports", headers=cab).json()
    assert lista["datos"][0]["estado"] == "previsualizada" and lista["paginacion"]["total"] == 1
    detalle = c.get(f"/api/v1/admin/imports/{pv['importacion_id']}", headers=cab).json()["datos"]
    assert "token" not in detalle["resumen"]["archivo"]

    r = c.post(f"/api/v1/admin/imports/{pv['importacion_id']}/confirm", headers=cab,
               json={"url": "https://ejemplo.prueba/anuario", "fecha_descarga": "2026-11-10"})
    assert r.status_code == 202 and r.json()["datos"]["estado"] == "en_proceso"
    detalle = c.get(f"/api/v1/admin/imports/{pv['importacion_id']}", headers=cab).json()["datos"]
    assert detalle["estado"] == "completada", detalle
    assert (detalle["filas_validas"], detalle["filas_rechazadas"]) == (2, 1) and detalle["errores"]
    with fabrica() as s:
        fuente = s.scalar(select(models.FuenteDatos).where(models.FuenteDatos.codigo == "anuario_sdm_2025"))
        assert fuente.url == "https://ejemplo.prueba/anuario" and fuente.fecha_descarga is not None
        assert s.scalar(select(func.count()).select_from(models.SiniestroEvento)
                        .where(models.SiniestroEvento.fuente_id == fuente.id)) == 3
    r = c.post(f"/api/v1/admin/imports/{pv['importacion_id']}/confirm", headers=cab)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "no_confirmable"


def test_cancelar_y_errores_de_carga(entorno):
    c, _, _ = entorno
    cab = entrar(c)
    pv = subir(c, cab, siniestros_csv(fila_2025(1))).json()["datos"]
    assert c.post(f"/api/v1/admin/imports/{pv['importacion_id']}/cancel", headers=cab).json()["datos"]["estado"] == "cancelada"
    assert c.post(f"/api/v1/admin/imports/{pv['importacion_id']}/confirm", headers=cab).status_code == 409
    r = subir(c, cab, "x", nombre="virus.exe")
    assert r.status_code == 400 and r.json()["error"]["codigo"] == "archivo_rechazado"
    assert subir(c, cab, siniestros_csv(fila_2025(1)), mapeo="no_existe").status_code == 400
    assert subir(c, cab, siniestros_csv(fila_2025(1)), columnas="{no es json").status_code == 422
    sin_token = c.post("/api/v1/admin/imports", data={"tipo": "siniestros"},
                       files={"archivo": ("a.csv", b"a,b\n1,2\n", "text/csv")})
    assert sin_token.status_code == 401
    assert c.get("/api/v1/admin/imports/9999", headers=cab).status_code == 404


def test_mapeos_disponibles(entorno):
    c, _, _ = entorno
    d = c.get("/api/v1/admin/mappings", headers=entrar(c)).json()
    assert {m["codigo"] for m in d["datos"]} >= {"anuario_sdm_2025", "anuario_sdm_2015_2024", "poblacion_osb_localidad"}
    assert "localidades" in d["tipos_de_carga"]


def test_sincronizacion_en_segundo_plano_y_conflicto(entorno):
    c, fabrica, llamadas = entorno
    cab = entrar(c)
    r = c.post("/api/v1/admin/sync/arcgis", headers=cab, json={"modo": "completa", "desde_anio": 2025, "max_paginas": 1})
    assert r.status_code == 202
    assert llamadas == [{"modo": "completa", "desde_anio": 2025, "max_paginas": 1, "usuario_id": 1}]
    assert c.post("/api/v1/admin/sync/arcgis", headers=cab, json={"modo": "total"}).status_code == 422
    with fabrica() as s:
        s.add(models.Importacion(tipo="arcgis", estado="en_proceso", modo="incremental"))
        s.commit()
    r = c.post("/api/v1/admin/sync/arcgis", headers=cab)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "sincronizacion_en_curso"
    assert c.post("/api/v1/admin/sync/arcgis").status_code == 401
