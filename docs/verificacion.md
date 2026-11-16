# Lista de verificación de aceptación

Cada requisito del proyecto, dónde está implementado y cómo se comprueba: con una **prueba automática**
(`pytest`) o con un **paso manual** del recorrido de la sección final. Las pruebas están en `backend/tests/`.

Leyenda: ✅ verificado por prueba automática · 👁 verificación manual en la página · ⚠ con limitación (ver README §10)

## A. Fuente principal ArcGIS REST (SIMUR)

| # | Requisito | Implementación | Verificación |
|---|---|---|---|
| A1 | Consultar directamente el servicio oficial | `services/arcgis_client.py`, `scripts/sync_arcgis.py`, botón en Administración | ✅ `test_arcgis_client.py::test_consulta_usa_post_con_outfields_explicito` · 👁 R6 |
| A2 | Respuestas JSON/GeoJSON | Cliente JSON con geometría; API pública en GeoJSON (`/accidents/geojson`, `/localities/geojson`) | ✅ `test_geometria_se_adjunta_cuando_se_pide` · `test_api_publica.py` |
| A3 | Paginación | Ordenada por OBJECTID, páginas ≤ MaxRecordCount (2000) | ✅ `test_paginacion_recorre_todo_en_orden_de_objectid`, `test_paginacion_exacta_termina_con_pagina_vacia`, `test_pagina_no_puede_superar_maxrecordcount`, `test_paginacion_recupera_todos_los_registros` |
| A4 | Tablas relacionadas (actor vial, vehículo, causa) | Enlazadas por FORMULARIO, en lotes | ✅ `test_carga_completa_guarda_siniestros_personas_vehiculos_y_causas` |
| A5 | Verificar campos, nulos, duplicados, coordenadas y fechas | `services/calidad.py`; inspección en `scripts/inspect_service.py`; informe en `docs/informe_calidad.md` | ✅ `test_esquema_cambiado_detiene_sin_importar`, `test_codigo_accidente_repetido_en_el_servicio_se_reporta`, `test_coordenadas_invalidas_se_marcan_sin_imputar`, `test_fecha_epoch_verificada_en_el_servicio_no_corre_el_dia`, `test_calidad.py` |
| A6 | No inventar registros, fechas, coordenadas ni cifras | Nada se imputa; los periodos salen del mín./máx. real; fichas sin cifras | ✅ `test_coordenada_faltante_no_se_imputa`, `test_periodo_de_la_fuente_es_el_minimo_y_maximo_real`, `test_localidad_desconocida_no_se_reasigna`, `test_aceptacion.py::test_coordenadas_no_se_imputan_y_concentracion_solo_conteos` |
| A7 | Fecha más reciente y cobertura | Ficha de la fuente (periodo, última carga) en `/sources` y en «Fuentes y metodología» | ✅ `test_periodo_de_la_fuente_es_el_minimo_y_maximo_real` · 👁 R3 |
| A8 | Actualización sin duplicados | Clave (fuente, código); sincronización incremental con ventana | ✅ `test_dos_sincronizaciones_seguidas_no_duplican`, `test_incremental_relee_la_ventana_desde_la_fecha_maxima_guardada`, `test_registros_que_desaparecen_del_servicio_se_informan_y_no_se_borran` |
| A9 | Servicio no disponible → mensaje y datos guardados | La carga queda «fallida» con un motivo legible; los datos anteriores se conservan | ✅ `test_servicio_caido_marca_fallida_y_conserva_lo_guardado`, `test_falla_a_mitad_conserva_las_paginas_confirmadas`, `test_caida_de_red_termina_en_servicio_no_disponible` · 👁 R6 |

## B. Funcionalidades

| # | Requisito | Dónde | Verificación |
|---|---|---|---|
| B1 | Mapa de siniestros | Mapa → Puntos (agrupados, ventana con detalle) | ✅ `test_aceptacion.py` (geojson) · 👁 R4 |
| B2 | Mapa de calor | Mapa → Calor | 👁 R4 |
| B3 | Estadísticas | Inicio y Analítica (7 gráficos con su tabla de datos) | ✅ `test_api_publica.py` · 👁 R5 |
| B4 | Filtros por localidad, año, gravedad y clase (más mes, fechas y actor vial) | Cajón «Filtros», buscador y botones rápidos | ✅ `test_aceptacion.py::test_ningun_endpoint_publico_expone_datos_privados_ni_califica_zonas` (6 combinaciones en todos los endpoints) · 👁 R2 |
| B5 | Concentración geográfica | Mapa → Concentración (cuadrícula de 250/500/1000 m calculada en el servidor) | ✅ `test_aceptacion.py::test_coordenadas_no_se_imputan_y_concentracion_solo_conteos`, `test_api_base.py::test_celda_de_250m_y_sus_limites_contienen_el_punto` |
| B6 | Fuentes y metodología, Ayuda | Secciones propias | 👁 R3, R7 |
| B7 | Administración: login, carga, previsualización, mapeo, confirmación, historial, sincronización | Administración | ✅ `test_api_admin.py` · 👁 R8 |
| B8 | Exportación CSV (+ PDF opcional) | Explorador y Fuentes; informe imprimible | ✅ `test_exportacion.py`, `test_api_publica.py::test_exportar_csv_*` · 👁 R5 |
| B9 | Datos DEMO | `scripts/generar_demo.py` | ✅ `test_demo.py` · 👁 R1 |

## C. Las 9 decisiones del proyecto

| # | Decisión | Verificación |
|---|---|---|
| C1 | ArcGIS por defecto; una fuente por consulta; nunca se suman | ✅ `test_aceptacion.py::test_una_sola_fuente_por_consulta_nunca_se_suman`, `test_demo.py::test_carga_y_borrado_en_sqlite_sin_tocar_otras_fuentes` |
| C2 | Sin duplicados por (fuente, id); conflictos entre fuentes informados, no fusionados | ✅ `test_coincidencias_con_otra_fuente_se_informan_sin_fusionar`, `test_mismo_siniestro_en_dos_anuarios_se_reporta_sin_fusionar`, `test_confirmar_dos_veces_no_se_permite_y_reimportar_no_duplica` |
| C3 | KPI por defecto «con heridos o muertos»; «solo daños» aparte con advertencia | ✅ `test_aceptacion.py::test_kpi_por_defecto_y_solo_danos_aparte` |
| C4 | Siniestros ≠ víctimas; personas «derivado de actor vial», nunca sumadas | ✅ `test_kpi_por_defecto_y_solo_danos_aparte` (marca `derivado`), `test_exportacion.py` (columnas `*_derivado_actor_vial`) |
| C5 | Coordenadas nunca imputadas; motivos sin_coordenada / fuera_de_rango / fuera_de_bogota / sospechosa | ✅ `test_calidad.py` (4 motivos), `test_coordenada_incoherente_con_su_localidad_queda_sospechosa` |
| C6 | Privacidad: sin placa, fecha de nacimiento ni código de la persona; formulario oculto; edad por rangos | ✅ `test_outfields_explicito_y_sin_datos_personales`, `test_si_el_servidor_devuelve_placa_igual_se_descarta`, `test_previsualizacion_no_muestra_columnas_personales`, `test_aceptacion.py` (todas las respuestas públicas), `test_exportacion.py::test_nunca_exporta_columnas_prohibidas` |
| C7 | Tasas solo con denominador oficial, con fórmula y fuente; nunca «peligrosa»; sin rojo/amarillo | ✅ `test_aceptacion.py::test_tasas_solo_con_denominador_oficial_y_con_formula`, `test_frontend_estatico.py::test_sin_rojo_ni_amarillo_en_la_paleta`, `test_nunca_se_califica_una_zona_como_peligrosa` |
| C8 | Polígonos oficiales o círculos en centroides rotulados | ✅ `test_geo_localidades.py` · 👁 R4 (rótulo «no son límites oficiales») · ⚠ el GeoJSON probado era de manzanas |
| C9 | Cuadrícula ~250 m en el servidor, solo conteos | ✅ `test_coordenadas_no_se_imputan_y_concentracion_solo_conteos` |

## D. Seguridad

| # | Requisito | Verificación |
|---|---|---|
| D1 | Secretos en `.env`; `.env.example` sin contraseñas reales | Revisión: `.env.example` y `.env.docker.example` solo tienen `CAMBIAR…`; Docker se niega a arrancar con esos valores |
| D2 | Contraseñas con bcrypt y política mínima | ✅ `test_api_base.py::test_hash_bcrypt`, `test_politica_de_contrasena` |
| D3 | JWT con vencimiento; rutas de administración protegidas | ✅ `test_token_valido_vencido_y_alterado`, `test_rutas_admin_exigen_token_valido` |
| D4 | Límite de peticiones y de intentos de inicio de sesión | ✅ `test_limitador_por_ip_con_regla_estricta`, `test_limite_de_intentos_de_login` |
| D5 | Cargas seguras (tamaño, tipo, bombas ZIP, archivo modificado) | ✅ `test_proteccion_de_cargas`, `test_archivos.py`, `test_archivo_modificado_tras_previsualizar` |
| D6 | CSP estricta, sin CDN ni HTML armado con datos | ✅ `test_cabeceras_de_seguridad`, `test_aceptacion.py::test_portada_con_cabeceras_de_seguridad`, `test_frontend_estatico.py` |
| D7 | Errores sin detalles internos | ✅ `test_aceptacion.py::test_errores_siempre_con_el_mismo_formato` |
| D8 | CSV sin inyección de fórmulas | ✅ `test_exportacion.py::test_neutraliza_formulas` |

---

## Recorrido de verificación manual (≈ 20 minutos)

Requisitos: instalación completa (README §2) y el servidor en marcha
(`uvicorn app.main:app --app-dir backend --reload`). Marque cada casilla.

**R1. Datos DEMO**
- [ ] `python scripts\generar_demo.py` termina con «Listo».
- [ ] En http://127.0.0.1:8000/ aparece el aviso morado «Datos de demostración» (si no hay otras fuentes) o la DEMO
      se puede elegir en Filtros → Fuente.

**R2. Inicio y búsqueda**
- [ ] Escriba «kenn» en el buscador → Enter: aparece la etiqueta «Localidad: Kennedy» y cambian las cifras.
- [ ] Pulse «Con muertos» y luego otra vez: el filtro se pone y se quita.
- [ ] Abra «Filtros», marque un año y pulse Escape: el panel se cierra y el filtro queda.
- [ ] Copie la dirección de la página, ábrala en otra pestaña: se ve la misma consulta.

**R3. Fuentes y metodología**
- [ ] Las fichas muestran registros, periodo y última carga; la fuente en uso dice «En uso ahora».

**R4. Mapa**
- [ ] Capa «Por localidad»: si no hay polígonos oficiales, el panel dice que son círculos y que «no son límites oficiales».
- [ ] Capa «Puntos»: los grupos se separan al acercar; un punto abre su fecha, hora y clase.
- [ ] Capa «Calor» y «Concentración» (cambie a 500 m) se dibujan sin rojo ni amarillo.
- [ ] El panel indica cuántos registros no tienen ubicación válida.

**R5. Analítica, Explorador y descargas**
- [ ] Analítica muestra 7 tarjetas; «Ver los datos en tabla» abre la tabla.
- [ ] Explorador → «CSV para Excel»: el archivo abre en columnas en Excel, sin columna de formulario.
- [ ] «Informe / PDF» → «Imprimir» → «Guardar como PDF» produce un PDF legible.

**R6. ArcGIS**
- [ ] Administración → Sincronizar ArcGIS → Incremental: aparece «En proceso» y luego «Completada» (o «Fallida» con
      el motivo, si el servicio no responde; los datos anteriores siguen visibles).

**R7. Ayuda**
- [ ] Busque «solo danos» (sin tilde): aparecen las preguntas relacionadas, abiertas.

**R8. Administración**
- [ ] Contraseña errada → «Correo o contraseña incorrectos». Contraseña correcta → panel.
- [ ] Importar un CSV con una columna renombrada: la revisión marca «Obligatorio: falta», no deja confirmar; al
      elegir la columna y «volver a revisar», deja confirmar.
- [ ] Un archivo con columna PLACA: aparece «Columnas omitidas por privacidad: PLACA» y la placa no se ve en la muestra.
- [ ] Historial: la carga aparece con su detalle. «Cerrar sesión» vuelve al formulario.

**R9. Teclado y celular**
- [ ] Toda la aplicación se recorre con Tab / Mayús+Tab; Escape cierra panel y ventanas.
- [ ] En el celular (o con la ventana angosta) no hay desplazamiento horizontal y el mapa aparece primero.
