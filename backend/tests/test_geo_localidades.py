"""Polígonos de localidades: validación, detección del atributo, simplificación y punto en polígono.
Geometrías SINTÉTICAS (cuadrados), no son límites reales."""
import io
import json

import pytest

from app.services import geo_localidades as g
from app.services.archivos import recibir_archivo
from app.services.importador_excel import ImportadorArchivos
from tests.repositorio_memoria import RepositorioMemoria


def cuadrado(x, y, lado=0.01, puntos_por_lado=1):
    pasos = [i / puntos_por_lado for i in range(puntos_por_lado)]
    anillo = ([[x + lado * t, y] for t in pasos] + [[x + lado, y + lado * t] for t in pasos]
              + [[x + lado * (1 - t), y + lado] for t in pasos] + [[x, y + lado * (1 - t)] for t in pasos])
    return [anillo + [anillo[0]]]


def coleccion(propiedades_y_geom, crs=None):
    datos = {"type": "FeatureCollection",
             "features": [{"type": "Feature", "properties": p, "geometry": geom} for p, geom in propiedades_y_geom]}
    if crs:
        datos["crs"] = crs
    return datos


def guardar(tmp_path, datos, nombre="l.geojson"):
    ruta = tmp_path / nombre
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    return ruta


def test_detecta_el_atributo_de_nombre_y_agrupa(tmp_path):
    datos = coleccion([
        ({"LocCodigo": "01", "LocNombre": "USAQUÉN"}, {"type": "Polygon", "coordinates": cuadrado(-74.05, 4.70)}),
        ({"LocCodigo": "17", "LocNombre": "LA CANDELARIA"}, {"type": "Polygon", "coordinates": cuadrado(-74.07, 4.59)}),
        ({"LocCodigo": "17", "LocNombre": "LA CANDELARIA"}, {"type": "Polygon", "coordinates": cuadrado(-74.08, 4.59)}),
    ], crs={"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}})
    r = g.cargar_y_validar(guardar(tmp_path, datos))
    assert r.propiedad_localidad == "LocNombre"
    assert r.localidades == ["USAQUEN", "CANDELARIA"] and "SUMAPAZ" in r.faltantes
    candelaria = next(f for f in r.coleccion["features"] if f["properties"]["localidad"] == "CANDELARIA")
    assert candelaria["properties"] == {"localidad": "CANDELARIA", "nombre": "La Candelaria", "codigo": 17}
    assert len(candelaria["geometry"]["coordinates"]) == 2
    assert any("varios polígonos" in a for a in r.advertencias)


def test_solo_codigo_tambien_sirve(tmp_path):
    datos = coleccion([({"COD": 20}, {"type": "Polygon", "coordinates": cuadrado(-74.2, 3.9)})])
    assert g.cargar_y_validar(guardar(tmp_path, datos)).localidades == ["SUMAPAZ"]


def test_archivo_de_manzanas_se_rechaza_sin_leerlo_completo(tmp_path):
    datos = coleccion([({"MANCODIGO": "003203029", "SECCODIGO": "003203", "SHAPE_AREA": 9.3e-07},
                        {"type": "Polygon", "coordinates": cuadrado(-74.07, 4.59, 0.0005)})],
                      crs={"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}})
    with pytest.raises(g.ErrorGeo, match="MANCODIGO"):
        g.cargar_y_validar(guardar(tmp_path, datos))


def test_coordenadas_proyectadas_se_rechazan(tmp_path):
    datos = coleccion([({"LocNombre": "BOSA"}, {"type": "Polygon", "coordinates": [[[92000, 100000], [93000, 100000],
                                                                                   [93000, 101000], [92000, 100000]]]})])
    with pytest.raises(g.ErrorGeo, match="proyectado"):
        g.cargar_y_validar(guardar(tmp_path, datos))


def test_crs_distinto_se_rechaza(tmp_path):
    datos = coleccion([({"LocNombre": "BOSA"}, {"type": "Polygon", "coordinates": cuadrado(-74.19, 4.62)})],
                      crs={"type": "name", "properties": {"name": "EPSG:3116"}})
    with pytest.raises(g.ErrorGeo, match="EPSG:4326"):
        g.cargar_y_validar(guardar(tmp_path, datos))


def test_geometria_no_poligonal(tmp_path):
    datos = coleccion([({"LocNombre": "BOSA"}, {"type": "Point", "coordinates": [-74.19, 4.62]})])
    with pytest.raises(g.ErrorGeo, match="polígonos"):
        g.cargar_y_validar(guardar(tmp_path, datos))


def test_si_un_poligono_no_tiene_localidad_reconocible(tmp_path):
    datos = coleccion([({"LocNombre": "BOSA"}, {"type": "Polygon", "coordinates": cuadrado(-74.19, 4.62)}),
                       ({"LocNombre": "SOACHA"}, {"type": "Polygon", "coordinates": cuadrado(-74.22, 4.58)})])
    with pytest.raises(g.ErrorGeo, match="todos los polígonos"):
        g.cargar_y_validar(guardar(tmp_path, datos))


def test_simplificacion_reduce_vertices_y_mantiene_anillos_cerrados(tmp_path):
    datos = coleccion([({"LocNombre": "KENNEDY"}, {"type": "Polygon",
                                                   "coordinates": cuadrado(-74.15, 4.62, 0.02, puntos_por_lado=50)})])
    r = g.cargar_y_validar(guardar(tmp_path, datos), tolerancia=0.0001)
    anillo = r.coleccion["features"][0]["geometry"]["coordinates"][0][0]
    assert r.vertices_antes == 201 and len(anillo) < 20
    assert anillo[0] == anillo[-1] and len(anillo) >= 4


def test_punto_en_poligono_con_hueco():
    poligono = [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]], [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]]
    assert g.punto_en_multipoligono(1, 1, [poligono])
    assert not g.punto_en_multipoligono(5, 5, [poligono])
    assert not g.punto_en_multipoligono(11, 5, [poligono])


def test_importador_publica_el_geojson_normalizado(tmp_path):
    datos = coleccion([({"LocNombre": "Bosa"}, {"type": "Polygon", "coordinates": cuadrado(-74.19, 4.62)})])
    recibido = recibir_archivo(io.BytesIO(json.dumps(datos).encode()), "localidades.geojson", "application/geo+json",
                               tmp_path / "cargas", max_bytes=2**20)
    repo = RepositorioMemoria()
    imp = ImportadorArchivos(repo, tmp_path / "cargas", tmp_path / "geo")
    pv = imp.previsualizar(recibido, tipo="localidades")
    assert pv.validacion["localidades_encontradas"] == ["BOSA"] and pv.puede_confirmar
    assert not (tmp_path / "geo" / g.NOMBRE_ARCHIVO).exists()  # previsualizar no publica
    r = imp.confirmar(pv.importacion_id)
    assert r.estado == "completada"
    publicado = g.cargar_guardado(tmp_path / "geo")
    assert publicado["features"][0]["properties"]["localidad"] == "BOSA"
    assert g.localidad_de_punto(-74.185, 4.625, publicado) == "BOSA"
    assert g.localidad_de_punto(-74.0, 4.7, publicado) is None
