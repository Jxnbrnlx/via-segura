# VÍA SEGURA

Aplicación web para consultar la **siniestralidad vial histórica de Bogotá D.C.**: cuántos siniestros hubo,
dónde, cuándo, de qué tipo y a quiénes afectaron. Usa datos oficiales de la Secretaría Distrital de Movilidad
(servicio ArcGIS SIMUR y anuarios de siniestralidad).

> **No es** navegación, **no es** información en tiempo real y **no predice** siniestros. Muestra registros
> históricos oficiales, con sus límites explicados en la propia aplicación (sección «Fuentes y metodología»).

Proyecto académico. Backend en Python (FastAPI + SQLAlchemy), frontend en JavaScript sin frameworks, mapas con
Leaflet y gráficos con Chart.js.

---

## Contenido

1. [Qué hace](#1-qué-hace)
2. [Instalación desde cero en Windows (PowerShell)](#2-instalación-desde-cero-en-windows-powershell)
3. [Cargar datos](#3-cargar-datos)
4. [Uso diario](#4-uso-diario)
5. [Con Docker (opcional)](#5-con-docker-opcional)
6. [Pruebas](#6-pruebas)
7. [Decisiones del proyecto](#7-decisiones-del-proyecto)
8. [API](#8-api)
9. [Seguridad y privacidad](#9-seguridad-y-privacidad)
10. [Limitaciones conocidas](#10-limitaciones-conocidas)
11. [Estructura del proyecto](#11-estructura-del-proyecto)
12. [Problemas frecuentes](#12-problemas-frecuentes)
13. [Licencias y créditos](#13-licencias-y-créditos)

---

## 1. Qué hace

| Sección | Para qué sirve |
|---|---|
| **Inicio** | Buscador («Kennedy», «2024», «atropello», «peatones», una dirección), botones rápidos, 4 cifras clave y 2 gráficos. |
| **Mapa** | Cuatro capas: por localidad (conteo o tasa por habitante), puntos agrupados, mapa de calor y concentración en cuadrícula de 250 m / 500 m / 1 km. Escala temporal por año. |
| **Analítica** | Siniestros por año o mes, personas heridas y fallecidas, localidades, actor vial (condición, sexo, edad por rangos), clase, gravedad y matriz día × hora. Cada gráfico tiene su tabla de datos. |
| **Explorador** | Tabla paginada con búsqueda por dirección, detalle de cada siniestro y descarga CSV. |
| **Fuentes y metodología** | De dónde vienen los datos, cómo se cuentan, limitaciones y descargas. |
| **Ayuda** | Preguntas frecuentes con buscador y glosario. |
| **Administración** | Inicio de sesión, importación de archivos en tres pasos, sincronización con ArcGIS e historial. |
| **Descargas** | CSV para Excel, CSV estándar e informe imprimible (Guardar como PDF). |

Filtros: fuente, fechas, año, mes, localidad, clase, gravedad y actor vial. Quedan en la dirección de la página,
así que una consulta se comparte copiando el enlace.

---

## 2. Instalación desde cero en Windows (PowerShell)

**Requisitos:** Windows 10/11, [Python 3.12 o superior](https://www.python.org/downloads/) (al instalarlo,
marque «Add python.exe to PATH») e Internet para instalar paquetes, descargar las librerías del mapa y consultar ArcGIS.

Abra **PowerShell** y copie los comandos uno por uno. Cambie `C:\Users\SU_USUARIO\Downloads` por la carpeta
donde está el zip.

**Paso 1. Descomprimir el proyecto.**

```powershell
Expand-Archive C:\Users\SU_USUARIO\Downloads\via-segura.zip -DestinationPath C:\Users\SU_USUARIO\Downloads\via-segura-app -Force
cd C:\Users\SU_USUARIO\Downloads\via-segura-app\via-segura
```

Compruebe que está en la carpeta correcta: `dir` debe mostrar `backend`, `frontend`, `scripts` y `README.md`.

**Paso 2. Crear y activar el entorno virtual.**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Al principio de la línea debe aparecer `(.venv)`. Si Windows dice que la ejecución de scripts está deshabilitada:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

**Paso 3. Instalar las dependencias.**

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

**Paso 4. Crear la configuración (`.env`).**

```powershell
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
notepad .env
```

En el Bloc de notas, reemplace el valor de `SECRET_KEY=` por el texto largo que imprimió el segundo comando,
guarde y cierre. Para uso local puede dejar `DATABASE_URL=sqlite:///./via_segura.db`.

**Paso 5. Crear la base de datos.**

```powershell
alembic upgrade head
```

**Paso 6. Descargar las librerías del mapa y los gráficos** (Leaflet y Chart.js, una sola vez):

```powershell
python scripts\descargar_librerias.py
```

**Paso 7. Crear su cuenta de administrador.** La contraseña se pide sin mostrarse: mínimo 12 caracteres, con letras y números.

```powershell
python scripts\crear_admin.py --correo su_correo@ejemplo.org
```

**Paso 8. Comprobar que todo está bien.**

```powershell
pytest
```

Todas las pruebas deben pasar (`passed`).

**Paso 9. Cargar datos.** Vea la [sección 3](#3-cargar-datos). Para probar rápido:

```powershell
python scripts\generar_demo.py
```

**Paso 10. Abrir la aplicación.**

```powershell
uvicorn app.main:app --app-dir backend --reload
```

Abra **http://127.0.0.1:8000/** en el navegador. Para detener el servidor, pulse `Ctrl + C` en PowerShell.

---

## 3. Cargar datos

Puede combinar las opciones. **Las fuentes nunca se suman**: en la página se elige una a la vez
(«Filtros» → «Fuente»).

### Opción A: datos DEMO (sintéticos, para probar)

```powershell
python scripts\generar_demo.py                   # 4.000 siniestros inventados (2020-2025)
python scripts\generar_demo.py --cantidad 20000  # más registros
python scripts\generar_demo.py --borrar          # quitarlos
```

Aparecen como la fuente **«DEMO — Datos sintéticos (no son cifras oficiales)»**, con un aviso visible en todas
las pantallas. Son inventados con semilla fija y no reproducen ningún siniestro real. Las ubicaciones se dispersan
alrededor de celdas de ~500 m de zonas urbanas. Incluyen a propósito registros sin coordenada, fuera de Bogotá,
sin localidad y sin hora, para ver los avisos de calidad. Detalle en `backend/app/services/demo.py`.

### Opción B: ArcGIS SIMUR (fuente principal y por defecto)

```powershell
python scripts\sync_arcgis.py --modo completa --desde-anio 2015   # primera carga (tarda: cientos de miles de registros)
python scripts\sync_arcgis.py                                     # después: incremental (solo lo nuevo o modificado)
```

También desde la página: **Administración → Sincronizar ArcGIS**. Si el servicio no responde, se conservan los
datos guardados y la sincronización queda como «fallida» en el historial.

### Opción C: anuarios, población y polígonos

Desde la página (**Administración → Importar archivo**): elija el tipo y el archivo, revise la previsualización
y confirme. Nada se guarda hasta confirmar. Orden recomendado para un anuario: **siniestros → actores →
vehículos**. También por consola:

```powershell
python scripts\importar_archivo.py RUTA\anuario2025.csv --tipo siniestros --mapeo anuario_sdm_2025 --confirmar
python scripts\importar_archivo.py RUTA\poblacion.csv --tipo poblacion --mapeo poblacion_osb_localidad --confirmar
```

Guía completa: [`docs/guia_importacion.md`](docs/guia_importacion.md).

---

## 4. Uso diario

Cada vez que vaya a usar la aplicación:

```powershell
cd C:\Users\SU_USUARIO\Downloads\via-segura-app\via-segura
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --app-dir backend --reload
```

Para actualizar con lo último de ArcGIS: `python scripts\sync_arcgis.py`, o el botón en Administración.

---

## 5. Con Docker (opcional)

Levanta la aplicación con **PostgreSQL** en dos contenedores. Requiere
[Docker Desktop](https://www.docker.com/products/docker-desktop/).

```powershell
cd C:\Users\SU_USUARIO\Downloads\via-segura-app\via-segura
Copy-Item .env.docker.example .env.docker
notepad .env.docker
```

Cambie `POSTGRES_PASSWORD` y `SECRET_KEY` (todo lo que dice `CAMBIAR`). El contenedor se niega a arrancar si
quedan valores de ejemplo. Evite el carácter `$` en las contraseñas. Opcional: `CARGAR_DEMO=1` carga los datos DEMO;
`ADMIN_CORREO` y `ADMIN_CONTRASENA` crean el administrador al arrancar.

```powershell
docker compose --env-file .env.docker up -d --build
docker compose --env-file .env.docker logs -f app        # ver el arranque (Ctrl + C para salir)
```

Abra **http://localhost:8000/**. Otros comandos:

```powershell
docker compose --env-file .env.docker exec app python scripts/crear_admin.py --correo su_correo@ejemplo.org
docker compose --env-file .env.docker exec app python scripts/sync_arcgis.py
docker compose --env-file .env.docker down          # detener (los datos se conservan)
docker compose --env-file .env.docker down -v       # detener y BORRAR la base de datos
```

La imagen descarga Leaflet y Chart.js al construirse, con verificación SHA-512. La base de datos no se expone fuera
de Docker; los datos persisten en volúmenes.

---

## 6. Pruebas

```powershell
pytest                       # todas
pytest -q backend\tests\test_aceptacion.py   # solo las de aceptación
```

| Archivo | Qué comprueba |
|---|---|
| `test_aceptacion.py` | Recorre **todos** los endpoints públicos (descubiertos solos) con varios filtros: sin formulario, placas, fechas de nacimiento ni edades exactas; nunca «peligrosa»; una fuente por consulta; KPI por defecto y «solo daños» aparte; coordenadas sin imputar; concentración solo con conteos; tasas con fórmula y denominador; errores con formato uniforme; cabeceras de seguridad. |
| `test_frontend_estatico.py` | Sin librerías de CDN, sin HTML armado con datos (`innerHTML`), sin rojo ni amarillo en la paleta, sin calificar zonas. |
| `test_calidad.py`, `test_lectores_mapeos.py`, `test_archivos.py` | Normalización, fechas, coordenadas, lectura de CSV/XLSX y protección de cargas. |
| `test_importador*.py`, `test_geo_localidades.py` | Importación en dos pasos, sin duplicados, columnas personales descartadas. |
| `test_arcgis_*.py` | Cliente y sincronización con un ArcGIS simulado (paginación, reintentos, servicio caído). |
| `test_api_*.py` | Endpoints públicos y de administración, exportación CSV. |
| `test_demo.py` | Datos DEMO: reproducibles, coherentes, pasan por el importador oficial y se borran sin tocar otras fuentes. |
| `test_descargar_librerias.py` | Descargador de Leaflet/Chart.js: huella SHA-512, rutas seguras, no rompe lo instalado. |

---

## 7. Decisiones del proyecto

1. **Fuente por defecto: ArcGIS SIMUR.** El tablero filtra por **una** fuente y nunca suma fuentes.
2. **Sin duplicados:** cada siniestro se identifica por (fuente, código). Las coincidencias entre fuentes se
   **informan** al importar; no se fusionan.
3. **KPI por defecto: siniestros con heridos o muertos.** «Solo daños» va aparte, con advertencia: su registro cae
   desde 2023.
4. **Siniestros ≠ víctimas.** Las personas se calculan desde la tabla de actores viales («derivado de actor vial»)
   y nunca se suman con siniestros.
5. **Coordenadas nunca imputadas.** Motivos: `sin_coordenada`, `fuera_de_rango`, `fuera_de_bogota`, `sospechosa`
   (lejos del resto de su localidad).
6. **Privacidad:** no se importan placas, fechas de nacimiento ni códigos de las personas. El formulario (IPAT) no
   se expone. La edad se muestra solo por rangos.
7. **Tasas solo con denominador oficial** (población por localidad y año), con fórmula y fuente visibles. Ninguna
   localidad se llama «peligrosa». No se usa rojo ni amarillo para calificar zonas.
8. **Mapa por localidad** con polígonos oficiales. Si no están cargados, se usan círculos en el promedio de
   coordenadas, rotulados como tales.
9. **Concentración en cuadrícula (~250 m) calculada en el servidor:** solo se envían conteos por celda.

---

## 8. API

Documentación interactiva: **http://127.0.0.1:8000/api/docs**. Referencia completa: [`docs/api.md`](docs/api.md).

| Método | Ruta (prefijo `/api/v1`) | Para qué |
|---|---|---|
| GET | `/health` | Estado del servicio |
| GET | `/sources` | Fichas de las fuentes |
| GET | `/metadata/fields` | Dimensiones disponibles y valores para filtros |
| GET | `/dashboard/summary` | Indicadores, «solo daños» aparte, cobertura y tasas |
| GET | `/accidents` | Tabla paginada (filtros, búsqueda, orden) |
| GET | `/accidents/{id}` | Detalle con personas (rango de edad), vehículos y causas |
| GET | `/accidents/geojson` | Puntos con coordenada válida (por zona visible) |
| GET | `/analytics/by-period` · `by-locality` · `by-hour-day` · `by-actor` · `by-severity` · `by-class` | Agregados para gráficos |
| GET | `/analytics/concentration` | Cuadrícula con conteos |
| GET | `/localities/geojson` | Polígonos (o centroides rotulados) con conteos y tasas |
| GET | `/export/accidents.csv` | Descarga CSV con los filtros |
| POST | `/admin/auth/login` | Iniciar sesión (JWT) |
| GET/POST | `/admin/imports` · `/admin/imports/{id}` · `…/confirm` · `…/cancel` | Importación en dos pasos e historial |
| GET | `/admin/mappings` | Mapeos de columnas |
| POST | `/admin/sync/arcgis` | Sincronizar ArcGIS en segundo plano |

Filtros comunes: `fuente`, `fecha_desde`, `fecha_hasta`, `anio`, `mes`, `localidad`, `clase`, `gravedad`
(o `todas`) y `actor`. Los filtros de lista se pueden repetir.

---

## 9. Seguridad y privacidad

- Secretos solo en `.env` / `.env.docker` (excluidos de Git). Los archivos `*.example` no tienen contraseñas reales.
- Contraseñas con bcrypt (mínimo 12 caracteres). JWT HS256 con vencimiento. En la página, el token vive en
  `sessionStorage` (se borra al cerrar la pestaña).
- Límite de peticiones por IP, más estricto en el inicio de sesión. Límite de tamaño de archivos y protección contra
  «bombas ZIP».
- Cabeceras de seguridad y CSP estricta: solo scripts propios (Leaflet y Chart.js se sirven desde el propio
  servidor), sin `eval` ni HTML armado con datos. El único recurso externo son las imágenes del mapa base de
  OpenStreetMap.
- Columnas personales descartadas al leer (placa, fecha de nacimiento, código de la persona, documentos, etc.).
- CSV exportado sin datos personales y con protección contra inyección de fórmulas.

---

## 10. Limitaciones conocidas

**De los datos**

- Son siniestros **reportados**: puede haber subregistro, sobre todo de los leves.
- «Solo daños» casi desaparece de las fuentes desde 2023. La serie total no es comparable entre años; por eso el
  indicador principal es «con heridos o muertos».
- Los anuarios no traen causas ni barrio, y el anuario 2025 no trae «solo daños». Las categorías son las de cada
  fuente y pueden cambiar de criterio entre años.
- Las tasas usan la población del Observatorio de Salud de Bogotá. Los años futuros de ese archivo son proyecciones.
- Los datos más recientes de ArcGIS pueden cambiar. La sincronización incremental revisa una ventana de 90 días
  (`ARCGIS_VENTANA_DIAS`); para recoger correcciones más antiguas, haga una sincronización completa.

**Del mapa**

- El archivo GeoJSON que se probó era de **manzanas**, no de localidades, y el importador lo rechaza con un mensaje
  claro. Mientras no se cargue el GeoJSON oficial de localidades, el mapa por localidad usa círculos (rotulados) y la
  revisión «sospechosa» usa una heurística: puntos muy alejados del resto de su localidad.
- Las imágenes del mapa base necesitan Internet (OpenStreetMap).

**Técnicas**

- SQLite sirve para uso local. Para varios usuarios simultáneos use PostgreSQL (Docker lo trae configurado).
- El límite de peticiones se guarda en la memoria de cada proceso: con varios procesos o servidores, cada uno
  cuenta por separado.
- Las importaciones y sincronizaciones corren dentro del mismo servidor. Si se reinicia a mitad de una, esa carga
  queda «En proceso» en el historial: vuelva a importarla. Una sincronización bloqueada se libera sola a las 12 horas.
- El PDF se genera con «Imprimir → Guardar como PDF» del navegador: no hay generación de PDF en el servidor.
- Cada CSV tiene un máximo de 300.000 filas (`EXPORTAR_MAX_FILAS`). Con más, hay que acotar los filtros.

**De la verificación**

- Las pruebas automáticas de la interfaz se hicieron en Chrome contra una API simulada, con sustitutos de Leaflet y
  Chart.js. El mapa y los gráficos reales se verificaron a mano en Windows.
- **Los archivos de Docker no se pudieron construir en el entorno de desarrollo** (no había un servicio de Docker
  disponible). La configuración se validó con `docker compose config`, pero la primera construcción debe
  comprobarse en un equipo con Docker Desktop.
- La accesibilidad se probó con teclado y revisando roles y etiquetas ARIA, no con un lector de pantalla real.

---

## 11. Estructura del proyecto

```
via-segura/
├── backend/
│   ├── app/
│   │   ├── main.py              # aplicación FastAPI, middlewares, archivos estáticos
│   │   ├── config.py            # configuración desde .env
│   │   ├── models.py            # tablas (SQLAlchemy)
│   │   ├── seed_fuentes.py      # fichas de las fuentes
│   │   ├── api/                 # dependencias, errores, middlewares de seguridad
│   │   ├── routers/             # publico.py y admin.py
│   │   ├── schemas/             # filtros y entradas de administración
│   │   ├── services/            # calidad, ArcGIS, importador, consultas, exportación, demo…
│   │   └── data/mapeos/         # cómo se leen las columnas de cada archivo oficial
│   └── tests/                   # pruebas (pytest)
├── frontend/
│   ├── index.html
│   ├── css/estilos.css
│   ├── js/                      # app.js, estado.js, api.js, sesion.js, componentes/ y vistas/
│   └── vendor/                  # Leaflet y Chart.js (lo crea scripts/descargar_librerias.py)
├── alembic/                     # migraciones de la base de datos
├── scripts/                     # sync_arcgis, importar_archivo, crear_admin, generar_demo, descargar_librerias…
├── docker/arranque.sh           # arranque del contenedor
├── docs/                        # API, guía de importación, diccionario de datos, calidad, verificación
├── Dockerfile · docker-compose.yml · .env.example · .env.docker.example
└── requirements.txt · pytest.ini · alembic.ini
```

---

## 12. Problemas frecuentes

| Síntoma | Solución |
|---|---|
| `Activate.ps1 no se reconoce` | No existe el entorno: `python -m venv .venv`. Si dice que los scripts están deshabilitados: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`. |
| `can't open file ...\scripts\...py` | No está en la carpeta del proyecto, o el zip quedó en otra subcarpeta. Use `Expand-Archive` como en el paso 1 y compruebe con `dir`. |
| `La base de datos no tiene las tablas` | Ejecute `alembic upgrade head`. |
| La página dice «Todavía no hay datos» | Cargue datos ([sección 3](#3-cargar-datos)). |
| «El mapa no está disponible» o gráficos como barras simples | `python scripts\descargar_librerias.py` y recargue con `Ctrl + F5`. |
| Se ve el diseño viejo | `Ctrl + F5` (recarga sin caché). |
| `{"error":{"codigo":"no_encontrado"...}}` en `/` | Falta la carpeta `frontend/` (zip incompleto o extraído en otra parte): vuelva a extraer con `Expand-Archive`. |
| Docker: `.env.docker todavía tiene valores de ejemplo` | Cambie `SECRET_KEY` y `POSTGRES_PASSWORD` en `.env.docker`. |

---

## 13. Licencias y créditos

- **Datos:** Secretaría Distrital de Movilidad de Bogotá (ArcGIS SIMUR y anuarios), Observatorio de Salud de Bogotá
  (población) y Datos Abiertos Bogotá (localidades). Las condiciones de uso son las de cada publicación.
- **Mapa base:** © colaboradores de OpenStreetMap.
- **Librerías:** Leaflet 1.9.4 (BSD-2-Clause), Leaflet.markercluster 1.5.3 (MIT), Chart.js 4.4.1 (MIT) y
  Leaflet.heat 0.2.0 (su aviso de autoría va dentro del propio archivo). Las versiones y licencias se guardan en
  `frontend/vendor/LICENCIAS.txt` y `frontend/vendor/licencias/` al descargarlas.
- Proyecto académico VÍA SEGURA.
