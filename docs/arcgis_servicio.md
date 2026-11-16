# Servicio ArcGIS SIMUR: lo verificado y cómo se sincroniza

Servicio: `https://sig.simur.gov.co/arcgis/rest/services/Accidentalidad/AccidentalidadAnalisis/FeatureServer`
(Secretaría Distrital de Movilidad de Bogotá).

Todas las cifras de este documento se obtuvieron consultando el servicio el **16-11-2026**. El servicio
se actualiza continuamente: vuelve a ejecutar `python scripts/inspect_service.py` para cifras al día.
Nada de lo que sigue se usa como dato en la aplicación; la aplicación siempre calcula desde lo importado.

## Estructura (metadatos)

| Id | Nombre | Tipo | Registros (16-11-2026) | Uso en VÍA SEGURA |
|---|---|---|---|---|
| 0 | MUERTO | capa de puntos (una fila por persona fallecida) | 16.074 | No se importa (contiene CODIGO_ACCIDENTADO) |
| 1 | LESIONADO | capa de puntos (una fila por persona lesionada) | 486.261 | No se importa (contiene CODIGO_ACCIDENTADO) |
| 2 | ACCIDENTE | capa de puntos (un siniestro por fila) | 907.596 | **Siniestros** (`siniestros_evento`) |
| 3 | VM_ACC_ACTOR_VIAL | tabla | 3.281.989 | Personas (`actores_viales`) |
| 4 | VM_ACC_CAUSA | tabla | 1.915.832 | Causas (`causas_evento`) |
| 5 | VM_ACC_VEHICULO | tabla | 2.813.776 | Vehículos (`vehiculos_evento`) |
| 6 | VM_ACC_VIA | tabla | 970.044 | No se importa todavía |

- MaxRecordCount = 2000; formatos JSON, geoJSON y PBF; paginación, orderBy, estadísticas y distinct soportados.
- Sistema de referencia WKID 4686 (MAGNA-SIRGAS). En 4 registros revisados la geometría coincide con
  LATITUD/LONGITUD hasta el octavo decimal; se usan los campos LATITUD/LONGITUD.
- **Todas las relaciones usan `FORMULARIO`** (capa 2 de origen; capas 0 y 1 y tablas 3-6 de destino).
- `dateFieldsTimeReference` = UTC.

## Hallazgos que cambian el procesamiento

| Hallazgo | Consecuencia en el código |
|---|---|
| `FECHA_OCURRENCIA_ACC` llega como medianoche UTC de la fecha local (1794268800000 = 2026-11-10, día MARTES en la fuente). Restar 5 horas correría el día. | `calidad.fecha_desde_epoch_ms`: múltiplo exacto de un día → fecha UTC; otro valor → hora de Bogotá. |
| `HORA_OCURRENCIA_ACC` es texto `HH:MM:SS`; `MES_` y `DIA_OCURRENCIA_ACC` son texto (NOVIEMBRE, MARTES); `ANO_` es decimal. | Año, mes y día de semana se calculan de la fecha; los de la fuente solo se contrastan (discrepancias en el resumen). |
| `CODIGO_ACCIDENTE` y `FORMULARIO`: el conteo de valores distintos es igual al total (907.596). | `id_registro` = CODIGO_ACCIDENTE; unión con tablas por FORMULARIO. Duplicados, si aparecen, se reportan. |
| `GRAVEDAD`: CON HERIDOS, CON MUERTOS, SOLO DANOS y vacío. | Se mapea a `Con Heridos`, `Con Muertos`, `Solo Daños`; vacío → NULL. Otro valor → registro rechazado y reportado. |
| `CLASE_ACC`: CHOQUE, ATROPELLO, CAIDA DE OCUPANTE, VOLCAMIENTO, OTRO, INCENDIO, AUTOLESION y vacío. | Se mapea a las mismas etiquetas que el anuario. |
| `LOCALIDAD` sin tildes (USAQUEN), pero ANTONIO NARIÑO conserva la Ñ. 1 registro vacío. | Clave canónica: MAYÚSCULAS sin tildes, conservando Ñ; "La Candelaria" → CANDELARIA. |
| 0 registros sin LATITUD/LONGITUD y 0 fuera de la caja amplia de Bogotá. El anuario 2015-2020 sí tiene 15.065 sin coordenada. | Parece que la capa solo publica siniestros georreferenciados (observación; no está documentado). Por eso ArcGIS y anuarios no deben compararse como totales. |
| Tabla 3: `CODIGO_VEHICULO` vacío en 238.318 filas; `CODIGO_VICTIMA` nunca vacío. | `actores_viales.codigo_vehiculo` admite NULL (se corrigió la migración 0001, que nunca se había ejecutado). |
| Tabla 3: `CODIGO` = `<CODIGO_ACCIDENTE>-<CODIGO_VEHICULO>`. Tabla 4 trae `CODIGO_ACCIDENTE`. | Se usa como comprobación cruzada de la unión por FORMULARIO (`relacion.*_codigo_no_coincide`). |
| Tabla 3: ESTADO = HERIDO / ILESO / MUERTO / vacío; GENERO = MASCULINO / FEMENINO / SIN INFORMACION / vacío; MUERTE_POSTERIOR = S / N / vacío. | Coinciden con el CHECK de la base. |
| Tabla 3: CONDICION incluye `ACOMPA¿E` (Ñ dañada en la fuente). | Solo se repara el carácter: se guarda `ACOMPAÑE`. No se reinterpreta el significado. |
| Tabla 4 trae filas idénticas repetidas (mismo CODIGO). | Se guarda una causa por (vehículo, código de causa); se cuentan los duplicados. |
| `returnDistinctValues` no deduplicó al pedir LOCALIDAD (devolvió ~200 KB). | Los valores distintos se obtienen con estadísticas agrupadas (`conteo_por_valor`). |

## Comparación con los anuarios (observaciones, no se corrigen)

| Año | ArcGIS: con heridos o muertos | Anuario: con heridos o muertos | Diferencia |
|---|---|---|---|
| 2024 | 12.977 | 12.912 (12.361 + 551) | +65 en ArcGIS |
| 2025 | 11.599 | 11.573 | +26 en ArcGIS |

- El siniestro 11335436 del anuario 2025 existe en ArcGIS con el mismo FORMULARIO, la misma fecha
  (2025-09-02) y las mismas coordenadas: los identificadores son comparables entre fuentes.
- El servicio cubre desde 2001 (443.828 registros antes de 2015) hasta la fecha más reciente publicada
  (2026-11-10 al consultar). Los anuarios cubren 2015-2025.
- Por la decisión 1, el tablero filtra por UNA fuente y nunca suma fuentes.

## Sincronización

```
python scripts/inspect_service.py --json docs/inspeccion_arcgis.json   # revisar antes de importar
python scripts/sync_arcgis.py --modo completa --desde-anio 2025 --max-paginas 2   # prueba corta
python scripts/sync_arcgis.py --modo completa --desde-anio 2015                    # carga real
python scripts/sync_arcgis.py                                                      # actualización
```

- **Completa:** recorre la capa 2 en páginas de 2000 ordenadas por OBJECTID; por cada página consulta las
  tablas 3, 5 y 4 con `FORMULARIO IN (...)` (bloques de `ARCGIS_LOTE_FORMULARIOS`, por POST).
  Una carga de todo el servicio son ~455 páginas de siniestros más las consultas relacionadas: puede tardar
  bastante. `--desde-anio` la acota.
- **Incremental:** relee desde (fecha máxima guardada − `ARCGIS_VENTANA_DIAS`), porque muertes posteriores
  y correcciones cambian registros ya publicados.
- **Upsert** por (fuente_id, id_registro); personas, vehículos y causas se reemplazan completos.
- Confirmación por página: un fallo a mitad conserva las páginas completas ya guardadas (son datos reales
  del servicio) y nunca deja una página a medias.
- Si el servicio no responde: importación `fallida`, mensaje legible y se conservan los datos anteriores.
- Registros guardados que ya no aparecen en el servicio: se informan en el resumen, **no se borran**.
- Nunca se solicitan `PLACA`, `FECHA_NACIMIENTO` ni `CODIGO_ACCIDENTADO` (el cliente rechaza `*` y esos campos).

## Coherencia localidad-coordenada (heurística)

Mientras no haya polígonos oficiales de localidades, al final de cada sincronización se marca como
`sospechosa` la coordenada que cae fuera de la caja de su localidad (percentiles 0,1 % y 99,9 % de los
puntos de esa localidad, ampliada 0,03° ≈ 3,3 km). El punto no se mueve ni se borra; solo no se muestra
en el mapa y se cuenta. Probado sobre el anuario 2015-2024 marca 185 registros en total, entre ellos el caso
documentado de Fontibón en lat 4,0858 y otros cuyo punto cae en otra zona de la ciudad (p. ej. "Chapinero" en
lat 4,55); también puede marcar algún punto rural legítimo de una localidad grande. Parámetros:
`COHERENCIA_PERCENTIL` y `COHERENCIA_MARGEN_GRADOS`. Con polígonos oficiales se reemplazará por una
prueba punto-en-polígono.

## Inspección completa (`inspect_service.py`, 16-11-2026, ejecutada por el usuario)

- **Cobertura:** del 2001-01-15 al 2026-11-10. No hay fechas futuras.
- **Siniestros por año:** 2001-2006 son casi vacíos (2001: 2; 2002: 202; 2003: 282; 2005: 432; 2006: 368)
  y **2004 no tiene registros**. La serie útil empieza en 2007 (59.541). Después: 2015: 55.563;
  2019: 65.027; 2020: 44.051; 2021: 28.855; 2022: 25.453; 2023: 14.116; 2024: 14.021; 2025: 12.401;
  2026 (parcial): 9.467. La caída desde 2021-2023 coincide con la casi desaparición de "Solo daños" en los
  anuarios (observación; la causa no está documentada).
- **GRAVEDAD:** SOLO DANOS 560.092; CON HERIDOS 331.852; CON MUERTOS 15.646; vacía 6.
- **CLASE_ACC:** CHOQUE 752.643; ATROPELLO 106.726; CAIDA DE OCUPANTE 20.721; VOLCAMIENTO 11.940; OTRO 10.782;
  AUTOLESION 4.415; INCENDIO 89; vacía 280.
- **LOCALIDAD:** las 20 localidades (SUMAPAZ: 8) y 1 vacía. **MUNICIPIO:** BOGOTA DC en todos.
- **Nulos:** CIV 1.831; PK_CALZADA 2.312; BARRIO 86; MVINOMBRE 4.050; ningún nulo en fecha, hora, código,
  formulario ni coordenadas.
- **Duplicados** (agrupación con HAVING): 0 en CODIGO_ACCIDENTE y 0 en FORMULARIO.
- **Muestra de 6.000 registros:** geometría y LATITUD/LONGITUD difieren como máximo 5×10⁻⁹ grados; todas
  las horas tienen formato HH:MM:SS; todas las fechas son medianoche UTC; el día de la semana de la fuente
  coincide con el calculado.
- **Tabla 3 (personas):** ESTADO: ILESO 2.453.895; HERIDO 793.259; MUERTO 24.351; vacío 10.484.
  MUERTE_POSTERIOR = S en 8.313. EDAD vacía en 325.164 y fuera de 0-110 en 4.978 (se guardan vacías).
  GENERO vacío en 60.812. CONDICION incluye ACOMPA¿E (2 filas).
- **Tabla 5 (vehículos):** 1.231 sin CODIGO_VEHICULO; no se pueden enlazar y se rechazan contados.
- **Tabla 4 (causas):** TIPO = CG, PE, CE, VI, VH, PA o vacío. El significado de los códigos no está
  documentado en el servicio, por eso todavía no se usa.
- **Unión por FORMULARIO:** en 50 siniestros recientes, los 50 tienen personas, y las 114 filas tienen el
  prefijo de CODIGO igual a CODIGO_ACCIDENTE.
- **Prueba de sincronización** (`--modo completa --desde-anio 2025 --max-paginas 2`): 4.000 siniestros
  guardados, 0 rechazados.
