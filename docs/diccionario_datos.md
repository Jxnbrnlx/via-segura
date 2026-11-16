# Diccionario de datos y mapeo de campos

Elaborado inspeccionando los archivos adjuntos (noviembre de 2026) y los metadatos del servicio ArcGIS.
Las columnas conservan su **nombre original**; el mapeo a campos lógicos se guarda en `importaciones.mapeo`.

## Fuentes inspeccionadas

| Fuente | Cobertura observada | Siniestros | Vehículos | Personas |
|---|---|---|---|---|
| Anuario (archivo rotulado "2024") | 2015-01-01 a 2024-12-31 | 278.614 | 523.168 | 608.155 |
| Anuario 2025 | 2025-01-01 a 2025-12-31 | 11.573 | 19.974 | 28.029 |
| ArcGIS SIMUR (capa 2 y tablas 3-5) | 2001 a la fecha más reciente publicada (2026-11-10 al consultar el 16-11-2026); el periodo guardado se calcula al sincronizar | 907.596 | 2.813.776 | 3.281.989 |

## Campos lógicos

| Campo lógico (tabla.columna) | Anuario 2015-2024 | Anuario 2025 | ArcGIS |
|---|---|---|---|
| siniestros_evento.id_registro | Codigo_Accidente | Codigo_Siniestro | CODIGO_ACCIDENTE (capa 2) |
| .formulario (interno) | Formulario | Formulario | FORMULARIO |
| .fecha_evento / anio / mes / dia_semana | Fecha_Acc (MM/DD/AAAA), AA_Acc, MM_Acc, Dia_Semana_Acc | Fecha_Siniestro (M/D/AAAA), AA_Siniestro, MM_Siniestro, Dia_Semana_Siniestro | FECHA_OCURRENCIA_ACC (epoch ms = medianoche UTC de la fecha local); año/mes/día se calculan de la fecha |
| .hora / minuto | Hora_Acc, Min_Acc | Hora_Siniestro, Min_Siniestro | HORA_OCURRENCIA_ACC (texto) |
| .localidad | Localidad | Localidad | LOCALIDAD |
| .direccion / barrio / via_nombre | Direccion | Direccion | DIRECCION / BARRIO / MVINOMBRE |
| .clase_siniestro | Clase_Acc | Clase_Siniestro | CLASE_ACC |
| .gravedad | Gravedad_indicador_30d | Gravedad_indicador_30d | GRAVEDAD (criterio sin documentar) |
| .gravedad_tradicional | Gravedad_Indicador_Tradicional | no existe | no existe |
| .latitud / longitud | Latitud, Longitud (numérico) | Latitud, Longitud (**texto con coma decimal**) | LATITUD, LONGITUD |
| actores_viales.estado | Gravedad_Indicador_30d (HERIDO/ILESO/MUERTO) | igual | ESTADO (HERIDO/ILESO/MUERTO/vacío, verificado) |
| .condicion / condicion_especifica | Condicion / Condicion_Especifica | igual (+ victimaC, asociadoC) | CONDICION / CONDICION_A |
| .sexo / edad | Sexo / Edad | Sexo / Edad | GENERO / EDAD |
| .codigo_vehiculo / consecutivo_victima | Codigo_Vehiculo / Ccodigo_Victima | igual | CODIGO_VEHICULO (vacío en 238.318 filas: se guarda NULL) / CODIGO_VICTIMA |
| .muerte_posterior | no existe | no existe | MUERTE_POSTERIOR (S/N) |
| vehiculos_evento.clase / servicio / modalidad | Clase / Servicio / Modalidad | igual | CLASE / SERVICIO / MODALIDAD |
| causas_evento | no existe | no existe | VM_ACC_CAUSA (CODIGO_CAUSA, NOMBRE, TIPO_CAUSA; filas repetidas se guardan una vez) |
| unión con la capa 2 | Codigo_Accidente | Codigo_Siniestro | FORMULARIO (todas las relaciones del servicio) |

Los campos `numero_heridos` y `numero_fallecidos` **no existen en ninguna fuente**; se derivan contando
personas por `estado` en `actores_viales` y se rotulan "derivado de actor vial".

## Campos que NO se importan (datos personales)

VM_ACC_VEHICULO.PLACA, VM_ACC_ACTOR_VIAL.FECHA_NACIMIENTO, VM_ACC_ACTOR_VIAL.CODIGO_ACCIDENTADO y cualquier
documento o nombre. La consulta a ArcGIS usa `outFields` explícito para no solicitarlos.

## Normalizaciones

- Localidad: clave canónica en MAYÚSCULAS, sin tildes pero conservando la Ñ, sin espacios sobrantes
  (`Bosa`, `BOSA`; `USAQUÉN` del anuario y `USAQUEN` de ArcGIS; `La Candelaria` → `CANDELARIA`).
  El nombre con tildes para mostrar está en `calidad.LOCALIDADES`. Un texto que no sea una de las 20
  localidades queda NULL y el original se guarda en `atributos.localidad_original`.
- Coordenadas con coma decimal (anuario 2025) se convierten a número; nunca se imputan.
- Edad fuera de 0-110 → NULL. Rango de edad con los cursos de vida del archivo oficial de población:
  0-5, 6-11, 12-17, 18-28, 29-59, 60+. Sexo: MASCULINO / FEMENINO / SIN INFORMACION.
- Categorías abiertas (condición, clase de vehículo, servicio): MAYÚSCULAS sin tildes; la Ñ dañada
  (`ACOMPA¿E`) solo se repara a `ACOMPAÑE`, sin reinterpretar.
- Clase de siniestro: Choque, Atropello, Caída de ocupante, Volcamiento, Incendio, Autolesión, Otro.
  Una clase desconocida se conserva tal cual y se reporta.
- Gravedad: se mapea a `Con Muertos`, `Con Heridos`, `Solo Daños`; valores no reconocidos se rechazan y se reportan.

## Categorías observadas (anuarios)

Clase: Choque, Atropello, Caida de ocupante, Volcamiento, Otro, Incendio, Autolesión.
Condición de la persona: CONDUCTOR, MOTOCICLISTA, PEATÓN, PASAJERO, CICLISTA, SIN INFORMACION.

## Categorías observadas (ArcGIS, 16-11-2026)

Ver `docs/arcgis_servicio.md`. Condición: además de las anteriores, `ACOMPA¿E`.

## Atributos adicionales de los anuarios (`siniestros_evento.atributos`)

Las columnas `Elemento_Choque` y `Tipo_Objeto_Fijo` se guardan como texto, con su nombre en minúsculas. Las
banderas `Con_*` solo se guardan cuando valen "SI", como `true`; por ejemplo, `{"con_moto": true}`.
Si la localidad no se reconoce, se guarda vacía y el texto original queda en `localidad_original`.

## Denominadores (`denominadores_oficiales`)

| Campo | Origen (población OSB) |
|---|---|
| localidad | CODIGO_LOCALIDAD 1-20 → clave canónica; el código 0 → `BOGOTA` (total de la ciudad). Se verifica contra NOMBRE_LOCALIDAD |
| anio | ANO |
| poblacion | suma de POBLACION de todos los sexos y edades |

## Polígonos de localidades

El archivo normalizado está en `backend/app/data/geo/localidades.geojson`. Cada polígono tiene las propiedades
`localidad` (clave canónica), `nombre` (con tildes) y `codigo` (1-20).
