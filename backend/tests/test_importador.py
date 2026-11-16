"""Importador de archivos con repositorio en memoria. Todos los datos son SINTÉTICOS de prueba."""
import io
import json
from datetime import date, datetime

import pytest

from app.services.archivos import recibir_archivo
from app.services.importador_excel import (
    ErrorImportacion, ImportadorArchivos, interpretar_fecha,
)
from app.services.mapeos import ErrorMapeo
from tests.repositorio_memoria import RepositorioMemoria

HOY = date(2026, 11, 16)
ENC_2025 = ("Codigo_Siniestro,Formulario,Longitud,Latitud,Direccion,Fecha_Siniestro,AA_Siniestro,MM_Siniestro,"
            "DD_Mes_Siniestro,Dia_Semana_Siniestro,Hora_Siniestro,Min_Siniestro,Localidad,Clase_Siniestro,"
            "Elemento_Choque,Tipo_Objeto_Fijo,Gravedad_indicador_30d,Con_Bicicleta,Con_Moto")


def fila_2025(codigo, fecha="9/2/2025", mes="Septiembre", dia="2", anio="2025", localidad="TUNJUELITO",
              gravedad="Con Heridos", lat='"4,58"', lon='"-74,13"', moto="SI"):
    return (f'{codigo},PR{codigo},{lon},{lat},KR 1 # 2 (PRUEBA),{fecha},{anio},{mes},{dia},martes,13,5,'
            f'{localidad},Choque,Vehículo,,{gravedad},,{moto}')


@pytest.fixture
def entorno(tmp_path):
    repo = RepositorioMemoria()
    imp = ImportadorArchivos(repo, tmp_path / "cargas", tmp_path / "geo", hoy=HOY, bloque=3)
    return repo, imp, tmp_path


def subir(tmp_path, contenido, nombre="datos.csv", mime="text/csv"):
    datos = contenido.encode("utf-8") if isinstance(contenido, str) else contenido
    return recibir_archivo(io.BytesIO(datos), nombre, mime, tmp_path / "cargas", max_bytes=10 * 2**20)


def fuente(repo, codigo):
    return repo.obtener_fuente(codigo).id


def siniestros_csv(*filas):
    return ENC_2025 + "\n" + "\n".join(filas) + "\n"


# ------------------------------------------------------------------ fechas

@pytest.mark.parametrize("valor, controles, esperado", [
    ("02/09/2015", dict(anio=2015, mes=2, dia=9), date(2015, 2, 9)),     # MM/DD resuelto por los controles
    ("09/02/2015", dict(anio=2015, mes=2, dia=9), date(2015, 2, 9)),     # DD/MM también
    ("9/2/2025", {}, date(2025, 9, 2)),                                  # sin controles: primer formato
    ("2025-09-02 00:00:00", {}, date(2025, 9, 2)),
    (datetime(2025, 9, 2, 10), dict(dia=2), date(2025, 9, 2)),
])
def test_interpretar_fecha(valor, controles, esperado):
    assert interpretar_fecha(valor, ["%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y"], **controles) == (esperado, None)


def test_fecha_incoherente_con_controles_no_se_adivina():
    fecha, error = interpretar_fecha("02/09/2015", ["%m/%d/%Y"], anio=2015, mes=9, dia=2)
    assert fecha is None and "incoherente" in error


# ------------------------------------------------------------------ previsualización

def test_previsualizacion_no_escribe_datos_y_registra_estado(entorno):
    repo, imp, tmp = entorno
    pv = imp.previsualizar(subir(tmp, siniestros_csv(fila_2025(1), fila_2025(2))), tipo="siniestros",
                           mapeo_codigo="anuario_sdm_2025")
    assert pv.puede_confirmar and pv.validacion["validas"] == 2
    assert pv.mapeo["latitud"] == "Latitud" and "gravedad_tradicional" in pv.campos_sin_columna
    tipos = {c["nombre"]: c["tipo_inferido"] for c in pv.columnas}
    assert tipos["Latitud"] == "decimal con coma" and tipos["Codigo_Siniestro"] == "entero"
    assert repo.siniestros() == []
    registro = repo.importacion(pv.importacion_id)
    assert registro["estado"] == "previsualizada" and registro["tipo"] == "excel" and registro["modo"] == "siniestros"


def test_previsualizacion_no_muestra_columnas_personales(entorno):
    repo, imp, tmp = entorno
    csv = "Codigo_Siniestro,Codigo_Vehiculo,Clase,Placa\n1,1,AUTOMOVIL,ABC123\n"
    pv = imp.previsualizar(subir(tmp, csv), tipo="vehiculos", mapeo_codigo="anuario_sdm_2025")
    assert pv.columnas_personales_omitidas == ["Placa"]
    assert "ABC123" not in json.dumps(pv.como_dict(), default=str)
    assert "ABC123" not in json.dumps(repo.estado["importaciones"], default=str)


def test_previsualizacion_con_mapeo_incompleto_no_permite_confirmar(entorno):
    repo, imp, tmp = entorno
    pv = imp.previsualizar(subir(tmp, "Otro,Fecha\n1,2\n"), tipo="siniestros", mapeo_codigo="anuario_sdm_2025")
    assert not pv.puede_confirmar and set(pv.faltantes_obligatorios) == {"id_registro", "fecha_evento"}
    r = imp.confirmar(pv.importacion_id)
    assert r.estado == "fallida" and "obligatorias" in r.mensaje


def test_tipo_o_mapeo_invalido_borra_el_archivo_recibido(entorno):
    _, imp, tmp = entorno
    recibido = subir(tmp, siniestros_csv(fila_2025(1)))
    with pytest.raises(ErrorMapeo):
        imp.previsualizar(recibido, tipo="siniestros", mapeo_codigo="no_existe")
    assert not recibido.ruta.exists()
    with pytest.raises(ErrorImportacion):
        imp.previsualizar(subir(tmp, siniestros_csv(fila_2025(1))), tipo="otro", mapeo_codigo="anuario_sdm_2025")


# ------------------------------------------------------------------ siniestros

def test_importa_siniestros_con_validaciones(entorno):
    repo, imp, tmp = entorno
    csv = siniestros_csv(
        fila_2025(1),
        fila_2025(2, lat="", lon=""),                                   # sin coordenada: no se imputa
        fila_2025(3, fecha="9/3/2025"),                                 # incoherente con día 2
        fila_2025(4, gravedad="Grave"),                                 # gravedad desconocida
        fila_2025(1),                                                   # repetido en el archivo
        fila_2025(5, fecha="12/1/2026", mes="Diciembre", dia="1", anio="2026"),   # futura
        fila_2025(6, localidad="SOACHA"),
        fila_2025(7, gravedad=""),
    )
    pv = imp.previsualizar(subir(tmp, csv), tipo="siniestros", mapeo_codigo="anuario_sdm_2025")
    r = imp.confirmar(pv.importacion_id)
    assert r.estado == "completada", r.mensaje
    assert (r.filas_revisadas, r.filas_validas, r.filas_rechazadas) == (8, 4, 4)
    por_id = {s["id_registro"]: s for s in repo.siniestros()}
    assert set(por_id) == {1, 2, 6, 7}
    s1 = por_id[1]
    assert s1["fecha_evento"] == date(2025, 9, 2) and s1["dia_semana"] == "martes"
    assert (s1["latitud"], s1["longitud"], s1["coordenada_valida"]) == (4.58, -74.13, True)
    assert s1["atributos"] == {"elemento_choque": "Vehículo", "con_moto": True}
    assert por_id[2]["motivo_coordenada"] == "sin_coordenada" and por_id[2]["latitud"] is None
    assert por_id[6]["localidad"] is None and por_id[6]["atributos"]["localidad_original"] == "SOACHA"
    assert por_id[7]["gravedad"] is None
    q = r.resumen["calidad"]
    assert q["rechazo.fecha"] == 1 and q["rechazo.gravedad_no_reconocida"] == 1 and q["rechazo.fecha_futura"] == 1
    assert q["duplicado.siniestro_en_archivo"] == 1
    imp_reg = repo.importacion(pv.importacion_id)
    assert imp_reg["estado"] == "completada" and imp_reg["fecha_max_evento"] == date(2025, 9, 2)
    assert any("incoherente" in e for e in imp_reg["errores"])
    f = repo.estado["fuentes"][fuente(repo, "anuario_sdm_2025")]
    assert (f["periodo_inicio"], f["periodo_fin"]) == (date(2025, 9, 2), date(2025, 9, 2))
    assert not pv_ruta(tmp).exists() or not any(pv_ruta(tmp).iterdir())  # archivo temporal eliminado


def pv_ruta(tmp):
    return tmp / "cargas"


def test_confirmar_dos_veces_no_se_permite_y_reimportar_no_duplica(entorno):
    repo, imp, tmp = entorno
    csv = siniestros_csv(fila_2025(1), fila_2025(2))
    pv = imp.previsualizar(subir(tmp, csv), tipo="siniestros", mapeo_codigo="anuario_sdm_2025")
    imp.confirmar(pv.importacion_id)
    with pytest.raises(ErrorImportacion, match="completada"):
        imp.confirmar(pv.importacion_id)
    pv2 = imp.previsualizar(subir(tmp, csv), tipo="siniestros", mapeo_codigo="anuario_sdm_2025")
    r = imp.confirmar(pv2.importacion_id)
    assert (r.nuevos, r.actualizados) == (0, 2) and len(repo.siniestros()) == 2


def test_archivo_modificado_tras_previsualizar(entorno):
    repo, imp, tmp = entorno
    recibido = subir(tmp, siniestros_csv(fila_2025(1)))
    pv = imp.previsualizar(recibido, tipo="siniestros", mapeo_codigo="anuario_sdm_2025")
    recibido.ruta.write_text(siniestros_csv(fila_2025(99)), encoding="utf-8")
    with pytest.raises(ErrorImportacion, match="cambió"):
        imp.confirmar(pv.importacion_id)
    assert repo.siniestros() == []


def test_cancelar(entorno):
    repo, imp, tmp = entorno
    recibido = subir(tmp, siniestros_csv(fila_2025(1)))
    pv = imp.previsualizar(recibido, tipo="siniestros", mapeo_codigo="anuario_sdm_2025")
    imp.cancelar(pv.importacion_id)
    assert repo.importacion(pv.importacion_id)["estado"] == "cancelada" and not recibido.ruta.exists()
    with pytest.raises(ErrorImportacion):
        imp.confirmar(pv.importacion_id)


def test_mismo_siniestro_en_dos_anuarios_se_reporta_sin_fusionar(entorno):
    repo, imp, tmp = entorno
    pv = imp.previsualizar(subir(tmp, siniestros_csv(fila_2025(7))), tipo="siniestros",
                           mapeo_codigo="anuario_sdm_2025")
    imp.confirmar(pv.importacion_id)
    csv_2024 = ("Codigo_Accidente,Fecha_Acc,AA_Acc,MM_Acc,DD_Mes_Acc,Gravedad_indicador_30d,"
                "Gravedad_Indicador_Tradicional,Localidad,Con_Moto,Con_Rutas\n"
                "7,09/02/2024,2024,Septiembre,2,Con Heridos,Solo Daños,USAQUÉN,,SI\n")
    pv = imp.previsualizar(subir(tmp, csv_2024), tipo="siniestros", mapeo_codigo="anuario_sdm_2015_2024")
    r = imp.confirmar(pv.importacion_id)
    [coincidencia] = r.resumen["coincidencias_otras_fuentes"]
    assert coincidencia == {"fuente": "anuario_sdm_2025", "coincidencias": 1, "fecha_distinta": 1}
    s = repo.siniestros(fuente(repo, "anuario_sdm_2015_2024"))[0]
    assert s["fecha_evento"] == date(2024, 9, 2) and s["gravedad_tradicional"] == "Solo Daños"
    assert s["localidad"] == "USAQUEN" and s["atributos"] == {"con_rutas": True}
    assert len(repo.siniestros()) == 2


# ------------------------------------------------------------------ personas y vehículos

def preparar_siniestros(repo, imp, tmp, ids=(1, 2, 3)):
    pv = imp.previsualizar(subir(tmp, siniestros_csv(*(fila_2025(i) for i in ids))), tipo="siniestros",
                           mapeo_codigo="anuario_sdm_2025")
    imp.confirmar(pv.importacion_id)


ENC_ACTOR = "Codigo_Siniestro,Codigo_Vehiculo,Ccodigo_Victima,Condicion,Gravedad_Indicador_30d,Sexo,Edad,Fecha_Nacimiento"


def test_importa_personas_enlazadas_y_rechaza_huerfanas(entorno):
    repo, imp, tmp = entorno
    preparar_siniestros(repo, imp, tmp)
    csv = ENC_ACTOR + "\n" + "\n".join([
        "1,1,0,CONDUCTOR,HERIDO,Masculino,34,1990-01-01",
        "1,,1,PEATÓN,MUERTO,Femenino,2021,1990-01-01",     # sin vehículo; edad atípica -> NULL
        "2,1,0,MOTOCICLISTA,ILESO,Masculino,25,1990-01-01",
        "2,1,0,MOTOCICLISTA,ILESO,Masculino,25,1990-01-01",  # duplicado
        "9,1,0,CONDUCTOR,HERIDO,Masculino,40,1990-01-01",   # siniestro inexistente
        "1,2,2,PASAJERO,HERIDO,Femenino,12,1990-01-01",     # mismo siniestro en otro bloque (bloque=3)
    ]) + "\n"
    pv = imp.previsualizar(subir(tmp, csv), tipo="actores", mapeo_codigo="anuario_sdm_2025")
    assert pv.columnas_personales_omitidas == ["Fecha_Nacimiento"]
    r = imp.confirmar(pv.importacion_id)
    assert r.estado == "completada", r.mensaje
    assert (r.filas_revisadas, r.filas_validas, r.filas_rechazadas) == (6, 4, 2)
    por_id = {s["id_registro"]: s for s in repo.siniestros()}
    actores = sorted(por_id[1]["actores"], key=lambda a: a["consecutivo_victima"])
    assert [a["consecutivo_victima"] for a in actores] == [0, 1, 2]     # no se perdió el del segundo bloque
    peaton = actores[1]
    assert peaton["codigo_vehiculo"] is None and peaton["edad"] is None and peaton["estado"] == "MUERTO"
    assert peaton["condicion"] == "PEATON" and peaton["sexo"] == "FEMENINO"
    assert actores[2]["rango_edad"] == "12-17"
    assert "1990-01-01" not in repr(repo.estado["siniestros"])  # la fecha de nacimiento nunca se lee
    assert r.resumen["filas_de_siniestros_no_importados"] == 1
    assert r.resumen["siniestros_de_la_fuente_sin_actores"] == 1
    # Reimportar la hoja de siniestros no borra las personas
    preparar_siniestros(repo, imp, tmp)
    assert len(repo.siniestros()[0]["actores"]) + len(repo.siniestros()[1]["actores"]) == 4


def test_reimportar_personas_reemplaza_sin_duplicar(entorno):
    repo, imp, tmp = entorno
    preparar_siniestros(repo, imp, tmp)
    csv = ENC_ACTOR + "\n1,1,0,CONDUCTOR,HERIDO,Masculino,34,\n1,1,1,PASAJERO,ILESO,Femenino,30,\n"
    for _ in range(2):
        pv = imp.previsualizar(subir(tmp, csv), tipo="actores", mapeo_codigo="anuario_sdm_2025")
        imp.confirmar(pv.importacion_id)
    s = next(s for s in repo.siniestros() if s["id_registro"] == 1)
    assert len(s["actores"]) == 2


def test_importa_vehiculos_sin_placa(entorno):
    repo, imp, tmp = entorno
    preparar_siniestros(repo, imp, tmp)
    csv = "Codigo_Siniestro,Codigo_Vehiculo,Clase,Servicio,Modalidad,Placa\n1,1,Automóvil,Particular,,XYZ987\n1,,Bus,,,\n"
    pv = imp.previsualizar(subir(tmp, csv), tipo="vehiculos", mapeo_codigo="anuario_sdm_2025")
    r = imp.confirmar(pv.importacion_id)
    assert (r.filas_validas, r.filas_rechazadas) == (1, 1)
    s = next(s for s in repo.siniestros() if s["id_registro"] == 1)
    assert s["vehiculos"] == [{"codigo_vehiculo": 1, "clase": "AUTOMOVIL", "servicio": "PARTICULAR", "modalidad": None}]
    assert "XYZ987" not in repr(repo.estado)


# ------------------------------------------------------------------ xlsx

def test_importa_desde_xlsx_eligiendo_la_hoja(entorno):
    openpyxl = pytest.importorskip("openpyxl")
    repo, imp, tmp = entorno
    libro = openpyxl.Workbook()
    ws = libro.active
    ws.title = "Siniestros"
    ws.append(["Codigo_Accidente", "Fecha_Acc", "AA_Acc", "MM_Acc", "DD_Mes_Acc", "Hora_Acc", "Min_Acc",
               "Gravedad_indicador_30d", "Localidad", "Latitud", "Longitud"])
    ws.append([10, datetime(2020, 2, 9), 2020, "Febrero", 9, 20, 40, "Con Muertos", "BOSA", 4.62, -74.18])
    ws.append([11, "02/10/2020", 2020, "Febrero", 10, 7, 0, "Solo Daños", "SUBA", None, None])
    libro.create_sheet("Vehiculos").append(["Codigo_Accidente", "Codigo_Vehiculo", "Clase", "Placa"])
    libro["Vehiculos"].append([10, 1, "BUS", "SECRETA1"])
    buf = io.BytesIO()
    libro.save(buf)
    xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    pv = imp.previsualizar(subir(tmp, buf.getvalue(), "anuario.xlsx", xlsx), tipo="siniestros",
                           mapeo_codigo="anuario_sdm_2015_2024")
    assert pv.hojas == ["Siniestros", "Vehiculos"] and pv.hoja == "Siniestros"
    r = imp.confirmar(pv.importacion_id)
    assert r.filas_validas == 2
    por_id = {s["id_registro"]: s for s in repo.siniestros()}
    assert por_id[10]["fecha_evento"] == date(2020, 2, 9) and (por_id[10]["hora"], por_id[10]["minuto"]) == (20, 40)
    assert por_id[11]["fecha_evento"] == date(2020, 2, 10) and por_id[11]["gravedad"] == "Solo Daños"
    pv = imp.previsualizar(subir(tmp, buf.getvalue(), "anuario.xlsx", xlsx), tipo="vehiculos",
                           mapeo_codigo="anuario_sdm_2015_2024")
    assert pv.hoja == "Vehiculos"
    imp.confirmar(pv.importacion_id)
    assert next(s for s in repo.siniestros() if s["id_registro"] == 10)["vehiculos"][0]["clase"] == "BUS"


# ------------------------------------------------------------------ población

def test_importa_poblacion_sumando_sexos_y_edades(entorno):
    repo, imp, tmp = entorno
    csv = "﻿ANO;CODIGO_LOCALIDAD;NOMBRE_LOCALIDAD;SEXO;EDAD;POBLACION\r\n" + "\r\n".join([
        "2025;0;Bogotá;Hombres;0;30", "2025;0;Bogotá;Mujeres;0;40",
        "2025;1;Usaquén;Hombres;0;10", "2025;1;Usaquén;Mujeres;0;20",
        "2025;17;La Candelaria;Hombres;0;15", "2025;17;La Candelaria;Mujeres;0;25",
        "2030;1;Usaquén;Hombres;0;12",
        "2025;3;Usaquén;Hombres;0;1",          # código y nombre no coinciden
        "abc;1;Usaquén;Hombres;0;1",
    ]) + "\r\n"
    pv = imp.previsualizar(subir(tmp, csv), tipo="poblacion", mapeo_codigo="poblacion_osb_localidad")
    r = imp.confirmar(pv.importacion_id)
    assert r.estado == "completada", r.mensaje
    assert (r.filas_validas, r.filas_rechazadas) == (7, 2)
    fid = fuente(repo, "poblacion_osb_localidad")
    den = repo.estado["denominadores"]
    assert den[(fid, "USAQUEN", 2025)] == 30 and den[(fid, "CANDELARIA", 2025)] == 40
    assert den[(fid, "BOGOTA", 2025)] == 70
    assert r.resumen["anios_proyectados"] == [2030]
    assert r.resumen["suma_localidades_distinta_del_total"] == {}
    f = repo.estado["fuentes"][fid]
    assert (f["periodo_inicio"], f["periodo_fin"]) == (date(2025, 1, 1), date(2030, 12, 31))


def test_poblacion_detecta_total_incoherente(entorno):
    repo, imp, tmp = entorno
    csv = "ANO;CODIGO_LOCALIDAD;NOMBRE_LOCALIDAD;POBLACION\n2025;0;Bogotá;100\n2025;1;Usaquén;60\n"
    pv = imp.previsualizar(subir(tmp, csv), tipo="poblacion", mapeo_codigo="poblacion_osb_localidad")
    r = imp.confirmar(pv.importacion_id)
    assert r.resumen["suma_localidades_distinta_del_total"] == {"2025": {"total_bogota": 100, "suma_localidades": 60}}


# ------------------------------------------------------------------ metadatos de la fuente

def test_metadatos_de_la_fuente_solo_lo_indicado(entorno):
    repo, imp, tmp = entorno
    pv = imp.previsualizar(subir(tmp, siniestros_csv(fila_2025(1))), tipo="siniestros",
                           mapeo_codigo="anuario_sdm_2025")
    imp.confirmar(pv.importacion_id, metadatos_fuente={"url": "https://ejemplo.prueba/anuario", "fecha_descarga": None})
    f = repo.estado["fuentes"][fuente(repo, "anuario_sdm_2025")]
    assert f["url"] == "https://ejemplo.prueba/anuario" and f["fecha_descarga"] is None


def test_reservar_es_exclusiva_y_luego_confirma(entorno):
    repo, imp, tmp = entorno
    pv = imp.previsualizar(subir(tmp, siniestros_csv(fila_2025(1))), tipo="siniestros",
                           mapeo_codigo="anuario_sdm_2025")
    imp.reservar(pv.importacion_id)
    assert repo.importacion(pv.importacion_id)["estado"] == "en_proceso"
    with pytest.raises(ErrorImportacion):
        imp.reservar(pv.importacion_id)
    with pytest.raises(ErrorImportacion):
        imp.confirmar(pv.importacion_id)            # sin reservada=True no se procesa dos veces
    r = imp.confirmar(pv.importacion_id, reservada=True)
    assert r.estado == "completada" and len(repo.siniestros()) == 1


def test_reservada_con_archivo_borrado_queda_fallida(entorno):
    repo, imp, tmp = entorno
    recibido = subir(tmp, siniestros_csv(fila_2025(1)))
    pv = imp.previsualizar(recibido, tipo="siniestros", mapeo_codigo="anuario_sdm_2025")
    imp.reservar(pv.importacion_id)
    recibido.ruta.unlink()
    with pytest.raises(ErrorImportacion):
        imp.confirmar(pv.importacion_id, reservada=True)
    assert repo.importacion(pv.importacion_id)["estado"] == "fallida"
