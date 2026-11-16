# Guía para importar los archivos oficiales y actualizar los datos

Todos los comandos se ejecutan en PowerShell, desde la carpeta `via-segura`, con el entorno virtual activo
(`.\.venv\Scripts\Activate.ps1`) y la base creada (`alembic upgrade head`).
La carga se puede hacer desde la página (**Administración → Importar archivo**) o por consola con
`scripts/importar_archivo.py`. Ambos usan el mismo servicio, con las mismas validaciones. En la página, la
revisión permite elegir otra columna para cualquier campo y volver a revisar antes de confirmar.

## 0. Datos DEMO (sintéticos)

Para probar la aplicación sin archivos oficiales:

```powershell
python scripts\generar_demo.py                  # carga 4.000 siniestros inventados
python scripts\generar_demo.py --solo-csv demo  # solo escribe los CSV (para subirlos desde la página)
python scripts\generar_demo.py --borrar         # borra la DEMO sin tocar las fuentes oficiales
```

Los datos DEMO pasan por el mismo importador (mapeo `demo_sintetica`). Quedan en una fuente aparte,
«DEMO — Datos sintéticos», que nunca se suma con las oficiales y muestra un aviso en todas las pantallas.

## 1. Cómo funciona una carga

1. **Previsualizar** (sin `--confirmar`). El archivo se valida: nombre, extensión, tipo, tamaño y contenido.
   Luego se elige la hoja y se muestran las columnas con su tipo y las primeras filas. Las columnas con datos
   personales (placa, fecha de nacimiento, documento…) se omiten. También se muestra el mapeo aplicado y la
   validación de las primeras 1.000 filas. Queda registrada como importación **previsualizada**; no escribe datos.
2. **Confirmar** (`--confirmar` o `--confirmar-id N`). Se comprueba que el archivo no cambió (huella SHA-256).
   Después se procesa por bloques y la importación queda **completada** o **fallida**, con el conteo de filas
   revisadas, válidas y rechazadas y los motivos de rechazo.
3. **Cancelar** (`--cancelar-id N`): descarta una previsualización y borra el archivo temporal.

Una fila nunca se "arregla" inventando datos. Si falta la coordenada, queda sin coordenada. Si la fecha no
coincide con las columnas de año, mes y día, la fila se rechaza y se informa. Si la localidad no es una de las
20, se guarda vacía y se conserva el texto original.

## 2. Anuarios de siniestralidad (Secretaría Distrital de Movilidad)

Los anuarios tienen tres hojas que se importan **en este orden**: siniestros, personas y vehículos. Las personas
y los vehículos se enlazan con los siniestros que ya están en la base.

Se puede subir el `.xlsx` original: el script elige la hoja según el mapeo. El de 2015-2024 pesa unos 126 MB y
se lee en modo de solo lectura, sin cargarlo entero en memoria; tarda varios minutos. También se pueden subir
las hojas exportadas a CSV.

```powershell
# Ver las hojas de un libro
python scripts/importar_archivo.py --hojas "C:\datos\Base_Anuario_de_Siniestralidad_2024.xlsx"

# Anuario 2025
python scripts/importar_archivo.py "C:\datos\Base_Anuario_2025.xlsx" --tipo siniestros --mapeo anuario_sdm_2025 --confirmar --fecha-descarga AAAA-MM-DD
python scripts/importar_archivo.py "C:\datos\Base_Anuario_2025.xlsx" --tipo actores    --mapeo anuario_sdm_2025
python scripts/importar_archivo.py "C:\datos\Base_Anuario_2025.xlsx" --tipo vehiculos  --mapeo anuario_sdm_2025

# Anuario 2015-2024 (mismo procedimiento con el otro mapeo)
python scripts/importar_archivo.py "C:\datos\Base_Anuario_de_Siniestralidad_2024.xlsx" --tipo siniestros --mapeo anuario_sdm_2015_2024 --confirmar
```

En las hojas de personas y vehículos, primero conviene previsualizar sin `--confirmar`. Los nombres de columna
de esas hojas vienen del diccionario de la Parte 1 y todavía no se han comprobado con el archivo. Si la
previsualización dice "Faltan columnas obligatorias", indique la columna correcta con `--columna`:

```powershell
python scripts/importar_archivo.py anuario.xlsx --tipo actores --mapeo anuario_sdm_2015_2024 --columna id_registro=Codigo_Accidente --columna consecutivo_victima=Codigo_Victima
```

Para desactivar un campo opcional se usa `--columna campo=` (sin valor). Los mapeos están en
`backend/app/data/mapeos/*.json`: cada campo lógico tiene una lista de columnas candidatas.

**Qué se guarda de cada hoja**

| Hoja | Campos | Observaciones |
|---|---|---|
| Siniestros | id, formulario, fecha, hora, localidad, dirección, clase, gravedad (indicador 30 días), gravedad tradicional (solo 2015-2024), coordenadas | Elemento_Choque, Tipo_Objeto_Fijo y las banderas `Con_*` con valor "SI" se guardan en `atributos` |
| Actor vial | código de vehículo (puede faltar), consecutivo, estado (HERIDO/ILESO/MUERTO), condición, sexo, edad (0-110; si no, vacía), rango de edad | Fecha de nacimiento: no se lee |
| Vehículos | código de vehículo, clase, servicio, modalidad | Placa: no se lee |

**Siniestros repetidos entre anuarios.** Cada anuario es una fuente distinta y nada se fusiona. Si el mismo
código aparece en los dos, se informa en el resumen (`coincidencias_otras_fuentes`), incluida la fecha distinta.
Con los CSV recibidos aparecen exactamente los 3 casos documentados.

## 3. Población por localidad (denominador de tasas)

```powershell
python scripts/importar_archivo.py "C:\datos\osb_demografia-poblacion-localidad.csv" --tipo poblacion --mapeo poblacion_osb_localidad --confirmar --url "<enlace de la ficha>" --fecha-descarga AAAA-MM-DD
```

Se suman sexos y edades por año y localidad. El código 0 se guarda como `BOGOTA`, que es el total de la ciudad.
El script comprueba que la suma de las 20 localidades sea igual a ese total. Los años posteriores al actual
quedan marcados como proyecciones en el resumen. Sin esta carga, la aplicación muestra solo conteos y no tasas.

## 4. Polígonos de localidades (mapa temático)

Descargue el conjunto **"Localidad. Bogotá D.C."** de Datos Abiertos Bogotá en GeoJSON, con coordenadas en
EPSG:4326 / WGS84.

```powershell
python scripts/importar_archivo.py "C:\datos\localidad.geojson" --tipo localidades --confirmar
```

El sistema detecta solo el atributo que identifica la localidad, sea nombre o código. Une los polígonos de una
misma localidad, simplifica el detalle por debajo de unos 5 m y publica el resultado en
`backend/app/data/geo/localidades.geojson`. Rechaza los archivos que no son de localidades: por ejemplo, el de
manzanas (`MANZ`) que se recibió el 16-11-2026, y lo hace en segundos, sin leerlo completo. También rechaza
coordenadas en metros (proyectadas). Mientras no haya polígonos, el mapa usa círculos en el centroide de los
puntos reales.

## 5. Fuente principal: ArcGIS SIMUR

```powershell
python scripts/inspect_service.py --json docs/inspeccion_arcgis.json     # revisar el servicio
python scripts/sync_arcgis.py --modo completa --desde-anio 2015          # primera carga (larga)
python scripts/sync_arcgis.py                                            # actualizaciones
```

La actualización relee los últimos `ARCGIS_VENTANA_DIAS` (90) días porque los registros cambian después de
publicados, por ejemplo con muertes posteriores. No duplica. Si el servicio falla, se conservan los datos.

**Programar la actualización diaria en Windows** (Programador de tareas):

```powershell
schtasks /Create /TN "VIA SEGURA - sincronizar ArcGIS" /SC DAILY /ST 03:15 /TR "cmd /c cd /d C:\ruta\via-segura && .venv\Scripts\python.exe scripts\sync_arcgis.py >> sync.log 2>&1"
```

## 6. Dónde quedan los resultados

- La tabla `importaciones` guarda cada carga: archivo (nombre saneado), hoja, estado, filas
  revisadas/válidas/rechazadas, fechas mínima y máxima, mapeo usado, hasta 200 errores legibles y un resumen
  de calidad.
- La ficha de cada fuente (`fuentes_datos`) guarda el periodo real (mínimo y máximo de lo importado) y la
  URL y las fechas que indique el administrador. No se inventan.
- Los archivos subidos se guardan temporalmente en `backend/app/data/cargas/<código aleatorio>/` y se
  borran al completar, salvo que se configure `CONSERVAR_ARCHIVO_IMPORTADO=true`.
