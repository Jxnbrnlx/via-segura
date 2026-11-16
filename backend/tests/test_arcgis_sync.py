"""Sincronización ArcGIS con servidor simulado y repositorio en memoria (sin red ni base de datos).

Las mismas reglas se prueban contra la base de datos real en test_repositorio_sql.py.
"""
from datetime import date, timedelta

import pytest

from app.services.arcgis_client import ClienteArcGIS
from app.services.arcgis_sync import CODIGO_FUENTE_ARCGIS, SincronizadorArcGIS
from tests.arcgis_falso import (
    ServidorArcGISFalso, accidente, actor, conjunto_basico, falla_conexion, falla_json_200,
)
from tests.repositorio_memoria import RepositorioMemoria

BASE = "https://servicio.prueba/FeatureServer"
HOY = date(2026, 11, 16)


def preparar(capas=None, pagina=2000, **kw):
    servidor = ServidorArcGISFalso(capas if capas is not None else conjunto_basico(10), max_registros=pagina)
    cliente = ClienteArcGIS(BASE, pagina=pagina, transport=servidor.transporte(), dormir=lambda s: None,
                            reintentos=1)
    repo = RepositorioMemoria()
    sync = SincronizadorArcGIS(cliente, repo, hoy=HOY, **kw)
    return servidor, repo, sync


def fuente_id(repo):
    return repo.obtener_fuente(CODIGO_FUENTE_ARCGIS).id


def test_carga_completa_guarda_siniestros_personas_vehiculos_y_causas():
    servidor, repo, sync = preparar()
    r = sync.ejecutar("completa")
    assert r.estado == "completada", r.mensaje
    assert (r.filas_revisadas, r.filas_validas, r.filas_rechazadas, r.nuevos) == (10, 10, 0, 10)
    s = sorted(repo.siniestros(), key=lambda x: x["id_registro"])[0]
    assert s["id_registro"] == 9_000_000 and s["fecha_evento"] == date(2025, 3, 1)
    assert s["gravedad"] == "Con Heridos" and s["clase_siniestro"] == "Choque" and s["localidad"] == "KENNEDY"
    assert (s["hora"], s["minuto"], s["dia_semana"]) == (14, 30, "sábado")
    assert s["coordenada_valida"] is True and s["motivo_coordenada"] is None
    assert len(s["actores"]) == 2 and len(s["vehiculos"]) == 1
    peaton = next(a for a in s["actores"] if a["condicion"] == "PEATON")
    assert peaton["codigo_vehiculo"] is None          # no se inventa un vehículo
    assert peaton["edad"] is None and peaton["rango_edad"] is None   # 2021 -> NULL
    assert len(s["causas"]) == 1                       # la causa duplicada se guarda una vez
    assert r.resumen["calidad"]["duplicado.causa"] == 10
    assert r.resumen["calidad"]["actor.edad_atipica_a_null"] == 10


def test_periodo_de_la_fuente_es_el_minimo_y_maximo_real():
    _, repo, sync = preparar()
    sync.ejecutar("completa")
    f = repo.estado["fuentes"][fuente_id(repo)]
    assert f["periodo_inicio"] == date(2025, 3, 1)
    assert f["periodo_fin"] == date(2025, 3, 1) + timedelta(days=27)
    assert f["fecha_descarga"] is not None


def test_importacion_queda_registrada_con_conteos_y_mapeo():
    _, repo, sync = preparar()
    r = sync.ejecutar("completa")
    imp = repo.importacion(r.importacion_id)
    assert imp["estado"] == "completada" and imp["tipo"] == "arcgis"
    assert (imp["filas_revisadas"], imp["filas_validas"], imp["filas_rechazadas"]) == (10, 10, 0)
    assert imp["fecha_min_evento"] == date(2025, 3, 1)
    assert "PLACA" in imp["mapeo"]["no_importados"]
    assert imp["resumen"]["fecha_mas_reciente_en_servicio"] == "2025-03-28"


def test_dos_sincronizaciones_seguidas_no_duplican():
    _, repo, sync = preparar()
    sync.ejecutar("completa")
    r2 = sync.ejecutar("completa")
    assert r2.estado == "completada"
    assert (r2.nuevos, r2.actualizados) == (0, 10)
    assert len(repo.siniestros()) == 10
    assert all(len(s["actores"]) == 2 and len(s["causas"]) == 1 for s in repo.siniestros())


def test_paginacion_recupera_todos_los_registros():
    servidor, repo, sync = preparar(conjunto_basico(25), pagina=4)
    r = sync.ejecutar("completa")
    assert r.resumen["paginas"] == 7 and len(repo.siniestros()) == 25


def test_incremental_relee_la_ventana_desde_la_fecha_maxima_guardada():
    servidor, repo, sync = preparar(ventana_dias=10)
    sync.ejecutar("completa")
    # Cambios posteriores en el servicio: una muerte posterior en un siniestro reciente y un siniestro nuevo.
    reciente = servidor.capas[2][-1]
    reciente["GRAVEDAD"] = "CON MUERTOS"
    servidor.capas[3].append(actor(reciente["FORMULARIO"], 9_000_009, 2, 1, estado="MUERTO"))
    servidor.capas[2].append(accidente(99, 9_100_000, date(2025, 4, 2)))
    servidor.peticiones.clear()

    r = sync.ejecutar("incremental")
    assert r.estado == "completada" and r.modo == "incremental"
    assert r.resumen["ventana"] == {"fecha_maxima_guardada": "2025-03-28", "dias": 10, "desde": "2025-03-18"}
    assert r.resumen["filtro"] == "FECHA_OCURRENCIA_ACC >= DATE '2025-03-18'"
    assert r.filas_revisadas == 5  # 19, 22, 25, 28 de marzo y el nuevo
    assert (r.nuevos, r.actualizados) == (1, 4)
    actualizado = next(s for s in repo.siniestros() if s["id_registro"] == 9_000_009)
    assert actualizado["gravedad"] == "Con Muertos"
    assert [a["estado"] for a in actualizado["actores"]].count("MUERTO") == 1
    assert len(repo.siniestros()) == 11


def test_incremental_sin_datos_previos_hace_carga_completa():
    _, repo, sync = preparar()
    r = sync.ejecutar("incremental")
    assert r.modo == "completa" and "carga completa" in r.resumen["nota"]
    assert len(repo.siniestros()) == 10


def test_completa_desde_un_anio():
    capas = conjunto_basico(3)
    capas[2].append(accidente(50, 8_000_000, date(2014, 6, 1)))
    _, repo, sync = preparar(capas)
    r = sync.ejecutar("completa", desde_anio=2015)
    assert r.resumen["filtro"] == "FECHA_OCURRENCIA_ACC >= DATE '2015-01-01'"
    assert {s["id_registro"] for s in repo.siniestros()} == {9_000_000, 9_000_001, 9_000_002}


def test_nunca_se_solicita_ni_se_guarda_informacion_personal():
    servidor, repo, sync = preparar()
    sync.ejecutar("completa")
    prohibidos = {"PLACA", "FECHA_NACIMIENTO", "CODIGO_ACCIDENTADO"}
    for consulta in servidor.consultas():
        if "outFields" in consulta:
            assert not prohibidos & set(consulta["outFields"].split(","))
            assert consulta["outFields"] != "*"
    texto = repr(repo.estado)
    assert "SECRETA" not in texto and "PERSONA-SECRETA" not in texto
    for s in repo.siniestros():
        for v in s["vehiculos"]:
            assert "placa" not in v
        for a in s["actores"]:
            assert not {"fecha_nacimiento", "codigo_accidentado"} & set(a)


def test_servicio_caido_marca_fallida_y_conserva_lo_guardado():
    servidor, repo, sync = preparar()
    sync.ejecutar("completa")
    antes = repr(sorted(repo.siniestros(), key=lambda s: s["id_registro"]))
    servidor.falla_permanente = falla_conexion
    r = sync.ejecutar("incremental")
    assert r.estado == "fallida"
    assert "No fue posible completar la sincronización" in r.mensaje
    assert "Se conservan 10 registros" in r.mensaje
    assert repr(sorted(repo.siniestros(), key=lambda s: s["id_registro"])) == antes
    imp = repo.importacion(r.importacion_id)
    assert imp["estado"] == "fallida" and imp["errores"] and imp["finalizada_en"] is not None
    assert imp["resumen"]["registros_conservados"] == 10


def test_falla_a_mitad_conserva_las_paginas_confirmadas():
    servidor, repo, sync = preparar(conjunto_basico(9), pagina=3)
    original = servidor._query
    llamadas = {"n": 0}

    def query_que_falla(capa, p):
        if capa == 2 and p.get("resultOffset") == "6":
            llamadas["n"] += 1
            return falla_json_200(500)(None)
        return original(capa, p)

    servidor._query = query_que_falla
    r = sync.ejecutar("completa")
    assert r.estado == "fallida"
    assert len(repo.siniestros()) == 6  # dos páginas completas confirmadas, ninguna a medias
    assert r.filas_validas == 6 and llamadas["n"] == 2  # intento + 1 reintento


def test_error_json_con_http_200_se_reporta_legible():
    servidor, repo, sync = preparar()
    servidor.fallas = [falla_json_200(400, "Invalid or missing input parameters.")]
    r = sync.ejecutar("completa")
    assert r.estado == "fallida"
    assert "ArcGIS informó un error (400)" in r.mensaje
    assert "No hay datos guardados" in r.mensaje


def test_esquema_cambiado_detiene_sin_importar():
    servidor, repo, sync = preparar()
    servidor.campos = {k: [c for c in v if c != "GRAVEDAD"] for k, v in servidor.campos.items()}
    r = sync.ejecutar("completa")
    assert r.estado == "fallida" and "2.GRAVEDAD" in r.mensaje
    assert repo.siniestros() == []


def test_coordenadas_invalidas_se_marcan_sin_imputar():
    capas = conjunto_basico(0)
    capas[2] = [
        accidente(1, 1, date(2025, 1, 1), lat=0, lon=0),
        accidente(2, 2, date(2025, 1, 2), lat=None, lon=None),
        accidente(3, 3, date(2025, 1, 3), lat=6.25, lon=-75.57),
        accidente(4, 4, date(2025, 1, 4), lat=4.6, lon=-74.1),
    ]
    _, repo, sync = preparar(capas)
    r = sync.ejecutar("completa")
    por_id = {s["id_registro"]: s for s in repo.siniestros()}
    assert por_id[1]["motivo_coordenada"] == "fuera_de_bogota" and not por_id[1]["coordenada_valida"]
    assert por_id[2]["motivo_coordenada"] == "sin_coordenada" and por_id[2]["latitud"] is None
    assert por_id[3]["motivo_coordenada"] == "fuera_de_bogota"
    assert por_id[4]["coordenada_valida"] is True
    assert r.resumen["calidad"]["coordenada.fuera_de_bogota"] == 2


def test_coordenada_incoherente_con_su_localidad_queda_sospechosa():
    capas = conjunto_basico(0)
    capas[2] = [accidente(i, i, date(2025, 1, 1) + timedelta(days=i % 200), localidad="FONTIBON",
                          lat=4.67 + (i % 10) * 0.002, lon=-74.14 + (i % 7) * 0.002) for i in range(1, 101)]
    capas[2].append(accidente(500, 500, date(2025, 2, 1), localidad="FONTIBON", lat=4.0858, lon=-74.2283))
    _, repo, sync = preparar(capas)
    r = sync.ejecutar("completa")
    s = next(s for s in repo.siniestros() if s["id_registro"] == 500)
    assert (s["coordenada_valida"], s["motivo_coordenada"]) == (False, "sospechosa")
    assert (s["latitud"], s["longitud"]) == (4.0858, -74.2283)  # no se mueve el punto
    assert r.resumen["coherencia_coordenadas"]["marcadas_sospechosas"] == 1
    # Una segunda sincronización recalcula la marca (no queda "pegada" ni se pierde)
    sync.ejecutar("completa")
    s = next(s for s in repo.siniestros() if s["id_registro"] == 500)
    assert s["motivo_coordenada"] == "sospechosa"


def test_fecha_futura_y_gravedad_desconocida_se_rechazan_con_motivo():
    capas = conjunto_basico(2)
    capas[2].append(accidente(70, 70, HOY + timedelta(days=3)))
    capas[2].append(accidente(71, 71, date(2025, 5, 5), gravedad="GRAVISIMO"))
    _, repo, sync = preparar(capas)
    r = sync.ejecutar("completa")
    assert (r.filas_revisadas, r.filas_validas, r.filas_rechazadas) == (4, 2, 2)
    assert r.resumen["calidad"]["rechazo.fecha_futura"] == 1
    assert r.resumen["categorias_no_reconocidas"]["gravedad_no_reconocida"] == {"GRAVISIMO": 1}
    errores = repo.importacion(r.importacion_id)["errores"]
    assert any("posterior a hoy" in e for e in errores)


def test_localidad_desconocida_no_se_reasigna():
    capas = conjunto_basico(0)
    capas[2] = [accidente(1, 1, date(2025, 1, 1), localidad="SOACHA")]
    _, repo, sync = preparar(capas)
    r = sync.ejecutar("completa")
    s = repo.siniestros()[0]
    assert s["localidad"] is None and s["atributos"]["localidad_original"] == "SOACHA"
    assert r.resumen["categorias_no_reconocidas"]["localidad_no_reconocida"] == {"SOACHA": 1}


def test_codigo_accidente_repetido_en_el_servicio_se_reporta():
    capas = conjunto_basico(2)
    copia = dict(capas[2][0], OBJECTID=77, FORMULARIO="PR7777777")
    capas[2].append(copia)
    _, repo, sync = preparar(capas)
    r = sync.ejecutar("completa")
    assert len(repo.siniestros()) == 2 and r.filas_rechazadas == 1
    assert r.resumen["calidad"]["duplicado.siniestro_en_servicio"] == 1


def test_registros_que_desaparecen_del_servicio_se_informan_y_no_se_borran():
    servidor, repo, sync = preparar()
    sync.ejecutar("completa")
    servidor.capas[2].pop(0)
    r = sync.ejecutar("completa")
    ausentes = r.resumen["guardados_que_ya_no_aparecen_en_el_servicio"]
    assert ausentes["cantidad"] == 1 and ausentes["ejemplos_id_registro"] == [9_000_000]
    assert len(repo.siniestros()) == 10


def test_coincidencias_con_otra_fuente_se_informan_sin_fusionar():
    _, repo, sync = preparar()
    anuario = repo.obtener_fuente("anuario_sdm_2025").id
    repo.agregar_siniestro(anuario, id_registro=9_000_000, fecha_evento=date(2024, 3, 1), localidad="KENNEDY",
                           latitud=None, longitud=None, coordenada_valida=False, motivo_coordenada="sin_coordenada")
    r = sync.ejecutar("completa")
    assert r.resumen["coincidencias_otras_fuentes"] == [
        {"fuente": "anuario_sdm_2025", "coincidencias": 1, "fecha_distinta": 1}]
    assert len(repo.siniestros(anuario)) == 1  # la otra fuente no se toca


def test_max_paginas_marca_la_carga_como_parcial():
    _, repo, sync = preparar(conjunto_basico(10), pagina=3)
    r = sync.ejecutar("completa", max_paginas=2)
    assert r.resumen["parcial"] is True and "PARCIAL" in r.mensaje
    assert len(repo.siniestros()) == 6
    assert "guardados_que_ya_no_aparecen_en_el_servicio" not in r.resumen


def test_modo_invalido():
    _, _, sync = preparar()
    with pytest.raises(ValueError):
        sync.ejecutar("total")
