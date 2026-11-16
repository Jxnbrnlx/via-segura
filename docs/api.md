# API REST de VÍA SEGURA (v1)

Para arrancar: `uvicorn app.main:app --app-dir backend --reload`. Documentación interactiva:
`http://127.0.0.1:8000/api/docs`. Todas las rutas empiezan por `/api/v1`.

## Reglas comunes

- **Una fuente por consulta.** El parámetro `fuente` recibe el código o un alias: `arcgis` (por defecto),
  `anuario_2025` o `anuario_2015_2024`. Las cifras de fuentes distintas nunca se suman.
- **Filtros combinables** (con Y). Las listas se pasan repitiendo el parámetro: `fecha_desde`, `fecha_hasta`
  (AAAA-MM-DD), `anio`, `mes` (1-12), `localidad` (nombre o clave: `Usaquén`, `USAQUEN`), `clase`,
  `gravedad` y `actor` (condición de la persona: `PEATON`, `CICLISTA`, `MOTOCICLISTA`…).
- **Gravedad por defecto:** "Con Heridos" y "Con Muertos", porque es la serie comparable entre años.
  `gravedad=todas` incluye "Solo Daños". Esta categoría siempre se informa aparte, con su advertencia.
- **Filtro `actor`:** limita los siniestros a los que tienen al menos una persona de esa condición. Las
  personas contadas pasan a ser solo las de esa condición.
- **Cada respuesta incluye** `datos`, `unidad` (siniestros o personas), `fuente` (ficha), `periodo` (fechas
  mínima y máxima reales de lo filtrado y número de registros), `filtros` y `advertencias`.
- **Personas:** son "derivado de actor vial" y nunca se suman con siniestros.
- **No se publican** el formulario (IPAT), la edad exacta (solo el rango), la placa, la fecha de nacimiento
  ni el código de la persona.
- **Coordenadas:** solo se devuelven las válidas. Las que no lo son se cuentan aparte.
- **Paginación:** máximo 200 filas por página.
- **Errores:** `{"error": {"codigo", "mensaje", "detalles"?}}`, con estados 400, 401, 404, 405, 409, 411,
  413, 422, 429 y 500. Nunca incluyen el valor enviado ni trazas internas.
- **Límite de peticiones:** `LIMITE_PETICIONES_POR_MINUTO` por IP en `/api/` y `LIMITE_LOGIN_POR_MINUTO`
  en el inicio de sesión. Al superarlo responde 429 con la cabecera `Retry-After`.
- **CORS:** solo los orígenes de `CORS_ORIGENES`.

## Consulta pública

| Método y ruta | Parámetros propios (además de `fuente` y los filtros) | Devuelve |
|---|---|---|
| GET `/health` | — | Estado del servicio y de la base de datos |
| GET `/sources` | — | Fichas de las fuentes: entidad, URL, periodo real, fecha de descarga, registros, última actualización, notas |
| GET `/metadata/fields` | `fuente` | Dimensiones disponibles en la fuente, con una nota si falta alguna; valores para los filtros (años, localidades, clases, gravedades, actores); campos no publicados |
| GET `/dashboard/summary` | filtros | Indicadores (siniestros, siniestros con muertos, personas heridas y fallecidas), "Solo Daños" aparte, cobertura de coordenadas y tasas por 100.000 habitantes si hay población oficial |
| GET `/accidents` | filtros, `pagina`, `tamano` (≤200), `orden` (`fecha`, `hora`, `localidad`, `clase`, `gravedad` o `id`; con `-` es descendente), `q` (busca en dirección, barrio y vía), `solo_con_coordenada` | Tabla paginada; coordenadas solo si son válidas; personas derivadas por siniestro |
| GET `/accidents/{id_registro}` | `fuente` | Detalle con personas (rango de edad), vehículos y causas |
| GET `/accidents/geojson` | filtros, `limite` (≤10.000; por defecto 2.000), `bbox=oeste,sur,este,norte` | FeatureCollection de puntos válidos (los más recientes primero), con cuántos quedan sin coordenada y si se truncó |
| GET `/analytics/by-locality` | filtros | Siniestros y personas por localidad, tasa por 100.000 habitantes (fórmula y fuente) y registros sin localidad |
| GET `/analytics/by-period` | filtros, `agrupacion` (`anio` o `mes`) | Serie con siniestros por gravedad y personas heridas y fallecidas |
| GET `/analytics/by-hour-day` | filtros | Matriz de 7 días × 24 horas y conteo de siniestros sin hora |
| GET `/analytics/by-actor` | filtros, `dimension` (`condicion`, `sexo` o `rango_edad`) | Personas por grupo y estado |
| GET `/analytics/by-severity` | filtros | Siniestros por gravedad (y gravedad tradicional si existe), "Solo Daños" aparte y personas por estado |
| GET `/analytics/by-class` | filtros | Siniestros por clase |
| GET `/analytics/concentration` | filtros, `tamano_celda_m` (100-1000; por defecto 250), `minimo`, `bbox` | Celdas con límites, centro y conteo (nunca los puntos individuales) |
| GET `/localities/geojson` | filtros | Polígonos oficiales con conteos y tasas; si no se han cargado, círculos en el centroide de los puntos reales, rotulados como tales |
| GET `/export/accidents.csv` | filtros, `formato` (`excel`: `;` y coma decimal; `estandar`: `,` y punto decimal), `q`, `solo_con_coordenada` | CSV (UTF-8 con BOM) con una fila por siniestro, ordenado por fecha. Personas en columnas `*_derivado_actor_vial`. Sin formulario ni datos personales; sin coordenadas si no son válidas (se indica el motivo). Textos que empiezan por `= + - @` se neutralizan con `'`. Máximo `EXPORTAR_MAX_FILAS` (300.000): si se supera responde 400 `exportacion_muy_grande` |

**Tasas** = siniestros (o personas fallecidas) ÷ suma de la población de cada año del periodo × 100.000.
Solo se calculan si hay población oficial para todas las localidades y años que intervienen. Si el periodo no
cubre años completos o incluye el año en curso, la respuesta lo advierte.

## Administración (requieren `Authorization: Bearer <token>`)

| Método y ruta | Entrada | Devuelve |
|---|---|---|
| POST `/admin/auth/login` | JSON `{"correo", "contrasena"}` | `access_token` (JWT HS256), `expira_en` y datos del usuario. Ante cualquier fallo, el mismo mensaje genérico |
| GET `/admin/me` | — | Administrador actual |
| GET `/admin/mappings` | — | Mapeos de columnas disponibles y tipos de carga |
| POST `/admin/imports` | multipart: `archivo`, `tipo` (`siniestros`, `actores`, `vehiculos`, `poblacion` o `localidades`), `mapeo`, `hoja`, `columnas` (JSON `{"campo": "Columna"}`) | 201 con la previsualización: columnas y tipos, primeras filas sin columnas personales, mapeo, validación de muestra y advertencias |
| GET `/admin/imports` | `pagina`, `tamano`, `tipo` (`arcgis` o `excel`), `estado` | Historial de cargas y sincronizaciones |
| GET `/admin/imports/{id}` | — | Detalle con errores legibles y resumen de calidad |
| POST `/admin/imports/{id}/confirm` | JSON opcional `{"url", "fecha_publicacion", "fecha_descarga"}` | 202: se procesa en segundo plano; el avance se consulta en el detalle |
| POST `/admin/imports/{id}/cancel` | — | Descarta una previsualización |
| POST `/admin/sync/arcgis` | JSON opcional `{"modo": "incremental"\|"completa", "desde_anio", "max_paginas"}` | 202: se ejecuta en segundo plano. Responde 409 si ya hay una sincronización en curso |

Las cuentas de administrador se crean desde la consola, con la contraseña pedida sin mostrarla:
`python scripts/crear_admin.py --correo admin@ejemplo.org`.

## Seguridad aplicada

- Contraseñas con bcrypt: mínimo 12 caracteres con letras y números, y máximo 72 bytes. El tiempo de
  verificación es el mismo exista o no la cuenta.
- JWT firmado con `SECRET_KEY` (en producción se exigen al menos 32 caracteres). En cada petición se verifica
  que la cuenta siga activa.
- Antes de recibir un archivo se exigen un token válido y un `Content-Length` dentro del límite. Después se
  validan la extensión, el MIME, el tamaño y el contenido, y se sanea el nombre (Parte 3).
- Consultas solo con el ORM o con parámetros. La búsqueda escapa los comodines `%` y `_`.
- Cabeceras `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` y `Permissions-Policy`; además,
  `Cache-Control: no-store` en `/admin`.
- El límite de peticiones se implementó como un middleware propio en lugar de slowapi. Así se puede probar
  sin dependencias y funciona con Starlette 1.x. Su limitación: cuenta en la memoria de cada proceso.

## Interfaz web (Parte 5)

FastAPI sirve la interfaz en `http://127.0.0.1:8000/` y sus archivos en `/static`. Está hecha con JavaScript
nativo y módulos ES, sin frameworks ni dependencias externas.

- `frontend/js/estado.js`: **único** objeto de filtros. Al cambiar, notifica a todas las piezas de la vista
  (tarjetas, tablas y, desde la Parte 6, gráficos y mapa). Además escribe los filtros en la URL
  (`#/tablero?fuente=anuario_sdm_2025&anio=2025`), así que un enlace copiado abre la misma vista.
- `frontend/js/api.js`: cliente de la API. Cancela las peticiones viejas cuando cambian los filtros y
  convierte los errores en mensajes legibles.
- `frontend/js/componentes/`: panel de filtros (construido con `/metadata/fields`), chips de filtros
  activos y estados de carga, error (con "Reintentar") y sin datos.
- `frontend/js/vistas/`: Inicio (tablero), Mapa, Analítica, Explorador, Fuentes, Ayuda, Administración e Informe.
- Si la fuente por defecto (ArcGIS) no tiene datos, la interfaz elige la primera fuente que sí los tenga y
  lo muestra en un chip.
- Seguridad: los datos se insertan siempre como texto, nunca como HTML. La política de contenido (CSP) solo
  permite scripts y estilos propios.
- Accesibilidad: enlace para saltar al contenido, foco visible, navegación completa con teclado, tablas con
  `caption` y `scope`, orden anunciado con `aria-sort` y región `aria-live` para los cambios. Contraste AA,
  sin depender del color y diseño adaptable desde 390 px.

## Mapa, gráficos y nuevo diseño (Parte 6)

### Librerías de terceros (una sola vez)

El mapa usa **Leaflet 1.9.4** (con **leaflet.markercluster 1.5.3** y **leaflet.heat 0.2.0**) y los gráficos
usan **Chart.js 4.4.1**. Como la CSP solo permite scripts del propio servidor, no se cargan desde un CDN:
se descargan a `frontend/vendor/` con

```powershell
python scripts/descargar_librerias.py
```

El script usa versiones fijas, compara cada paquete con la huella SHA-512 que publica el registro de npm,
extrae solo los archivos necesarios y escribe `frontend/vendor/LICENCIAS.txt`. Si algo falla no toca lo que
ya estaba instalado. Si las librerías faltan, la página no se rompe: los gráficos se muestran como barras
simples con la tabla de datos y el mapa explica qué comando ejecutar.

Las teselas del mapa base vienen de OpenStreetMap (`tile.openstreetmap.org`, permitido en `img-src` de la
CSP) con su atribución obligatoria. Es el único recurso externo, y solo son imágenes.

### Diseño

- **Inicio** es una portada de búsqueda: un buscador con sugerencias (localidad, año, mes, clase, actor
  vial, gravedad o una dirección, sin importar tildes; se maneja con flechas, Enter y Escape), botones de
  búsqueda rápida, cuatro indicadores, dos gráficos y accesos a Mapa, Analítica y Explorador. Las notas
  metodológicas quedan plegadas.
- Los filtros completos están en un **cajón lateral** (botón «Filtros», con contador). Los filtros activos
  siguen visibles como chips.
- Paleta azul marino, índigo, violeta y verde azulado (contraste AA comprobado). No se usan rojo ni
  amarillo para zonas o localidades.

### Mapa (`#/mapa`)

| Capa | Endpoint | Qué muestra |
|---|---|---|
| Por localidad | `/localities/geojson` | Polígonos oficiales coloreados por siniestros o tasa por 100.000 hab./año. Si no hay polígonos cargados, círculos en el promedio de coordenadas, rotulados como tales. |
| Puntos | `/accidents/geojson` | Siniestros agrupados (clúster) que se separan al acercar; color por gravedad y ventana con fecha, hora, clase y localidad. |
| Calor | `/accidents/geojson` | Densidad de puntos con coordenada válida. |
| Concentración | `/analytics/concentration` | Cuadrícula de 250 m, 500 m o 1 km calculada en el servidor (solo conteos). |

Los puntos se piden solo para la zona visible (`bbox`) con un límite según el acercamiento, y se recargan
al mover el mapa. La escala temporal filtra por año. El panel siempre informa cuántos registros no tienen
ubicación válida y si el resultado se recortó por el límite.

### Analítica (`#/analitica`)

Siniestros por año o mes (apilado por gravedad), personas heridas y fallecidas (derivado de actor vial,
en un gráfico aparte), siniestros por localidad (conteo o tasa), personas por condición, sexo o rango de
edad, siniestros por clase, por gravedad (con «Solo daños» aparte) y una matriz día × hora. Cada gráfico
indica unidad, fuente y periodo y tiene «Ver los datos en tabla» para lectores de pantalla y para copiar.

## Fuentes, Ayuda, Administración y descargas (Parte 7)

- **Fuentes y metodología** (`#/fuentes`): fichas de cada fuente leídas de `/sources` (registros, periodo,
  fechas, última carga y enlace oficial), los datos disponibles en la fuente en uso (`/metadata/fields`), cómo
  se cuentan las cifras, limitaciones y descarga.
- **Ayuda** (`#/ayuda`): preguntas frecuentes con buscador (sin tildes ni mayúsculas) y glosario.
- **Descargas**: «CSV para Excel», «CSV estándar» (en Explorador y Fuentes; usan los filtros activos y, en
  el Explorador, también la búsqueda) e «Informe / PDF» (`#/informe`): un resumen en tablas que se imprime
  o se guarda como PDF desde el navegador. No se usa ninguna librería de PDF.
- **Administración** (`#/admin`):
  - Inicio de sesión. El token se guarda en `sessionStorage`, así que se borra al cerrar la pestaña; la contraseña
    nunca se guarda. Si el token vence, se vuelve al formulario con un aviso.
  - Importar en tres pasos: elegir tipo, mapeo y archivo → revisar (validación de la muestra, columnas
    personales omitidas, mapeo editable campo por campo, hoja del libro, primeras filas) → confirmar (con URL y
    fechas opcionales de la publicación). Luego se sigue el avance hasta que termina.
  - Sincronizar ArcGIS (incremental o completa, desde un año), con seguimiento del estado.
  - Historial con filtros por origen y estado, y detalle de cada carga.
- Si todavía no hay datos, Inicio, Mapa, Analítica y Explorador lo explican y enlazan a Administración. Fuentes,
  Ayuda y Administración siguen disponibles.

## Datos DEMO (Parte 8)

`scripts/generar_demo.py` crea la fuente `demo_sintetica` (alias `demo`) con datos inventados, importados por el
mismo importador oficial. Se consulta como cualquier fuente (`?fuente=demo`), nunca es la fuente por defecto y la
página muestra un aviso permanente mientras está elegida. `--borrar` la elimina sin tocar las demás fuentes.
