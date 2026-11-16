"""Cliente ArcGIS con respuestas simuladas (sin red)."""
from datetime import date

import httpx
import pytest

from app.services.arcgis_client import (
    CAMPOS_ACTOR_VIAL, CAMPOS_VEHICULO, ClienteArcGIS, ErrorArcGIS, ServicioNoDisponible, sql_lista_texto,
    validar_campos,
)
from tests.arcgis_falso import (
    ServidorArcGISFalso, accidente, conjunto_basico, falla_conexion, falla_http, falla_json_200,
)

BASE = "https://servicio.prueba/arcgis/rest/services/X/FeatureServer"


def nuevo_cliente(servidor, **kw):
    esperas = []
    cliente = ClienteArcGIS(BASE, transport=servidor.transporte(), dormir=esperas.append, **kw)
    return cliente, esperas


def test_paginacion_recorre_todo_en_orden_de_objectid():
    servidor = ServidorArcGISFalso(conjunto_basico(10), max_registros=3)
    cliente, _ = nuevo_cliente(servidor, pagina=3)
    paginas = list(cliente.iterar_paginas(2, "1=1", ["OBJECTID", "CODIGO_ACCIDENTE"]))
    assert [len(p) for p in paginas] == [3, 3, 3, 1]
    assert [r["OBJECTID"] for p in paginas for r in p] == list(range(1, 11))
    consultas = servidor.consultas(2)
    assert [q["resultOffset"] for q in consultas] == ["0", "3", "6", "9"]
    assert all(q["orderByFields"] == "OBJECTID ASC" and q["resultRecordCount"] == "3" for q in consultas)


def test_paginacion_exacta_termina_con_pagina_vacia():
    servidor = ServidorArcGISFalso(conjunto_basico(6), max_registros=3)
    cliente, _ = nuevo_cliente(servidor, pagina=3)
    assert sum(len(p) for p in cliente.iterar_paginas(2, "1=1", ["OBJECTID"])) == 6


def test_pagina_no_puede_superar_maxrecordcount():
    with pytest.raises(ValueError):
        ClienteArcGIS(BASE, pagina=5000)


def test_error_json_con_http_200_no_reintentable():
    servidor = ServidorArcGISFalso(conjunto_basico(2))
    servidor.fallas = [falla_json_200(400, "Invalid query")]
    cliente, esperas = nuevo_cliente(servidor)
    with pytest.raises(ErrorArcGIS) as exc:
        cliente.contar(2)
    assert not isinstance(exc.value, ServicioNoDisponible)
    assert "400" in exc.value.mensaje and "Invalid query" in exc.value.mensaje
    assert exc.value.detalles == ["detalle simulado"]
    assert len(servidor.peticiones) == 1 and esperas == []


def test_error_json_200_transitorio_se_reintenta_y_recupera():
    servidor = ServidorArcGISFalso(conjunto_basico(4))
    servidor.fallas = [falla_json_200(500), falla_json_200(503)]
    cliente, esperas = nuevo_cliente(servidor, reintentos=4, espera_base_s=1.5)
    assert cliente.contar(2) == 4
    assert esperas == [1.5, 3.0]


def test_http_503_agota_reintentos_con_espera_creciente():
    servidor = ServidorArcGISFalso({})
    servidor.falla_permanente = falla_http(503)
    cliente, esperas = nuevo_cliente(servidor, reintentos=3, espera_base_s=1.0, espera_max_s=3.0)
    with pytest.raises(ServicioNoDisponible) as exc:
        cliente.contar(2)
    assert esperas == [1.0, 2.0, 3.0]  # exponencial con tope
    assert len(servidor.peticiones) == 4
    assert "503" in exc.value.mensaje and "reintentos" in exc.value.mensaje


def test_caida_de_red_termina_en_servicio_no_disponible():
    servidor = ServidorArcGISFalso({})
    servidor.falla_permanente = falla_conexion
    cliente, _ = nuevo_cliente(servidor, reintentos=2)
    with pytest.raises(ServicioNoDisponible) as exc:
        cliente.metadatos(2)
    assert "conectarse" in exc.value.mensaje


def test_tiempo_de_espera_agotado():
    def lento(request):
        raise httpx.ReadTimeout("lento", request=request)

    servidor = ServidorArcGISFalso({})
    servidor.falla_permanente = lento
    cliente, _ = nuevo_cliente(servidor, reintentos=1)
    with pytest.raises(ServicioNoDisponible) as exc:
        cliente.contar(2)
    assert "tiempo de espera" in exc.value.mensaje


def test_respuesta_html_se_trata_como_caida_temporal():
    servidor = ServidorArcGISFalso(conjunto_basico(1))
    servidor.fallas = [lambda r: httpx.Response(200, text="<html>Mantenimiento</html>")]
    cliente, esperas = nuevo_cliente(servidor)
    assert cliente.contar(2) == 1
    assert len(esperas) == 1


def test_http_404_no_se_reintenta():
    servidor = ServidorArcGISFalso({})
    servidor.falla_permanente = falla_http(404)
    cliente, esperas = nuevo_cliente(servidor)
    with pytest.raises(ErrorArcGIS):
        cliente.contar(2)
    assert esperas == []


@pytest.mark.parametrize("campos", [["*"], "*", [], ["FORMULARIO", "PLACA"], ["fecha_nacimiento"],
                                    ["CODIGO_ACCIDENTADO"]])
def test_outfields_explicito_y_sin_datos_personales(campos):
    with pytest.raises(ValueError):
        validar_campos(campos)


def test_no_se_hace_peticion_si_los_campos_son_prohibidos():
    servidor = ServidorArcGISFalso(conjunto_basico(1))
    cliente, _ = nuevo_cliente(servidor)
    with pytest.raises(ValueError):
        cliente.consultar(5, "1=1", ["FORMULARIO", "PLACA"])
    assert servidor.peticiones == []


def test_campos_de_la_sincronizacion_no_incluyen_datos_personales():
    for campos in (CAMPOS_ACTOR_VIAL, CAMPOS_VEHICULO):
        assert validar_campos(campos)
        assert not {"PLACA", "FECHA_NACIMIENTO", "CODIGO_ACCIDENTADO"} & set(campos)


def test_consulta_usa_post_con_outfields_explicito():
    servidor = ServidorArcGISFalso(conjunto_basico(2))
    cliente, _ = nuevo_cliente(servidor)
    cliente.consultar(5, "1=1", CAMPOS_VEHICULO)
    metodo, ruta, params = servidor.peticiones[-1]
    assert metodo == "POST" and ruta.endswith("/5/query")
    assert params["outFields"] == ",".join(CAMPOS_VEHICULO)
    assert params["f"] == "json" and params["returnGeometry"] == "false"


def test_si_el_servidor_devuelve_placa_igual_se_descarta():
    servidor = ServidorArcGISFalso(conjunto_basico(2), devolver_todo=True)
    cliente, _ = nuevo_cliente(servidor)
    registros, _ = cliente.consultar(5, "1=1", CAMPOS_VEHICULO)
    assert registros and all("PLACA" not in r for r in registros)
    registros, _ = cliente.consultar(3, "1=1", CAMPOS_ACTOR_VIAL)
    assert all("CODIGO_ACCIDENTADO" not in r and "FECHA_NACIMIENTO" not in r for r in registros)


def test_geometria_se_adjunta_cuando_se_pide():
    servidor = ServidorArcGISFalso({2: [accidente(1, 1, date(2025, 1, 1))]})

    def con_geometria(request):
        return httpx.Response(200, json={"features": [{"attributes": {"OBJECTID": 1},
                                                       "geometry": {"x": -74.1, "y": 4.6}}]})
    servidor.fallas = [con_geometria]
    cliente, _ = nuevo_cliente(servidor)
    registros, _ = cliente.consultar(2, "1=1", ["OBJECTID"], geometria=True)
    assert registros[0]["_geometria"] == {"x": -74.1, "y": 4.6}


def test_conteo_por_valor_lee_estadisticas_agrupadas():
    servidor = ServidorArcGISFalso({})
    servidor.fallas = [lambda r: httpx.Response(200, json={"features": [
        {"attributes": {"GRAVEDAD": "CON HERIDOS", "n": 7}}, {"attributes": {"GRAVEDAD": None, "N": 2}}]})]
    cliente, _ = nuevo_cliente(servidor)
    assert cliente.conteo_por_valor(2, "GRAVEDAD") == {"CON HERIDOS": 7, None: 2}
    params = servidor.peticiones[-1][2]
    assert params["groupByFieldsForStatistics"] == "GRAVEDAD"
    assert '"statisticType": "count"' in params["outStatistics"]


def test_estadisticas_no_sobre_campos_personales():
    cliente, _ = nuevo_cliente(ServidorArcGISFalso({}))
    with pytest.raises(ValueError):
        cliente.conteo_por_valor(5, "PLACA")


def test_valor_extremo():
    servidor = ServidorArcGISFalso(conjunto_basico(5))
    cliente, _ = nuevo_cliente(servidor)
    maximo = cliente.valor_extremo(2, "FECHA_OCURRENCIA_ACC", maximo=True)
    assert maximo == max(r["FECHA_OCURRENCIA_ACC"] for r in servidor.capas[2])
    assert servidor.peticiones[-1][2]["orderByFields"] == "FECHA_OCURRENCIA_ACC DESC"


def test_sql_lista_texto_escapa_comillas():
    assert sql_lista_texto(["A1", "B'2"]) == "('A1', 'B''2')"
