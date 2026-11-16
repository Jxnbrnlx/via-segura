"""Sincronización de extremo a extremo contra la base de datos real (SQLite temporal) con el
servidor ArcGIS simulado. Verifica idempotencia, reemplazo de hijos, restricciones CHECK,
conservación ante fallos y que no se guardan datos personales."""
from datetime import date

from sqlalchemy import func, select

from app import models
from app.services.arcgis_client import ClienteArcGIS
from app.services.arcgis_sync import CODIGO_FUENTE_ARCGIS, SincronizadorArcGIS
from app.services.repositorio_sql import RepositorioSQL, asegurar_fuente, sembrar_fuentes
from tests.arcgis_falso import ServidorArcGISFalso, accidente, actor, conjunto_basico, falla_conexion
from tests.conftest import nuevo_siniestro

HOY = date(2026, 11, 16)


def sincronizador(sesion, servidor, pagina=2000):
    cliente = ClienteArcGIS("https://servicio.prueba/FeatureServer", pagina=pagina,
                            transport=servidor.transporte(), dormir=lambda s: None, reintentos=1)
    return SincronizadorArcGIS(cliente, RepositorioSQL(sesion), hoy=HOY)


def contar(sesion, modelo):
    return sesion.scalar(select(func.count()).select_from(modelo))


def test_sembrar_fuentes_es_idempotente_y_sin_periodo_inventado(sesion):
    assert sembrar_fuentes(sesion) == 5
    sesion.commit()
    assert sembrar_fuentes(sesion) == 0
    arcgis = asegurar_fuente(sesion, CODIGO_FUENTE_ARCGIS)
    assert arcgis.prioridad == 1 and arcgis.periodo_inicio is None and arcgis.periodo_fin is None


def test_sincronizacion_completa_guarda_todo(sesion):
    r = sincronizador(sesion, ServidorArcGISFalso(conjunto_basico(10)), pagina=4).ejecutar("completa")
    assert r.estado == "completada", r.mensaje
    assert contar(sesion, models.SiniestroEvento) == 10
    assert contar(sesion, models.ActorVial) == 20
    assert contar(sesion, models.VehiculoEvento) == 10
    assert contar(sesion, models.CausaEvento) == 10  # duplicados de VM_ACC_CAUSA eliminados
    peaton = sesion.scalars(select(models.ActorVial).where(models.ActorVial.condicion == "PEATON")).first()
    assert peaton.codigo_vehiculo is None and peaton.edad is None
    fuente = asegurar_fuente(sesion, CODIGO_FUENTE_ARCGIS)
    assert fuente.periodo_inicio == date(2025, 3, 1) and fuente.periodo_fin == date(2025, 3, 28)
    imp = sesion.get(models.Importacion, r.importacion_id)
    assert imp.estado == "completada" and imp.filas_validas == 10 and imp.finalizada_en is not None
    assert imp.resumen["calidad"]["duplicado.causa"] == 10


def test_dos_sincronizaciones_no_duplican_ni_acumulan_hijos(sesion):
    servidor = ServidorArcGISFalso(conjunto_basico(10))
    sincronizador(sesion, servidor).ejecutar("completa")
    r = sincronizador(sesion, servidor).ejecutar("completa")
    assert (r.nuevos, r.actualizados) == (0, 10)
    assert contar(sesion, models.SiniestroEvento) == 10
    assert contar(sesion, models.ActorVial) == 20
    assert contar(sesion, models.CausaEvento) == 10


def test_incremental_actualiza_y_reemplaza_personas(sesion):
    servidor = ServidorArcGISFalso(conjunto_basico(10))
    sincronizador(sesion, servidor).ejecutar("completa")
    reciente = servidor.capas[2][-1]
    reciente["GRAVEDAD"] = "CON MUERTOS"
    servidor.capas[3].append(actor(reciente["FORMULARIO"], 9_000_009, 2, 1, estado="MUERTO"))
    r = sincronizador(sesion, servidor).ejecutar("incremental")
    assert r.estado == "completada" and r.modo == "incremental"
    s = sesion.scalars(select(models.SiniestroEvento).where(models.SiniestroEvento.id_registro == 9_000_009)).one()
    sesion.refresh(s)
    assert s.gravedad == "Con Muertos"
    assert sorted(a.estado for a in s.actores) == ["HERIDO", "HERIDO", "MUERTO"]
    assert contar(sesion, models.ActorVial) == 21


def test_coordenadas_respetan_las_restricciones_de_la_base(sesion):
    capas = conjunto_basico(0)
    capas[2] = [accidente(i, i, date(2025, 1, 1), localidad="FONTIBON", lat=4.67 + (i % 10) * 0.002,
                          lon=-74.14 + (i % 7) * 0.002) for i in range(1, 101)]
    capas[2] += [accidente(500, 500, date(2025, 2, 1), localidad="FONTIBON", lat=4.0858, lon=-74.2283),
                 accidente(501, 501, date(2025, 2, 2), lat=None, lon=None),
                 accidente(502, 502, date(2025, 2, 3), lat=95.0, lon=-74.1)]
    r = sincronizador(sesion, ServidorArcGISFalso(capas)).ejecutar("completa")
    assert r.estado == "completada", r.mensaje
    por_id = {s.id_registro: s for s in sesion.scalars(select(models.SiniestroEvento))}
    assert (por_id[500].coordenada_valida, por_id[500].motivo_coordenada) == (False, "sospechosa")
    assert (por_id[501].latitud, por_id[501].motivo_coordenada) == (None, "sin_coordenada")
    assert (por_id[502].latitud, por_id[502].motivo_coordenada) == (None, "fuera_de_rango")
    validas = sesion.scalar(select(func.count()).where(models.SiniestroEvento.coordenada_valida.is_(True)))
    assert validas == 100


def test_fallo_del_servicio_conserva_datos_y_registra_importacion_fallida(sesion):
    servidor = ServidorArcGISFalso(conjunto_basico(5))
    sincronizador(sesion, servidor).ejecutar("completa")
    servidor.falla_permanente = falla_conexion
    r = sincronizador(sesion, servidor).ejecutar("incremental")
    assert r.estado == "fallida"
    assert contar(sesion, models.SiniestroEvento) == 5
    imp = sesion.get(models.Importacion, r.importacion_id)
    assert imp.estado == "fallida" and imp.errores and "conectarse" in imp.errores[0]


def test_no_se_guardan_datos_personales(sesion):
    sincronizador(sesion, ServidorArcGISFalso(conjunto_basico(3), devolver_todo=True)).ejecutar("completa")
    for modelo in (models.ActorVial, models.VehiculoEvento, models.CausaEvento, models.SiniestroEvento):
        for fila in sesion.scalars(select(modelo)):
            texto = repr({c.name: getattr(fila, c.name) for c in modelo.__table__.columns})
            assert "SECRETA" not in texto


def test_coincidencias_con_anuario_se_informan_sin_tocarlo(sesion):
    anuario = asegurar_fuente(sesion, "anuario_sdm_2025")
    sesion.add(nuevo_siniestro(anuario.id, 9_000_000, fecha_evento=date(2024, 3, 1), anio=2024))
    sesion.commit()
    r = sincronizador(sesion, ServidorArcGISFalso(conjunto_basico(3))).ejecutar("completa")
    [coincidencia] = r.resumen["coincidencias_otras_fuentes"]
    assert coincidencia["fuente"] == "anuario_sdm_2025"
    assert coincidencia["coincidencias"] == 1 and coincidencia["fecha_distinta"] == 1
    assert coincidencia["prevalece"] == CODIGO_FUENTE_ARCGIS
    assert coincidencia["ejemplos_fecha_distinta"][0]["otra_fuente"] == "2024-03-01"
    assert contar(sesion, models.SiniestroEvento) == 4
