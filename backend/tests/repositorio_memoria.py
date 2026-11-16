"""Repositorio en memoria con la misma semántica que RepositorioSQL (solo para pruebas).

- Clave única (fuente_id, id_registro) en siniestros.
- Reemplazo completo de personas, vehículos y causas en cada guardado.
- confirmar/revertir con instantáneas, para probar que un fallo no borra lo ya confirmado.
"""
from __future__ import annotations

import copy
from datetime import date

from app.seed_fuentes import FUENTES_ADICIONALES, FUENTES_INICIALES
from app.services.arcgis_sync import FuenteInfo, RegistroSiniestro


class RepositorioMemoria:
    def __init__(self) -> None:
        self.estado = {
            "fuentes": {i + 1: dict(f, id=i + 1, periodo_inicio=None, periodo_fin=None, fecha_descarga=None)
                        for i, f in enumerate(FUENTES_INICIALES + FUENTES_ADICIONALES)},
            "siniestros": {},  # (fuente_id, id_registro) -> dict con hijos
            "importaciones": {},
            "denominadores": {},  # (fuente_id, localidad, anio) -> poblacion
        }
        self._confirmado = copy.deepcopy(self.estado)

    # utilidades de prueba
    def siniestros(self, fuente_id: int | None = None) -> list[dict]:
        return [s for (f, _), s in self.estado["siniestros"].items() if fuente_id is None or f == fuente_id]

    def importacion(self, importacion_id: int) -> dict:
        return self.estado["importaciones"][importacion_id]

    def agregar_siniestro(self, fuente_id: int, **datos) -> None:
        self.estado["siniestros"][(fuente_id, datos["id_registro"])] = dict(
            datos, fuente_id=fuente_id, actores=[], vehiculos=[], causas=[], id_interno=self._siguiente_id())
        self.confirmar()

    # protocolo Repositorio
    def obtener_fuente(self, codigo: str) -> FuenteInfo:
        for f in self.estado["fuentes"].values():
            if f["codigo"] == codigo:
                return FuenteInfo(f["id"], f["codigo"], f["prioridad"])
        raise LookupError(codigo)

    def crear_importacion(self, fuente_id, modo, usuario_id, mapeo) -> int:
        nuevo = len(self.estado["importaciones"]) + 1
        self.estado["importaciones"][nuevo] = {"id": nuevo, "fuente_id": fuente_id, "modo": modo, "tipo": "arcgis",
                                               "estado": "en_proceso", "mapeo": mapeo}
        return nuevo

    def actualizar_importacion(self, importacion_id, **campos) -> None:
        self.estado["importaciones"][importacion_id].update(campos)

    def fecha_maxima(self, fuente_id) -> date | None:
        fechas = [s["fecha_evento"] for s in self.siniestros(fuente_id)]
        return max(fechas) if fechas else None

    def periodo_real(self, fuente_id):
        fechas = [s["fecha_evento"] for s in self.siniestros(fuente_id)]
        return (min(fechas), max(fechas)) if fechas else (None, None)

    def contar_registros(self, fuente_id) -> int:
        return len(self.siniestros(fuente_id))

    def guardar_lote(self, fuente_id, importacion_id, registros: list[RegistroSiniestro], reemplazar_hijos=True):
        nuevos = actualizados = 0
        for r in registros:
            clave = (fuente_id, r.id_registro)
            previo = self.estado["siniestros"].get(clave)
            if previo is not None:
                actualizados += 1
            else:
                nuevos += 1
            hijos = ({"actores": copy.deepcopy(r.actores), "vehiculos": copy.deepcopy(r.vehiculos),
                      "causas": copy.deepcopy(r.causas)} if reemplazar_hijos or previo is None else
                     {k: previo[k] for k in ("actores", "vehiculos", "causas")})
            self.estado["siniestros"][clave] = dict(
                copy.deepcopy(r.siniestro), fuente_id=fuente_id, importacion_id=importacion_id,
                id_interno=previo["id_interno"] if previo else self._siguiente_id(), **hijos)
        return nuevos, actualizados

    def _siguiente_id(self) -> int:
        self.estado["ultimo_id"] = self.estado.get("ultimo_id", 0) + 1
        return self.estado["ultimo_id"]

    # importador de archivos
    def crear_importacion_archivo(self, *, fuente_id, modo, archivo, hoja, mapeo, resumen, usuario_id) -> int:
        nuevo = len(self.estado["importaciones"]) + 1
        self.estado["importaciones"][nuevo] = {
            "id": nuevo, "fuente_id": fuente_id, "modo": modo, "tipo": "excel", "estado": "previsualizada",
            "archivo": archivo, "hoja": hoja, "mapeo": copy.deepcopy(mapeo), "resumen": copy.deepcopy(resumen),
            "usuario_id": usuario_id}
        return nuevo

    def reservar_importacion(self, importacion_id, estados):
        imp = self.estado["importaciones"].get(importacion_id)
        if imp is None or imp["estado"] not in estados:
            return False
        imp["estado"] = "en_proceso"
        return True

    def obtener_importacion(self, importacion_id):
        imp = self.estado["importaciones"].get(importacion_id)
        return copy.deepcopy(imp) if imp else None

    def mapa_ids(self, fuente_id, ids):
        return {i: self.estado["siniestros"][(fuente_id, i)]["id_interno"] for i in ids
                if (fuente_id, i) in self.estado["siniestros"]}

    def _por_id_interno(self):
        return {s["id_interno"]: s for s in self.estado["siniestros"].values()}

    def reemplazar_hijos(self, tipo, filas, limpiar):
        por_id = self._por_id_interno()
        for i in limpiar:
            por_id[i][tipo] = []
        for f in filas:
            por_id[f["siniestro_id"]][tipo].append({k: v for k, v in f.items() if k != "siniestro_id"})

    def siniestros_sin_hijos(self, fuente_id, tipo):
        return sum(1 for s in self.siniestros(fuente_id) if not s[tipo])

    def upsert_denominadores(self, fuente_id, filas):
        nuevos = actualizados = 0
        for localidad, anio, poblacion in filas:
            clave = (fuente_id, localidad, anio)
            if clave in self.estado["denominadores"]:
                actualizados += 1
            else:
                nuevos += 1
            self.estado["denominadores"][clave] = poblacion
        return nuevos, actualizados

    def ids_desde(self, fuente_id, desde) -> set[int]:
        return {s["id_registro"] for s in self.siniestros(fuente_id) if desde is None or s["fecha_evento"] >= desde}

    def puntos_para_coherencia(self, fuente_id):
        return [(s["id_registro"], s["localidad"], s["latitud"], s["longitud"]) for s in self.siniestros(fuente_id)
                if s["latitud"] is not None and (s["coordenada_valida"] or s["motivo_coordenada"] == "sospechosa")]

    def aplicar_coherencia(self, fuente_id, sospechosas) -> int:
        for s in self.siniestros(fuente_id):
            if s["motivo_coordenada"] == "sospechosa":
                s["coordenada_valida"], s["motivo_coordenada"] = True, None
            if s["id_registro"] in sospechosas:
                s["coordenada_valida"], s["motivo_coordenada"] = False, "sospechosa"
        return len(sospechosas)

    def coincidencias_otras_fuentes(self, fuente_id):
        propios = {s["id_registro"]: s for s in self.siniestros(fuente_id)}
        salida = []
        for f in self.estado["fuentes"].values():
            if f["id"] == fuente_id:
                continue
            otros = [s for s in self.siniestros(f["id"]) if s["id_registro"] in propios]
            if otros:
                salida.append({"fuente": f["codigo"], "coincidencias": len(otros),
                               "fecha_distinta": sum(1 for s in otros
                                                     if s["fecha_evento"] != propios[s["id_registro"]]["fecha_evento"])})
        return salida

    def actualizar_fuente(self, fuente_id, **campos) -> None:
        self.estado["fuentes"][fuente_id].update(campos)

    def confirmar(self) -> None:
        self._confirmado = copy.deepcopy(self.estado)

    def revertir(self) -> None:
        self.estado = copy.deepcopy(self._confirmado)
