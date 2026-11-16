"""Fichas de las fuentes oficiales. NO contiene cifras: los periodos se calculan al importar.

Las filas se crean en la base de datos con `asegurar_fuente` / `sembrar_fuentes`
(app/services/repositorio_sql.py), que dejan el periodo vacío hasta la primera importación real.
"""
FUENTES_INICIALES = [
    {
        "codigo": "arcgis_simur_accidentalidad",
        "entidad": "Secretaría Distrital de Movilidad de Bogotá (SIMUR)",
        "nombre": "Accidentalidad - AccidentalidadAnalisis (FeatureServer)",
        "url": "https://sig.simur.gov.co/arcgis/rest/services/Accidentalidad/AccidentalidadAnalisis/FeatureServer",
        "formato": "ArcGIS REST (JSON/GeoJSON)",
        "prioridad": 1,
        "notas": "Capas 0 MUERTO, 1 LESIONADO, 2 ACCIDENTE; tablas 3 actor vial, 4 causa, 5 vehículo, 6 vía. "
                 "Periodo y fecha más reciente se determinan en cada sincronización.",
    },
    {
        "codigo": "anuario_sdm_2025",
        "entidad": "Secretaría Distrital de Movilidad de Bogotá",
        "nombre": "Base Anuario de Siniestralidad Vial 2025",
        "url": None,
        "formato": "xlsx",
        "prioridad": 2,
        "notas": "Archivo cargado por el administrador. Solo incluye siniestros con heridos o muertos.",
    },
    {
        "codigo": "anuario_sdm_2015_2024",
        "entidad": "Secretaría Distrital de Movilidad de Bogotá",
        "nombre": "Base Anuario de Siniestralidad (archivo rotulado 2024; cubre 2015-2024)",
        "url": None,
        "formato": "xlsx",
        "prioridad": 3,
        "notas": "Desde 2023 casi no registra 'Solo daños': la serie total no es comparable con años anteriores.",
    },
    {
        "codigo": "poblacion_osb_localidad",
        "entidad": "Observatorio de Salud de Bogotá (SaluData), Secretaría Distrital de Salud",
        "nombre": "Población por localidad, sexo y edad (osb_demografia-poblacion-localidad)",
        "url": None,
        "formato": "csv",
        "prioridad": 10,
        "notas": "Denominador para tasas por habitante (suma de sexos y edades). Incluye años futuros, que son "
                 "proyecciones. Confirme la metodología y el enlace en la ficha del conjunto de datos.",
    },
    {
        "codigo": "localidades_bogota",
        "entidad": "Datos Abiertos Bogotá (IDECA)",
        "nombre": "Localidad. Bogotá D.C. (polígonos)",
        "url": "https://datosabiertos.bogota.gov.co/dataset/localidad-bogota-d-c",
        "formato": "geojson",
        "prioridad": 10,
        "notas": "Solo para dibujar el mapa por localidad; no es un dato estadístico.",
    },
]

# Fuentes que NO se siembran al iniciar: solo se crean cuando se cargan (p. ej. con scripts/generar_demo.py).
FUENTES_ADICIONALES = [
    {
        "codigo": "demo_sintetica",
        "entidad": "VÍA SEGURA (generador de demostración)",
        "nombre": "DEMO — Datos sintéticos (no son cifras oficiales)",
        "url": None,
        "formato": "csv generado",
        "prioridad": 99,
        "notas": "Registros inventados para probar la aplicación sin datos oficiales. Las ubicaciones se dispersan "
                 "alrededor de celdas de unos 500 m; ningún registro corresponde a un siniestro real. "
                 "No use estas cifras para conclusiones. Se borran con: python scripts/generar_demo.py --borrar",
    },
]


def ficha_fuente(codigo: str) -> dict | None:
    return next((f for f in FUENTES_INICIALES + FUENTES_ADICIONALES if f["codigo"] == codigo), None)

