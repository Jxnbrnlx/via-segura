"""Datos DEMO sintéticos para probar VÍA SEGURA sin datos oficiales.

Todo lo que produce este módulo es INVENTADO con un generador pseudoaleatorio con semilla fija
(el mismo resultado en cada ejecución). No reproduce ningún siniestro real y no debe usarse para conclusiones.

- Las cantidades, gravedades, horas, clases y personas se sortean con proporciones elegidas a mano para que
  la aplicación tenga algo que mostrar; no son estadísticas oficiales.
- Las ubicaciones se dispersan (± ~250 m) alrededor de "anclas": centros de celdas de ~500 m, redondeados, con
  más registros por localidad en el anuario público 2025 (data/demo/anclas_localidades.json). Así los puntos
  caen sobre zonas urbanas plausibles sin copiar ninguna coordenada real.
- A propósito se incluyen casos difíciles: registros sin coordenada, con coordenada fuera de Bogotá, sin
  localidad y sin hora, para que se vean los avisos de calidad.
- Nunca se generan placas, fechas de nacimiento, nombres ni documentos.

La carga en la base de datos pasa por el mismo importador que los anuarios oficiales (dos pasos:
previsualizar y confirmar), con el mapeo data/mapeos/demo_sintetica.json.
"""
from __future__ import annotations

import csv
import json
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

CODIGO_FUENTE = "demo_sintetica"
CODIGO_MAPEO = "demo_sintetica"
ANCLAS = Path(__file__).resolve().parents[1] / "data" / "demo" / "anclas_localidades.json"
PRIMER_CODIGO = 9_000_001  # códigos altos y fáciles de reconocer

LOCALIDADES_ARCHIVO = {  # clave canónica -> como lo escribiría un archivo (mayúsculas, con tildes a veces)
    "USAQUEN": "USAQUÉN", "CHAPINERO": "CHAPINERO", "SANTA FE": "SANTA FE", "SAN CRISTOBAL": "SAN CRISTÓBAL",
    "USME": "USME", "TUNJUELITO": "TUNJUELITO", "BOSA": "BOSA", "KENNEDY": "KENNEDY", "FONTIBON": "FONTIBÓN",
    "ENGATIVA": "ENGATIVÁ", "SUBA": "SUBA", "BARRIOS UNIDOS": "BARRIOS UNIDOS", "TEUSAQUILLO": "TEUSAQUILLO",
    "LOS MARTIRES": "LOS MÁRTIRES", "ANTONIO NARIÑO": "ANTONIO NARIÑO", "PUENTE ARANDA": "PUENTE ARANDA",
    "CANDELARIA": "LA CANDELARIA", "RAFAEL URIBE URIBE": "RAFAEL URIBE URIBE", "CIUDAD BOLIVAR": "CIUDAD BOLÍVAR",
    "SUMAPAZ": "SUMAPAZ",
}

# Proporciones INVENTADAS para la demostración.
GRAVEDADES = (("Solo Daños", 0.45), ("Con Heridos", 0.52), ("Con Muertos", 0.03))
CLASES = (("Choque", 0.70), ("Atropello", 0.14), ("Caída de ocupante", 0.08), ("Volcamiento", 0.04),
          ("Autolesión", 0.02), ("Otro", 0.015), ("Incendio", 0.005))
HORAS = [1, 1, 1, 1, 1, 2, 4, 6, 6, 5, 4, 4, 5, 5, 5, 5, 6, 7, 7, 6, 4, 3, 2, 1]  # pesos por hora (0-23)
DIAS = [1.0, 1.0, 1.0, 1.05, 1.15, 1.2, 0.9]  # lunes..domingo
VEHICULOS = (("AUTOMOVIL", 0.40), ("MOTOCICLETA", 0.28), ("CAMIONETA", 0.10), ("BUS", 0.07),
             ("CAMION", 0.05), ("BICICLETA", 0.06), ("CAMPERO", 0.04))
SERVICIOS = (("PARTICULAR", 0.75), ("PUBLICO", 0.22), ("OFICIAL", 0.03))
VIAS = ("AK", "AC", "KR", "CL", "TV", "DG", "AV")

ENC_SINIESTROS = ["Codigo_Siniestro", "Formulario", "Fecha", "Hora", "Minuto", "Localidad", "Direccion", "Clase",
                  "Gravedad", "Latitud", "Longitud"]
ENC_ACTORES = ["Codigo_Siniestro", "Consecutivo", "Codigo_Vehiculo", "Estado", "Condicion", "Sexo", "Edad"]
ENC_VEHICULOS = ["Codigo_Siniestro", "Codigo_Vehiculo", "Clase", "Servicio"]


@dataclass
class DatosDemo:
    siniestros: list[dict] = field(default_factory=list)
    actores: list[dict] = field(default_factory=list)
    vehiculos: list[dict] = field(default_factory=list)


def _elegir(rng: random.Random, opciones) -> str:
    return rng.choices([o for o, _ in opciones], weights=[p for _, p in opciones])[0]


def _cargar_anclas(ruta: Path = ANCLAS) -> dict[str, list[list[float]]]:
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def _fecha(rng: random.Random, desde: date, hasta: date) -> date:
    while True:
        d = desde + timedelta(days=rng.randrange((hasta - desde).days + 1))
        if rng.random() < DIAS[d.weekday()] / max(DIAS):
            return d


def _direccion(rng: random.Random) -> str:
    a, b = rng.sample(VIAS, 2)
    return f"{a} {rng.randint(1, 180)} {b} {rng.randint(1, 160)}"


def _edad(rng: random.Random, condicion: str) -> int | str:
    if rng.random() < 0.06:
        return ""  # sin dato
    if condicion == "PEATON" and rng.random() < 0.15:
        return rng.randint(3, 15)
    base = rng.gauss(36, 14) if condicion != "PEATON" else rng.gauss(45, 20)
    return max(16 if condicion in ("CONDUCTOR", "MOTOCICLISTA") else 1, min(95, int(base)))


def generar(n: int = 4000, semilla: int = 2026, desde: date = date(2020, 1, 1),
            hasta: date = date(2025, 12, 31), anclas: dict | None = None) -> DatosDemo:
    """Genera `n` siniestros sintéticos con sus personas y vehículos (filas listas para CSV)."""
    if n < 1:
        raise ValueError("n debe ser al menos 1")
    if hasta < desde:
        raise ValueError("'hasta' debe ser posterior a 'desde'")
    rng = random.Random(semilla)
    anclas = anclas or _cargar_anclas()
    # Peso INVENTADO por localidad (más anclas urbanas = más peso), con Sumapaz casi sin registros.
    pesos = {k: (0.05 if k == "SUMAPAZ" else rng.uniform(0.5, 1.5)) for k in LOCALIDADES_ARCHIVO}
    claves = list(LOCALIDADES_ARCHIVO)
    datos = DatosDemo()

    for i in range(n):
        codigo = PRIMER_CODIGO + i
        loc = rng.choices(claves, weights=[pesos[k] for k in claves])[0]
        gravedad = _elegir(rng, GRAVEDADES)
        clase = _elegir(rng, CLASES)
        hora = rng.choices(range(24), weights=HORAS)[0]
        minuto = rng.randrange(0, 60, 5)

        lat, lon = rng.choice(anclas[loc])
        lat, lon = lat + rng.uniform(-0.00225, 0.00225), lon + rng.uniform(-0.00225, 0.00225)
        caso = rng.random()
        if caso < 0.04:
            lat = lon = None                      # sin coordenada
        elif caso < 0.045:
            lat, lon = 4.582, -74.228             # fuera de Bogotá (Soacha)
        elif caso < 0.048:
            lat, lon = 0.0, 0.0                   # fuera de rango
        localidad = "" if rng.random() < 0.01 else LOCALIDADES_ARCHIVO[loc]

        datos.siniestros.append({
            "Codigo_Siniestro": codigo,
            "Formulario": f"DEMO{codigo}",
            "Fecha": _fecha(rng, desde, hasta).isoformat(),
            "Hora": "" if rng.random() < 0.02 else hora,
            "Minuto": minuto,
            "Localidad": localidad,
            "Direccion": _direccion(rng),
            "Clase": clase,
            "Gravedad": gravedad,
            "Latitud": "" if lat is None else f"{lat:.6f}",
            "Longitud": "" if lon is None else f"{lon:.6f}",
        })

        # ---- vehículos y personas, coherentes con la clase y la gravedad
        n_veh = 1 if clase in ("Atropello", "Caída de ocupante", "Volcamiento", "Autolesión", "Incendio") \
            else rng.choices([1, 2, 3], weights=[0.15, 0.75, 0.10])[0]
        personas = []
        for v in range(1, n_veh + 1):
            clase_v = _elegir(rng, VEHICULOS)
            datos.vehiculos.append({"Codigo_Siniestro": codigo, "Codigo_Vehiculo": v, "Clase": clase_v,
                                    "Servicio": "" if clase_v == "BICICLETA" else _elegir(rng, SERVICIOS)})
            condicion = {"MOTOCICLETA": "MOTOCICLISTA", "BICICLETA": "CICLISTA"}.get(clase_v, "CONDUCTOR")
            personas.append([v, 0, condicion])
            for p in range(1, rng.choices([1, 2, 3], weights=[0.7, 0.2, 0.1])[0]):
                personas.append([v, p, "PASAJERO"])
        if clase == "Atropello":
            personas.append(["", 1, "PEATON"])

        # Estados: el peor coincide con la gravedad del siniestro.
        estados = ["ILESO"] * len(personas)
        if gravedad != "Solo Daños":
            # el más expuesto (peatón, ciclista, motociclista) suele ser la víctima
            orden = sorted(range(len(personas)), key=lambda j: personas[j][2] not in ("PEATON", "CICLISTA", "MOTOCICLISTA"))
            victima = orden[0] if rng.random() < 0.8 else rng.randrange(len(personas))
            estados[victima] = "MUERTO" if gravedad == "Con Muertos" else "HERIDO"
            for j in range(len(personas)):
                if j != victima and rng.random() < 0.25:
                    estados[j] = "HERIDO"
        for (vehiculo, consecutivo, condicion), estado in zip(personas, estados):
            datos.actores.append({
                "Codigo_Siniestro": codigo, "Consecutivo": consecutivo, "Codigo_Vehiculo": vehiculo,
                "Estado": estado, "Condicion": condicion,
                "Sexo": rng.choices(["MASCULINO", "FEMENINO", "SIN INFORMACION"], weights=[0.68, 0.30, 0.02])[0],
                "Edad": _edad(rng, condicion),
            })
    return datos


def escribir_csv(datos: DatosDemo, carpeta: Path) -> dict[str, Path]:
    """Escribe tres CSV (UTF-8, separados por comas) y devuelve sus rutas por tipo de carga."""
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    rutas = {}
    for tipo, encabezado, filas in (("siniestros", ENC_SINIESTROS, datos.siniestros),
                                    ("actores", ENC_ACTORES, datos.actores),
                                    ("vehiculos", ENC_VEHICULOS, datos.vehiculos)):
        ruta = carpeta / f"demo_{tipo}.csv"
        with open(ruta, "w", encoding="utf-8", newline="") as f:
            escritor = csv.DictWriter(f, fieldnames=encabezado)
            escritor.writeheader()
            escritor.writerows(filas)
        rutas[tipo] = ruta
    return rutas


def hay_demo(sesion) -> bool:
    from sqlalchemy import select

    from .. import models

    return sesion.scalar(
        select(models.SiniestroEvento.id).join(models.FuenteDatos, models.FuenteDatos.id == models.SiniestroEvento.fuente_id)
        .where(models.FuenteDatos.codigo == CODIGO_FUENTE).limit(1)) is not None


def borrar_demo(sesion) -> int:
    """Borra la fuente DEMO y todo lo que cuelga de ella. Devuelve cuántos siniestros borró.
    No toca ninguna otra fuente."""
    from sqlalchemy import delete, func, select

    from .. import models

    fuente = sesion.scalar(select(models.FuenteDatos).where(models.FuenteDatos.codigo == CODIGO_FUENTE))
    if fuente is None:
        return 0
    ids = select(models.SiniestroEvento.id).where(models.SiniestroEvento.fuente_id == fuente.id)
    total = sesion.scalar(select(func.count()).select_from(models.SiniestroEvento)
                          .where(models.SiniestroEvento.fuente_id == fuente.id)) or 0
    for hijo in (models.ActorVial, models.VehiculoEvento, models.CausaEvento):
        sesion.execute(delete(hijo).where(hijo.siniestro_id.in_(ids)))
    sesion.execute(delete(models.SiniestroEvento).where(models.SiniestroEvento.fuente_id == fuente.id))
    sesion.execute(delete(models.Importacion).where(models.Importacion.fuente_id == fuente.id))
    sesion.delete(fuente)
    sesion.commit()
    return int(total)


def cargar_demo(sesion, cfg, n: int = 4000, semilla: int = 2026, carpeta: Path | None = None,
                progreso=None, hoy: date | None = None) -> dict:
    """Genera los CSV y los importa con el importador oficial (previsualizar → confirmar), en el orden
    siniestros → actores → vehículos. Si ya había datos DEMO, los registros con el mismo código se actualizan
    (no se duplican). Devuelve un resumen por tipo."""
    import tempfile

    from .archivos import recibir_archivo
    from .importador_excel import ImportadorArchivos
    from .repositorio_sql import RepositorioSQL

    aviso = progreso or (lambda *_: None)
    with tempfile.TemporaryDirectory() as temporal:
        destino = Path(carpeta) if carpeta else Path(temporal)
        rutas = escribir_csv(generar(n=n, semilla=semilla), destino)
        importador = ImportadorArchivos(
            RepositorioSQL(sesion), cfg.carga_directorio, cfg.geo_directorio, bloque=cfg.importar_bloque,
            tolerancia_geo=cfg.geo_tolerancia_grados, coherencia_percentil=cfg.coherencia_percentil,
            coherencia_margen=cfg.coherencia_margen_grados, conservar_archivo=False, hoy=hoy)
        resumen = {}
        for tipo in ("siniestros", "actores", "vehiculos"):
            aviso(f"Importando {tipo} DEMO…")
            with open(rutas[tipo], "rb") as flujo:
                recibido = recibir_archivo(flujo, rutas[tipo].name, "text/csv", cfg.carga_directorio,
                                           max_bytes=cfg.carga_max_mb * 1024 * 1024,
                                           max_descomprimido=cfg.carga_max_descomprimido_mb * 1024 * 1024)
            pv = importador.previsualizar(recibido, tipo=tipo, mapeo_codigo=CODIGO_MAPEO)
            if not pv.puede_confirmar:
                raise RuntimeError(f"La previsualización DEMO de {tipo} no se puede confirmar: {pv.advertencias}")
            r = importador.confirmar(pv.importacion_id)
            if r.estado != "completada":
                raise RuntimeError(r.mensaje)
            resumen[tipo] = {"importacion_id": pv.importacion_id, "mensaje": r.mensaje}
            aviso("  " + r.mensaje)
    return resumen
