# Informe de calidad de datos (anuarios)

| Verificación | Resultado |
|---|---|
| IDs y formularios duplicados dentro de cada archivo | 0 |
| Fechas inválidas | 0 |
| Vehículos o personas sin siniestro (huérfanos) | 0 |
| Siniestros del archivo 2015-2024 sin filas de actor vial | 151 |
| Coordenadas vacías | 15.065 (5,4 %), todas de 2015 a 2020; 0 desde 2021 |
| Coordenadas atípicas (al sur del área urbana) | 12; 4 son incoherentes con su localidad (Fontibón, Suba, Tunjuelito, Santa Fe) |
| Localidad vacía | 1 registro (2025) |
| Edad > 110 años | 355 (máximo 2021) |
| Edad vacía | 13.337 (2015-2024) y 1.510 (2025) |
| Siniestros presentes en ambos archivos | 3, con año 2024 en uno y 2025 en el otro (mismo día y mes); no se resuelve automáticamente |

## Comparabilidad temporal

| Año | Solo daños | Con heridos | Con muertos | Total |
|---|---|---|---|---|
| 2022 | 12.566 | 12.371 | 516 | 25.453 |
| 2023 | 1.115 | 12.473 | 526 | 14.114 |
| 2024 | 1.037 | 12.361 | 551 | 13.949 |
| 2025 | no aparece | 11.022 | 551 | 11.573 |

El total de siniestros no es comparable entre 2022 y 2023 por la caída de "Solo daños"; la serie
"con heridos o muertos" sí lo es. La causa del cambio no está explicada en el diccionario oficial.

## Siniestros no son víctimas (2025)

11.573 siniestros (551 con muertos) frente a 28.029 personas registradas: 19.605 heridas, 7.841 ilesas y
562 fallecidas. Las cifras nunca se suman entre sí.

## Servicio ArcGIS (consultado el 16-11-2026)

Detalle completo en `docs/arcgis_servicio.md`. Resumen: 907.596 siniestros (2001 a 2026-11-10), sin
coordenadas vacías ni fuera de Bogotá, 1 localidad vacía, sin duplicados de CODIGO_ACCIDENTE ni de
FORMULARIO según el conteo de distintos; 238.318 personas sin CODIGO_VEHICULO; causas con filas
repetidas. Para 2024 y 2025 tiene 65 y 26 siniestros con heridos o muertos más que los anuarios.

## Archivos complementarios recibidos (16-11-2026)

| Archivo | Contenido real | Uso |
|---|---|---|
| `Base_Anuario_de_Siniestralidad_2024.csv` | Solo la hoja **Siniestros** del anuario 2015-2024 (278.614 filas, 40 columnas). Fecha `MM/DD/AAAA`, coherente con AA/MM/DD en el 100 %. | Importador (Parte 3). Faltan las hojas Vehiculos y Actor_vial en CSV. |
| `Base_Anuario_de_Siniestralidad_Vial_2025.csv` | Solo la hoja **Siniestros** del anuario 2025 (11.573 filas, 25 columnas). Coordenadas con coma decimal; fecha `M/D/AAAA`. | Importador (Parte 3). Faltan Vehículos y Actor vial. |
| `osb_demografia-poblacion-localidad.csv` | Población por año (2005-2035), localidad (código 0 = Bogotá; 1-20), sexo y edad simple (0-100). Separador `;`, UTF-8 con BOM. La suma de las 20 localidades es igual al total de Bogotá en los 31 años. | Denominadores (Parte 3). Los años posteriores al actual son **proyecciones**: se rotularán como tales. |
| `localidades.geojson` | **No son localidades**: es la capa `MANZ` (44.529 manzanas catastrales, atributos MANCODIGO, SECCODIGO, SHAPE_AREA, SHAPE_LEN; 129 MB). No trae código ni nombre de localidad. | No sirve para el mapa por localidad. Mientras llega el archivo correcto se usan círculos en el centroide de los puntos reales (decisión 8). |

El archivo correcto es el conjunto "Localidad. Bogotá D.C." de Datos Abiertos Bogotá (Catastro / IDECA),
que trae un polígono por localidad con su código y nombre.

## Resultado del importador con los CSV recibidos (Parte 3, 16-11-2026)

| Archivo | Filas | Válidas | Rechazadas | Observaciones |
|---|---|---|---|---|
| Anuario 2025, hoja Siniestros | 11.573 | 11.573 | 0 | 1 localidad vacía; 4 coordenadas "sospechosa" |
| Anuario 2015-2024, hoja Siniestros | 278.614 | 278.614 | 0 | 15.065 sin coordenada; 148 sin gravedad a 30 días; 185 coordenadas "sospechosa"; 3 siniestros también presentes en el anuario 2025 con fecha distinta (se informan, no se fusionan) |
| Población OSB | 131.502 | 131.502 | 0 | 651 denominadores (20 localidades + total Bogotá × 31 años); la suma de localidades es igual al total en todos los años; 2027-2035 son proyecciones |
| localidades.geojson (manzanas) | — | — | rechazado | El primer polígono solo tiene MANCODIGO, SECCODIGO, SHAPE_AREA y SHAPE_LEN |

En los dos anuarios la fecha de texto (MM/DD/AAAA) coincide con las columnas de año, mes y día en el 100 % de
las filas. El importador usa esas columnas para resolver fechas ambiguas como 02/09: no adivina.
