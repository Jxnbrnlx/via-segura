"""Normalizadores y validaciones (Python puro)."""
from datetime import date

import pytest

from app.services import calidad as c


# ---------------------------------------------------------------- localidad
@pytest.mark.parametrize("entrada, esperado", [
    ("USAQUÉN", "USAQUEN"),           # anuario (con tilde)
    ("USAQUEN", "USAQUEN"),           # ArcGIS (sin tilde)
    ("Bosa", "BOSA"),                 # hoja Actor vial del anuario
    ("  ciudad   bolívar ", "CIUDAD BOLIVAR"),
    ("ANTONIO NARIÑO", "ANTONIO NARIÑO"),  # la Ñ se conserva
    ("Antonio Narino", "ANTONIO NARIÑO"),
    ("La Candelaria", "CANDELARIA"),  # archivo de población
    ("CANDELARIA", "CANDELARIA"),
    ("Los Mártires", "LOS MARTIRES"),
    ("SUMAPAZ", "SUMAPAZ"),
])
def test_normalizar_localidad(entrada, esperado):
    assert c.normalizar_localidad(entrada) == esperado


@pytest.mark.parametrize("vacio", [None, "", "   "])
def test_localidad_vacia_es_none(vacio):
    assert c.normalizar_localidad(vacio) is None


def test_localidad_desconocida_no_se_reasigna():
    with pytest.raises(c.ValorNoReconocido):
        c.normalizar_localidad("SOACHA")


def test_codigos_de_localidad_coinciden_con_el_archivo_de_poblacion():
    assert len(c.CODIGO_LOCALIDAD) == 20
    assert c.CODIGO_LOCALIDAD[1] == "USAQUEN"
    assert c.CODIGO_LOCALIDAD[15] == "ANTONIO NARIÑO"
    assert c.CODIGO_LOCALIDAD[17] == "CANDELARIA"
    assert c.CODIGO_LOCALIDAD[19] == "CIUDAD BOLIVAR"
    assert c.CODIGO_LOCALIDAD[20] == "SUMAPAZ"


# ---------------------------------------------------------------- categorías
@pytest.mark.parametrize("entrada, esperado", [
    ("CON HERIDOS", "Con Heridos"), ("Con Heridos", "Con Heridos"), ("CON MUERTOS", "Con Muertos"),
    ("SOLO DANOS", "Solo Daños"), ("Solo Daños", "Solo Daños"), (None, None), ("", None),
])
def test_normalizar_gravedad(entrada, esperado):
    assert c.normalizar_gravedad(entrada) == esperado


def test_gravedad_desconocida_se_rechaza():
    with pytest.raises(c.ValorNoReconocido):
        c.normalizar_gravedad("GRAVE")


@pytest.mark.parametrize("entrada, esperado", [
    ("CHOQUE", ("Choque", True)), ("Caida de ocupante", ("Caída de ocupante", True)),
    ("AUTOLESION", ("Autolesión", True)), ("Autolesión", ("Autolesión", True)),
    ("EXPLOSION", ("EXPLOSION", False)),  # se conserva, no se reasigna
    (None, (None, True)),
])
def test_normalizar_clase(entrada, esperado):
    assert c.normalizar_clase(entrada) == esperado


def test_estado_y_sexo():
    assert c.normalizar_estado_persona("herido") == "HERIDO"
    assert c.normalizar_estado_persona(None) is None
    with pytest.raises(c.ValorNoReconocido):
        c.normalizar_estado_persona("GRAVE")
    assert c.normalizar_sexo("Masculino") == "MASCULINO"
    assert c.normalizar_sexo("SIN INFORMACIÓN") == "SIN INFORMACION"
    with pytest.raises(c.ValorNoReconocido):
        c.normalizar_sexo("X")


def test_enie_danada_se_repara_sin_interpretar():
    assert c.normalizar_categoria("ACOMPA¿E") == "ACOMPAÑE"
    assert c.normalizar_categoria("Peatón") == "PEATON"
    assert c.normalizar_categoria("¿QUÉ?") == "¿QUE?"  # el ¿ inicial no está entre letras


# ---------------------------------------------------------------- edad
@pytest.mark.parametrize("entrada, esperado", [
    (30, 30), (30.0, 30), ("45", 45), (0, 0), (110, 110), (111, None), (2021, None), (-1, None),
    (30.5, None), ("", None), (None, None), ("abc", None),
])
def test_normalizar_edad(entrada, esperado):
    assert c.normalizar_edad(entrada) == esperado


@pytest.mark.parametrize("edad, rango", [(0, "0-5"), (5, "0-5"), (6, "6-11"), (17, "12-17"), (18, "18-28"),
                                         (59, "29-59"), (60, "60+"), (110, "60+"), (None, None)])
def test_rango_edad(edad, rango):
    assert c.rango_edad(edad) == rango


# ---------------------------------------------------------------- números y coordenadas
@pytest.mark.parametrize("entrada, esperado", [
    ("4,58396118246", 4.58396118246), ("-74,13660797754", -74.13660797754), ("4.6", 4.6), (4.6, 4.6),
    ("", None), (None, None), ("N/A", None), (float("nan"), None), (True, None),
])
def test_convertir_numero_con_coma_decimal(entrada, esperado):
    assert c.convertir_numero(entrada) == esperado


def test_coordenada_faltante_no_se_imputa():
    r = c.validar_coordenada(None, "-74,1")
    assert (r.latitud, r.longitud, r.valida, r.motivo) == (None, None, False, "sin_coordenada")


def test_coordenada_fuera_de_rango_mundial():
    r = c.validar_coordenada(95, -74.1)
    assert (r.latitud, r.valida, r.motivo) == (None, False, "fuera_de_rango")


@pytest.mark.parametrize("lat, lon", [(0, 0), (6.25, -75.57), (4.6, 74.1), (-74.1, 4.6)])
def test_coordenada_fuera_de_bogota(lat, lon):
    r = c.validar_coordenada(lat, lon)
    assert r.valida is False and r.motivo == "fuera_de_bogota"
    assert (r.latitud, r.longitud) == (lat, lon)  # se conserva el valor para auditoría, sin mover el punto


def test_sumapaz_al_sur_es_valido():
    assert c.validar_coordenada(3.95, -74.2).valida is True


def test_coordenada_con_coma_decimal_valida():
    r = c.validar_coordenada("4,58396118246", "-74,13660797754")
    assert r.valida and r.latitud == pytest.approx(4.58396118246)


def test_detectar_sospechosas_marca_puntos_lejos_de_su_localidad():
    puntos = [(i, "FONTIBON", 4.67 + (i % 10) * 0.002, -74.14 + (i % 7) * 0.002) for i in range(100)]
    puntos += [(i, "USME", 4.47 - (i % 30) * 0.01, -74.12) for i in range(100, 200)]  # extensión rural
    puntos.append((999, "FONTIBON", 4.0858, -74.2283))   # caso real documentado: Fontibón al sur
    puntos.append((998, "FONTIBON", 4.69, -74.13))       # normal
    sospechosas = c.detectar_coordenadas_sospechosas(puntos)
    assert 999 in sospechosas
    assert 998 not in sospechosas
    assert not any(100 <= i < 200 for i in sospechosas)  # Usme rural no se marca


def test_detectar_sospechosas_ignora_localidades_con_pocos_puntos():
    assert c.detectar_coordenadas_sospechosas([(1, "SUMAPAZ", 3.8, -74.2), (2, "SUMAPAZ", 4.8, -74.0)]) == set()


# ---------------------------------------------------------------- fechas y horas
def test_fecha_epoch_verificada_en_el_servicio_no_corre_el_dia():
    # Valores reales del servicio (16-11-2026): 1794268800000 = martes 10-nov-2026 (DIA_OCURRENCIA_ACC = MARTES)
    assert c.fecha_desde_epoch_ms(1794268800000) == date(2026, 11, 10)
    assert c.dia_semana(date(2026, 11, 10)) == "martes"
    # Siniestro 11335436: 1756771200000 = 2025-09-02, igual a Fecha_Siniestro del anuario 2025
    assert c.fecha_desde_epoch_ms(1756771200000) == date(2025, 9, 2)


def test_fecha_epoch_con_hora_se_convierte_a_hora_de_bogota():
    # 2025-09-02 03:00 UTC = 2025-09-01 22:00 en Bogotá
    assert c.fecha_desde_epoch_ms(1756782000000) == date(2025, 9, 1)
    # medianoche de Bogotá expresada en UTC (05:00) -> mismo día local
    assert c.fecha_desde_epoch_ms(1756771200000 + 5 * 3_600_000) == date(2025, 9, 2)
    assert c.fecha_desde_epoch_ms(None) is None


@pytest.mark.parametrize("entrada, esperado", [
    ("19:50:00", (19, 50)), ("7:05", (7, 5)), ("00:00:00", (0, 0)), ("24:00:00", (None, None)),
    ("", (None, None)), (None, (None, None)), ("mediodía", (None, None)),
])
def test_hora_desde_texto(entrada, esperado):
    assert c.hora_desde_texto(entrada) == esperado


def test_hora_desde_enteros_anuario():
    assert c.hora_desde_enteros("20", "40") == (20, 40)
    assert c.hora_desde_enteros("25", "10") == (None, None)
    assert c.hora_desde_enteros("8", "") == (8, None)
