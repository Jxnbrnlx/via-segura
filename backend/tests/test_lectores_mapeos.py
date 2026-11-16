"""Lectura por bloques (CSV/XLSX) y resolución de mapeos."""
import pytest

from app.services.archivos import ErrorArchivo
from app.services.lectores import LectorCSV, abrir_tabla
from app.services.mapeos import (
    ErrorMapeo, HojaMapeo, cargar_mapeo, clave_columna, listar_mapeos, resolver_columnas, resolver_hoja,
)


def escribir(tmp_path, texto: str, nombre="t.csv", codificacion="utf-8"):
    ruta = tmp_path / nombre
    ruta.write_bytes(texto.encode(codificacion))
    return ruta


def test_csv_coma_con_bom_y_bloques(tmp_path):
    ruta = escribir(tmp_path, "﻿Id,Nombre\n" + "".join(f"{i},x{i}\n" for i in range(5)) + "\n")
    lector = LectorCSV(ruta)
    assert lector.columnas() == ["Id", "Nombre"]
    bloques = list(lector.filas(bloque=2))
    assert [len(b) for b in bloques] == [2, 2, 1]
    assert bloques[0][0] == (2, {"Id": "0", "Nombre": "x0"})
    assert lector.contar_filas() == 5


def test_csv_punto_y_coma_cp1252_y_vacios(tmp_path):
    ruta = escribir(tmp_path, "AÑO;Localidad;Valor\n2024;Usaquén;\n", codificacion="cp1252")
    lector = LectorCSV(ruta)
    assert lector.separador == ";" and lector.codificacion == "cp1252"
    [[(_, fila)]] = list(lector.filas())
    assert fila == {"AÑO": "2024", "Localidad": "Usaquén", "Valor": None}


def test_csv_con_valores_de_mas_se_rechaza(tmp_path):
    lector = LectorCSV(escribir(tmp_path, "a,b\n1,2,3\n"))
    with pytest.raises(ErrorArchivo, match="más valores"):
        list(lector.filas())


def test_encabezados_repetidos_o_vacios(tmp_path):
    assert LectorCSV(escribir(tmp_path, "a,a,,b\n1,2,3,4\n")).columnas() == ["a", "a_2", "columna_3", "b"]


def test_xlsx_por_hojas_conserva_tipos(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from datetime import datetime

    libro = openpyxl.Workbook()
    ws = libro.active
    ws.title = "Siniestros"
    ws.append(["Codigo", "Fecha", "Lat"])
    ws.append([1, datetime(2025, 2, 9), 4.6])
    ws.append([None, None, None])
    ws.append([2, "02/10/2025", " 4,7 "])
    libro.create_sheet("Vehículos").append(["Codigo_Vehiculo"])
    ruta = tmp_path / "l.xlsx"
    libro.save(ruta)
    lector = abrir_tabla(ruta)
    assert lector.hojas == ["Siniestros", "Vehículos"]
    filas = [f for b in lector.filas("Siniestros") for f in b]
    assert filas == [(2, {"Codigo": 1, "Fecha": datetime(2025, 2, 9), "Lat": 4.6}),
                     (4, {"Codigo": 2, "Fecha": "02/10/2025", "Lat": "4,7"})]
    with pytest.raises(ErrorArchivo, match="varias hojas"):
        lector.columnas(None)
    lector.cerrar()


# ------------------------------------------------------------------ mapeos

def test_mapeos_preconfigurados_son_validos():
    assert {"anuario_sdm_2015_2024", "anuario_sdm_2025", "poblacion_osb_localidad"} <= set(listar_mapeos())
    for codigo in listar_mapeos():
        mapeo = cargar_mapeo(codigo)
        assert mapeo.codigo == codigo and mapeo.hojas


def test_clave_columna():
    assert clave_columna("Gravedad indicador 30d") == clave_columna("GRAVEDAD_INDICADOR_30D")
    assert clave_columna("AÑO") == "ANO" and clave_columna("Vehículos") == "VEHICULOS"


def test_resolucion_ignora_mayusculas_y_tildes_y_omite_personales():
    hoja = cargar_mapeo("anuario_sdm_2025").hojas["vehiculos"]
    columnas = ["CODIGO_SINIESTRO", "Código_Vehículo", "CLASE", "Servicio", "Placa", "Otra"]
    res = resolver_columnas(hoja, columnas)
    assert res.campos == {"id_registro": "CODIGO_SINIESTRO", "codigo_vehiculo": "Código_Vehículo",
                          "clase": "CLASE", "servicio": "Servicio"}
    assert res.personales_omitidas == ["Placa"] and res.sin_columna == ["modalidad"]
    assert res.no_usadas == ["Otra"] and res.completo


def test_banderas_con_prefijo_no_capturan_condicion():
    hoja = cargar_mapeo("anuario_sdm_2025").hojas["siniestros"]
    res = resolver_columnas(hoja, ["Codigo_Siniestro", "Fecha_Siniestro", "Con_Moto", "Condicion", "Elemento_Choque"])
    assert res.atributos == ["Con_Moto", "Elemento_Choque"] and "Condicion" in res.no_usadas


def test_faltante_obligatorio_y_sobrescritura():
    hoja = cargar_mapeo("anuario_sdm_2015_2024").hojas["actores"]
    res = resolver_columnas(hoja, ["IdAcc", "Ccodigo_Victima", "Edad"])
    assert res.faltantes_obligatorios == ["id_registro"] and not res.completo
    res = resolver_columnas(hoja, ["IdAcc", "Ccodigo_Victima", "Edad"], {"id_registro": "IdAcc", "edad": ""})
    assert res.completo and res.campos == {"id_registro": "IdAcc", "consecutivo_victima": "Ccodigo_Victima"}


@pytest.mark.parametrize("sobrescribir, motivo", [
    ({"id_registro": "Placa"}, "datos personales"),
    ({"id_registro": "NoExiste"}, "no existe"),
    ({"inventado": "IdAcc"}, "desconocido"),
])
def test_sobrescritura_invalida(sobrescribir, motivo):
    hoja = cargar_mapeo("anuario_sdm_2015_2024").hojas["actores"]
    with pytest.raises(ErrorMapeo, match=motivo):
        resolver_columnas(hoja, ["IdAcc", "Ccodigo_Victima", "Placa"], sobrescribir)


def test_mapeo_no_puede_pedir_columnas_personales():
    with pytest.raises(ValueError):
        HojaMapeo(tipo="vehiculos", campos={"id_registro": ["Codigo"], "codigo_vehiculo": ["Codigo_Vehiculo"],
                                            "clase": ["Placa"]})


def test_resolver_hoja():
    mapeo = cargar_mapeo("anuario_sdm_2025")
    assert resolver_hoja(mapeo, "vehiculos", None, ["Siniestros", "Vehículos", "Actor vial"]) == "Vehículos"
    assert resolver_hoja(mapeo, "actores", None, ["Siniestros", "Actor_vial"]) == "Actor_vial"
    assert resolver_hoja(mapeo, "siniestros", None, []) is None  # CSV
    with pytest.raises(ErrorMapeo):
        resolver_hoja(mapeo, "vehiculos", None, ["Hoja1"])
    with pytest.raises(ErrorMapeo):
        cargar_mapeo("../secreto")
