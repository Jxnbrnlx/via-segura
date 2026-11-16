// Arranque: fuentes, metadatos, cajón de filtros, chips y enrutador por hash.
import { ErrorApi, obtener } from './api.js';
import { cajaError, cargando } from './componentes/carga.js';
import { pintarChips } from './componentes/chips.js';
import { crearEtiquetas, montarPanel } from './componentes/filtros.js';
import * as estado from './estado.js';
import { h, icono, vaciar } from './util.js';

const VISTAS = {
  tablero: { titulo: 'Inicio', cargar: () => import('./vistas/tablero.js') },
  mapa: { titulo: 'Mapa', cargar: () => import('./vistas/mapa.js'), ancho: true },
  analitica: { titulo: 'Analítica', cargar: () => import('./vistas/analitica.js') },
  explorador: { titulo: 'Explorador', cargar: () => import('./vistas/explorador.js') },
  fuentes: { titulo: 'Fuentes y metodología', cargar: () => import('./vistas/fuentes.js'), sinDatosOk: true },
  ayuda: { titulo: 'Ayuda', cargar: () => import('./vistas/ayuda.js'), sinDatosOk: true, sinFiltros: true },
  admin: { titulo: 'Administración', cargar: () => import('./vistas/admin.js'), sinDatosOk: true, sinFiltros: true },
  informe: { titulo: 'Informe', cargar: () => import('./vistas/informe.js') },
};

// Contexto compartido con las vistas.
export const ctx = { fuentes: [], metadatos: null, etiqueta: (_c, v) => v, panel: null, busquedaPendiente: '', sinDatos: false };
let desmontarVista = () => {};
let primeraNavegacion = true;
let rutaMontada = null;

const $ = (s) => document.querySelector(s);

function nombreFuente(codigo) {
  return ctx.fuentes.find((f) => f.codigo === codigo)?.nombre ?? codigo;
}

function elegirFuente(solicitada) {
  const conDatos = ctx.fuentes.filter((f) => f.tipo === 'siniestros' && f.registros > 0);
  if (conDatos.some((f) => f.codigo === solicitada)) return solicitada;
  return (conDatos.find((f) => f.por_defecto) ?? conDatos[0])?.codigo ?? null;
}

async function cargarMetadatos() {
  if (ctx.sinDatos) return;
  const cuerpo = $('#filtros-cuerpo');
  vaciar(cuerpo, cargando('Cargando filtros…'));
  try {
    ctx.metadatos = await obtener('/metadata/fields', { fuente: estado.filtros().fuente });
  } catch (error) {
    vaciar(cuerpo, cajaError(error, cargarMetadatos));
    return;
  }
  ctx.etiqueta = crearEtiquetas(ctx.metadatos);
  ctx.panel = montarPanel(cuerpo, { fuentes: ctx.fuentes, metadatos: ctx.metadatos, alCambiarFuente: cambiarFuente });
  refrescarChips();
}

async function cambiarFuente(codigo) {
  estado.actualizar({ fuente: codigo }, { notificar: false });
  await cargarMetadatos();
  await navegar({ forzar: true });  // la vista se reconstruye con los valores de la nueva fuente
}

function actualizarAvisoDemo() {
  const sinFiltros = Boolean(VISTAS[rutaMontada]?.sinFiltros);
  $('#aviso-demo').hidden = estado.filtros().fuente !== 'demo_sintetica' || ctx.sinDatos || sinFiltros;
}

function refrescarChips() {
  pintarChips($('#chips'), { etiqueta: ctx.etiqueta, nombreFuente });
  // Aviso permanente cuando la fuente es la DEMO sintética (nunca se confunde con datos oficiales).
  actualizarAvisoDemo();
  ctx.panel?.sincronizar();
}

// ---------------------------------------------------------------- cajón de filtros
function abrirFiltros() {
  const cajon = $('#cajon-filtros');
  if (!cajon.open) cajon.showModal();
}

function prepararCajon() {
  const cajon = $('#cajon-filtros');
  $('#abrir-filtros').addEventListener('click', abrirFiltros);
  cajon.querySelectorAll('[data-cerrar-filtros]').forEach((b) => b.addEventListener('click', () => cajon.close()));
  cajon.querySelector('[data-limpiar-filtros]').addEventListener('click', () => estado.limpiar());
  cajon.addEventListener('click', (e) => { if (e.target === cajon) cajon.close(); });  // clic en el fondo
  cajon.addEventListener('close', () => $('#abrir-filtros').focus());
}

// ---------------------------------------------------------------- enrutador
export function irA(ruta) {
  const q = estado.consultaURL();
  window.location.hash = `#/${ruta}${q ? `?${q}` : ''}`;
}

async function navegar({ forzar = false } = {}) {
  const [, consulta = ''] = window.location.hash.split('?');
  if (consulta && consulta !== estado.consultaURL()) {
    estado.leerURL();  // enlace compartido con filtros
    const fuente = elegirFuente(estado.filtros().fuente);
    if (fuente !== estado.filtros().fuente) estado.actualizar({ fuente }, { notificar: false });
    await cargarMetadatos();
    forzar = true;
  } else {
    const q = estado.consultaURL();
    window.history.replaceState(null, '', `#/${estado.rutaActual()}${q ? `?${q}` : ''}`);
  }

  let ruta = estado.rutaActual();
  if (!VISTAS[ruta]) {
    ruta = 'tablero';
    const q = estado.consultaURL();
    window.history.replaceState(null, '', `#/tablero${q ? `?${q}` : ''}`);
  }
  if (ruta === rutaMontada && !forzar) return;
  rutaMontada = ruta;

  document.querySelectorAll('.pestanas a').forEach((a) => {
    if (a.dataset.ruta === ruta) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  document.title = `${VISTAS[ruta].titulo} · VÍA SEGURA`;
  $('#contenido').classList.toggle('contenido--ancho', Boolean(VISTAS[ruta].ancho));
  $('.barra-filtros').hidden = Boolean(VISTAS[ruta].sinFiltros) || ctx.sinDatos;
  actualizarAvisoDemo();

  desmontarVista();
  desmontarVista = () => {};
  const contenedor = vaciar($('#vista'));
  if (ctx.sinDatos && !VISTAS[ruta].sinDatosOk) {
    sinDatos(contenedor);
  } else {
    try {
      const modulo = await VISTAS[ruta].cargar();
      if (rutaMontada !== ruta) return;  // el usuario ya navegó a otra sección mientras cargaba
      desmontarVista = modulo.montar(contenedor, ctx) || (() => {});
    } catch (error) {
      vaciar(contenedor, cajaError(new ErrorApi('No se pudo abrir esta sección. Recargue la página.'), () => window.location.reload()));
      console.error(error);  // eslint-disable-line no-console
    }
  }
  // Lleva el foco al contenido (lectores de pantalla), salvo que la vista ya lo haya puesto en un campo.
  if (!primeraNavegacion && !$('#vista').contains(document.activeElement)) $('#contenido').focus({ preventScroll: true });
  if (!primeraNavegacion) window.scrollTo({ top: 0 });
  primeraNavegacion = false;
}

// ---------------------------------------------------------------- arranque
function sinDatos(contenedor) {
  vaciar(contenedor,
    h('div', { class: 'cabecera-vista' }, h('h1', {}, 'Todavía no hay datos')),
    h('section', { class: 'seccion' },
      h('p', {}, 'No se ha cargado ninguna fuente de siniestros. Un administrador puede hacerlo desde ',
        h('a', { href: '#/admin' }, 'Administración'), ' (subir un anuario o sincronizar ArcGIS), o en el servidor con:'),
      h('pre', {}, 'python scripts/sync_arcgis.py --modo completa --desde-anio 2015\n'
        + 'python scripts/importar_archivo.py RUTA_DEL_ANUARIO --tipo siniestros --mapeo anuario_sdm_2025 --confirmar'),
      h('p', {}, 'Vea docs/guia_importacion.md.')));
}

async function iniciar() {
  document.querySelectorAll('[data-icono]').forEach((el) => el.prepend(icono(el.dataset.icono)));
  prepararCajon();
  estado.leerURL();
  ctx.irA = irA;
  ctx.abrirFiltros = abrirFiltros;

  try {
    ctx.fuentes = (await obtener('/sources')).datos;
  } catch (error) {
    vaciar($('#vista'), cajaError(error instanceof ErrorApi ? error : new ErrorApi(String(error)), () => window.location.reload()));
    vaciar($('#filtros-cuerpo'));
    return;
  }
  const fuente = elegirFuente(estado.filtros().fuente);
  if (fuente) {
    estado.actualizar({ fuente }, { notificar: false });
    await cargarMetadatos();
  } else {
    ctx.sinDatos = true;
    vaciar($('#filtros-cuerpo'), h('p', { class: 'suave' }, 'Sin fuentes con datos.'));
  }
  estado.suscribir(refrescarChips);
  window.addEventListener('hashchange', () => navegar());
  await navegar();
}

iniciar();
