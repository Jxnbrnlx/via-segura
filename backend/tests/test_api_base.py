"""Piezas de la API que no dependen de la base de datos: filtros, cuadrícula, middlewares y seguridad."""
from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app import seguridad
from app.api.middlewares import CabecerasSeguridad, LimitadorPeticiones, ProteccionCargas
from app.schemas.filtros import Filtros, Paginacion
from app.services import concentracion


# ---------------------------------------------------------------- filtros
def test_filtros_normalizan_y_ordenan():
    f = Filtros(localidad=["Usaquén", "SUBA", "usaquen"], anio=[2025, 2024, 2025], gravedad=["CON MUERTOS"],
                actor=["Peatón"], clase=["CHOQUE", "Caida de ocupante"])
    assert f.localidad == ["SUBA", "USAQUEN"] and f.anio == [2024, 2025]
    assert f.gravedades_efectivas == ("Con Muertos",) and f.actor == ["PEATON"]
    assert f.clase == ["Caída de ocupante", "Choque"]


def test_gravedad_por_defecto_y_todas():
    assert Filtros().gravedades_efectivas == ("Con Heridos", "Con Muertos")
    assert Filtros().usa_gravedad_por_defecto and not Filtros().incluye_solo_danos
    todas = Filtros(gravedad=["todas"])
    assert todas.gravedades_efectivas is None and todas.incluye_solo_danos
    assert todas.como_dict()["gravedad"] == "todas"


@pytest.mark.parametrize("datos", [
    {"localidad": ["Soacha"]}, {"gravedad": ["grave"]}, {"mes": [13]}, {"anio": [1800]},
    {"fecha_desde": date(2025, 2, 1), "fecha_hasta": date(2025, 1, 1)}, {"otro": 1},
    {"anio": list(range(2000, 2050))},
])
def test_filtros_invalidos(datos):
    with pytest.raises(ValidationError):
        Filtros(**datos)


def test_paginacion_limitada():
    assert Paginacion(pagina=3, tamano=20).desplazamiento == 40
    with pytest.raises(ValidationError):
        Paginacion(tamano=201)


# ---------------------------------------------------------------- cuadrícula
def test_celda_de_250m_y_sus_limites_contienen_el_punto():
    dlat, dlon = concentracion.pasos_grados(250)
    assert dlat == pytest.approx(0.0022458, rel=1e-3) and dlon > dlat
    fila, col = concentracion.celda_de(4.6097, -74.0817, 250)
    lim = concentracion.limites_celda(fila, col, 250)
    assert lim["lat_min"] <= 4.6097 <= lim["lat_max"] and lim["lon_min"] <= -74.0817 <= lim["lon_max"]
    assert concentracion.celda_de(4.6098, -74.0816, 250) == (fila, col)


# ---------------------------------------------------------------- middlewares
def _app(middleware, **kw):
    async def ok(request):
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/api/v1/x", ok), Route("/api/v1/login", ok, methods=["POST"]),
                            Route("/api/v1/admin/imports", ok, methods=["POST"]), Route("/otro", ok)])
    return middleware(app, **kw)


def test_limitador_por_ip_con_regla_estricta():
    reloj = {"t": 0.0}
    app = _app(LimitadorPeticiones, limite_por_minuto=3, reglas={"/api/v1/login": 1}, reloj=lambda: reloj["t"])
    c = TestClient(app)
    assert [c.get("/api/v1/x").status_code for _ in range(4)] == [200, 200, 200, 429]
    r = c.get("/api/v1/x")
    assert r.json()["error"]["codigo"] == "demasiadas_peticiones" and int(r.headers["retry-after"]) >= 1
    assert c.get("/otro").status_code == 200                    # fuera de /api/ no se limita
    assert [c.post("/api/v1/login").status_code for _ in range(2)] == [200, 429]
    reloj["t"] = 61
    assert c.get("/api/v1/x").status_code == 200                # la ventana se libera


def test_proteccion_de_cargas():
    app = _app(ProteccionCargas, ruta="/api/v1/admin/imports", max_bytes=100, token_valido=lambda t: t == "bueno")
    c = TestClient(app)
    assert c.post("/api/v1/admin/imports", content=b"x").status_code == 401
    assert c.post("/api/v1/admin/imports", content=b"x", headers={"Authorization": "Bearer malo"}).status_code == 401
    r = c.post("/api/v1/admin/imports", content=b"x" * 500, headers={"Authorization": "Bearer bueno"})
    assert r.status_code == 413 and r.json()["error"]["codigo"] == "archivo_demasiado_grande"
    assert c.post("/api/v1/admin/imports", content=b"x" * 50, headers={"Authorization": "Bearer bueno"}).status_code == 200
    assert c.get("/api/v1/x").status_code == 200


def test_cabeceras_de_seguridad():
    c = TestClient(_app(CabecerasSeguridad))
    r = c.get("/api/v1/x")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert "cache-control" not in r.headers and "content-security-policy" not in r.headers
    pagina = c.get("/otro")
    assert "script-src 'self'" in pagina.headers["content-security-policy"]


# ---------------------------------------------------------------- seguridad
SECRETO = "s" * 48


def test_token_valido_vencido_y_alterado():
    token, expira = seguridad.crear_token(7, "admin", SECRETO, 60)
    datos = seguridad.decodificar_token(token, SECRETO)
    assert datos["sub"] == "7" and datos["rol"] == "admin" and expira > datetime.now(timezone.utc)
    viejo, _ = seguridad.crear_token(7, "admin", SECRETO, 5, ahora=datetime.now(timezone.utc) - timedelta(hours=1))
    with pytest.raises(seguridad.ErrorToken, match="venció"):
        seguridad.decodificar_token(viejo, SECRETO)
    with pytest.raises(seguridad.ErrorToken):
        seguridad.decodificar_token(token, "otro" * 12)
    with pytest.raises(seguridad.ErrorToken):
        seguridad.decodificar_token(token[:-2] + "xx", SECRETO)


@pytest.mark.parametrize("contrasena, valida", [
    ("corta1", False), ("solo-letras-largas", False), ("123456789012345", False),
    ("clave-segura-2026", True), ("ñ" * 37 + "1", False),  # 75 bytes > 72
])
def test_politica_de_contrasena(contrasena, valida):
    assert (seguridad.validar_politica(contrasena) == []) is valida


def test_hash_bcrypt():
    pytest.importorskip("bcrypt")
    h = seguridad.hashear_contrasena("clave-segura-2026")
    assert h.startswith("$2") and seguridad.verificar_contrasena("clave-segura-2026", h)
    assert not seguridad.verificar_contrasena("otra-clave-2026", h)
    assert not seguridad.verificar_contrasena("clave-segura-2026", None)
    with pytest.raises(ValueError):
        seguridad.hashear_contrasena("debil")
