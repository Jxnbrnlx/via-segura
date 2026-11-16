"""Formato del CSV exportado (funciones puras, sin base de datos)."""
import csv
import io

import pytest

from app.services import exportacion as ex


def fila(**cambios):
    base = {"fuente": "anuario_sdm_2025", "id_registro": 7, "fecha": "2025-03-01", "anio": 2025, "mes": 3,
            "dia_semana": "sábado", "hora": 8, "minuto": 5, "localidad": "KENNEDY", "localidad_nombre": "Kennedy",
            "clase": "Choque", "gravedad": "Con Heridos", "gravedad_tradicional": None, "direccion": "AK 68 - CL 13",
            "barrio": None, "via": None, "latitud": 4.630012, "longitud": -74.15, "coordenada_valida": True,
            "motivo_sin_coordenada": None, "personas": {"heridas": 2, "fallecidas": 0, "ilesas": 1}}
    base.update(cambios)
    return base


def leer(texto, sep):
    assert texto.startswith(ex.BOM)
    filas = list(csv.reader(io.StringIO(texto[1:]), delimiter=sep))
    return [dict(zip(filas[0], f)) for f in filas[1:]], filas[0]


def test_formato_excel_usa_punto_y_coma_y_coma_decimal():
    datos, enc = leer("".join(ex.generar_csv([fila()], "excel")), ";")
    assert enc == ex.ENCABEZADOS
    d = datos[0]
    assert d["latitud"] == "4,630012" and d["longitud"] == "-74,15"
    assert d["hora"] == "08:05" and d["localidad"] == "Kennedy" and d["coordenada_valida"] == "si"
    assert d["personas_heridas_derivado_actor_vial"] == "2" and d["gravedad_tradicional"] == ""


def test_formato_estandar_usa_coma_y_punto_decimal():
    datos, _ = leer("".join(ex.generar_csv([fila()], "estandar")), ",")
    assert datos[0]["latitud"] == "4.630012" and datos[0]["direccion"] == "AK 68 - CL 13"


def test_sin_coordenada_valida_no_se_escriben_coordenadas():
    datos, _ = leer("".join(ex.generar_csv([fila(coordenada_valida=False, latitud=4.0, longitud=-74.2,
                                                 motivo_sin_coordenada="sospechosa")])), ";")
    assert datos[0]["latitud"] == "" and datos[0]["longitud"] == ""
    assert datos[0]["motivo_sin_coordenada"] == "no coincide con la localidad"


def test_sin_hora_y_sin_localidad_quedan_vacias():
    datos, _ = leer("".join(ex.generar_csv([fila(hora=None, minuto=None, localidad=None, localidad_nombre=None)])), ";")
    assert datos[0]["hora"] == "" and datos[0]["localidad"] == ""


@pytest.mark.parametrize("peligroso", ["=HYPERLINK(\"x\")", "+57", "-1+1", "@SUM(A1)"])
def test_neutraliza_formulas(peligroso):
    datos, _ = leer("".join(ex.generar_csv([fila(direccion=peligroso)])), ";")
    assert datos[0]["direccion"] == "'" + peligroso


def test_saltos_de_linea_y_separadores_en_texto():
    datos, _ = leer("".join(ex.generar_csv([fila(direccion="CL 1;\nKR 2 \"norte\"")])), ";")
    assert datos[0]["direccion"] == "CL 1; KR 2 \"norte\""


def test_nunca_exporta_columnas_prohibidas():
    assert not {"formulario", "placa", "fecha_nacimiento", "codigo_accidentado", "edad"} & set(ex.ENCABEZADOS)
    texto = "".join(ex.generar_csv([fila(formulario="A000123", placa="ABC123")]))
    assert "A000123" not in texto and "ABC123" not in texto


def test_por_bloques_con_bom_solo_al_principio():
    trozos = list(ex.generar_csv((fila(id_registro=i) for i in range(1, 8)), bloque=3))
    assert len(trozos) == 3 and trozos[0].startswith(ex.BOM)
    assert not any(t.startswith(ex.BOM) for t in trozos[1:])
    datos, _ = leer("".join(trozos), ";")
    assert [d["id_registro"] for d in datos] == [str(i) for i in range(1, 8)]


def test_sin_filas_solo_encabezado():
    texto = "".join(ex.generar_csv([]))
    assert texto == ex.BOM + ";".join(ex.ENCABEZADOS) + "\r\n"


def test_formato_desconocido():
    with pytest.raises(ValueError):
        list(ex.generar_csv([], "xml"))


def test_nombre_de_archivo_seguro():
    assert ex.nombre_archivo("anuario_sdm_2025", "20261116") == "via-segura_anuario_sdm_2025_20261116.csv"
    assert ex.nombre_archivo('x"/../y', "1") == "via-segura_x_____y_1.csv"
