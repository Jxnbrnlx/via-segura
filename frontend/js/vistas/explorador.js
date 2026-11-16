// Explorador: tabla paginada (máx. 200 filas por página), búsqueda, orden y detalle de cada siniestro.
// Usa los mismos filtros globales que el tablero; búsqueda, orden y página son propios de esta vista.
import { canal, obtener } from '../api.js';
import { cajaError, cargando, cargarEn, listaAvisos, vacio } from '../componentes/carga.js';
import { crearExportar } from '../componentes/exportar.js';
import * as estado from '../estado.js';
import { anexar, anunciar, capitalizar, fmtFecha, fmtFechaCorta, fmtHora, fmtNumero, h, retrasar, titulo, vaciar } from '../util.js';

const COLUMNAS = [
  { clave: 'fecha', texto: 'Fecha', ordenable: true },
  { clave: 'hora', texto: 'Hora', ordenable: true },
  { clave: 'localidad', texto: 'Localidad', ordenable: true },
  { clave: 'clase', texto: 'Clase', ordenable: true },
  { clave: 'gravedad', texto: 'Gravedad', ordenable: true },
  { clave: 'direccion', texto: 'Dirección' },
  { clave: 'heridas', texto: 'Heridas', num: true, titulo: 'Personas heridas (derivado de actor vial)' },
  { clave: 'fallecidas', texto: 'Fallecidas', num: true, titulo: 'Personas fallecidas (derivado de actor vial)' },
  { clave: 'coordenada', texto: 'Ubicación', titulo: '¿Tiene coordenada válida? Sin ella no aparece en el mapa.' },
];
const TAMANOS = [25, 50, 100, 200];

export function pildoraGravedad(g) {
  const clase = { 'Con Muertos': 'muertos', 'Con Heridos': 'heridos', 'Solo Daños': 'danos' }[g];
  return clase ? h('span', { class: `pildora pildora--${clase}` }, g) : h('span', {}, 'Sin dato');
}

export function montar(contenedor, ctx = {}) {
  const local = { pagina: 1, tamano: 50, orden: '-fecha', q: ctx.busquedaPendiente || '', soloCoordenada: false };
  ctx.busquedaPendiente = '';
  const pedir = canal();
  const zona = h('section', { class: 'seccion', 'aria-label': 'Resultados' });
  const dialogo = h('dialog', { class: 'dialogo', 'aria-labelledby': 'detalle-titulo' });

  const busqueda = h('input', {
    type: 'search', id: 'busqueda', maxlength: 100, placeholder: 'Ej.: Calle 80, Kennedy Central…', value: local.q || null,
    oninput: retrasar((e) => { local.q = e.target.value.trim(); local.pagina = 1; cargar(); }, 400),
  });
  const tamano = h('select', { id: 'tamano', onchange: (e) => { local.tamano = Number(e.target.value); local.pagina = 1; cargar(); } },
    TAMANOS.map((t) => h('option', { value: t, selected: t === local.tamano }, `${t} filas`)));

  anexar(contenedor, 
    h('div', { class: 'cabecera-vista' },
      h('h1', {}, 'Explorador de siniestros'),
      h('p', { class: 'suave' }, 'Cada fila es un siniestro. Las personas heridas o fallecidas se cuentan aparte y se '
        + 'derivan de la tabla de actores viales.')),
    h('div', { class: 'barra-herramientas' },
      h('div', { class: 'campo campo--busqueda' }, h('label', { for: 'busqueda' }, 'Buscar en dirección, barrio o vía'), busqueda),
      h('div', { class: 'campo' }, h('label', { for: 'tamano' }, 'Filas por página'), tamano),
      h('label', { class: 'opcion' },
        h('input', { type: 'checkbox', onchange: (e) => { local.soloCoordenada = e.target.checked; local.pagina = 1; cargar(); } }),
        'Solo con ubicación válida')),
    crearExportar(ctx, { compacto: true,
      extra: () => ({ q: local.q || undefined, solo_con_coordenada: local.soloCoordenada || undefined }) }),
    zona, dialogo);

  function cabecera() {
    return h('thead', {}, h('tr', {}, COLUMNAS.map((c) => {
      if (!c.ordenable) return h('th', { scope: 'col', class: c.num ? 'num' : null, title: c.titulo ?? null }, c.texto);
      const activa = local.orden.replace('-', '') === c.clave;
      const desc = local.orden.startsWith('-');
      return h('th', { scope: 'col', 'aria-sort': activa ? (desc ? 'descending' : 'ascending') : 'none' },
        h('button', {
          type: 'button',
          onclick: () => { local.orden = activa && !desc ? `-${c.clave}` : c.clave; local.pagina = 1; cargar(); },
        }, c.texto, h('span', { 'aria-hidden': 'true' }, activa ? (desc ? ' ▼' : ' ▲') : ' ↕'),
        h('span', { class: 'solo-lectores' }, activa ? (desc ? ', orden descendente' : ', orden ascendente') : ', ordenar')));
    })));
  }

  function fila(s) {
    return h('tr', {},
      h('td', { class: 'sin-salto' }, h('button', {
        type: 'button', class: 'boton boton--enlace',
        'aria-label': `Ver detalle del siniestro ${s.id_registro} del ${fmtFecha(s.fecha)}`,
        onclick: (ev) => abrirDetalle(s.id_registro, ev.currentTarget),
      }, h('time', { datetime: s.fecha }, fmtFechaCorta(s.fecha)))),
      h('td', { class: 'sin-salto' }, fmtHora(s.hora, s.minuto)),
      h('td', {}, s.localidad_nombre ?? 'Sin localidad'),
      h('td', {}, s.clase ?? '—'),
      h('td', {}, pildoraGravedad(s.gravedad)),
      h('td', { class: 'direccion' }, s.direccion ?? '—'),
      h('td', { class: 'num' }, fmtNumero(s.personas?.heridas)),
      h('td', { class: 'num' }, fmtNumero(s.personas?.fallecidas)),
      h('td', { class: 'sin-salto', title: s.coordenada_valida ? null : `Motivo: ${(s.motivo_sin_coordenada ?? '').replaceAll('_', ' ')}` },
        s.coordenada_valida ? 'Válida' : 'No válida'));
  }

  function pintar(z, r) {
    const pag = r.paginacion;
    if (!pag.total) {
      anexar(z, vacio(local.q ? `No hay siniestros que coincidan con “${local.q}” y los filtros elegidos.` : undefined));
      anexar(z, listaAvisos(r.advertencias));
      return;
    }
    const desde = (pag.pagina - 1) * pag.tamano + 1;
    const hasta = Math.min(pag.total, pag.pagina * pag.tamano);
    const irA = (n) => { local.pagina = n; cargar(); zona.scrollIntoView({ block: 'start' }); };
    anexar(z, 
      h('div', { class: 'tabla-contenedor' },
        h('table', { class: 'tabla' },
          h('caption', {}, `${fmtNumero(pag.total)} siniestros (filas ${fmtNumero(desde)}–${fmtNumero(hasta)}). `
            + `Fuente: ${r.fuente.nombre}. Periodo: ${fmtFecha(r.periodo.inicio)} a ${fmtFecha(r.periodo.fin)}. `
            + 'Pulse la fecha de un siniestro para ver su detalle.'),
          cabecera(),
          h('tbody', {}, r.datos.map(fila)))),
      h('nav', { class: 'paginacion', 'aria-label': 'Paginación' },
        h('p', { class: 'suave' }, `Página ${fmtNumero(pag.pagina)} de ${fmtNumero(pag.paginas)}`),
        h('div', { class: 'paginacion__botones' },
          h('button', { class: 'boton boton--secundario', type: 'button', disabled: pag.pagina <= 1, onclick: () => irA(1) }, '« Primera'),
          h('button', { class: 'boton boton--secundario', type: 'button', disabled: pag.pagina <= 1, onclick: () => irA(pag.pagina - 1) }, '‹ Anterior'),
          h('button', { class: 'boton boton--secundario', type: 'button', disabled: pag.pagina >= pag.paginas, onclick: () => irA(pag.pagina + 1) }, 'Siguiente ›'),
          h('button', { class: 'boton boton--secundario', type: 'button', disabled: pag.pagina >= pag.paginas, onclick: () => irA(pag.paginas) }, 'Última »'))),
      listaAvisos(r.advertencias));
    anunciar(`${fmtNumero(pag.total)} siniestros. Página ${pag.pagina} de ${pag.paginas}.`);
  }

  function cargar() {
    const p = estado.parametros({
      pagina: local.pagina, tamano: local.tamano, orden: local.orden, q: local.q,
      solo_con_coordenada: local.soloCoordenada ? 'true' : '',
    });
    cargarEn(zona, () => pedir('/accidents', p), pintar);
  }

  async function abrirDetalle(id, origen) {
    const cuerpo = h('div', { class: 'dialogo__cuerpo' }, cargando('Cargando detalle…'));
    const cerrar = h('button', { type: 'button', class: 'boton boton--icono', onclick: () => dialogo.close() },
      h('span', { 'aria-hidden': 'true' }, '×'), h('span', { class: 'solo-lectores' }, 'Cerrar detalle'));
    vaciar(dialogo, h('div', { class: 'dialogo__cabecera' }, h('h2', { id: 'detalle-titulo' }, `Siniestro ${id}`), cerrar), cuerpo);
    dialogo.addEventListener('close', () => origen?.focus(), { once: true });
    dialogo.showModal();
    cerrar.focus();
    try {
      const r = await obtener(`/accidents/${id}`, { fuente: estado.filtros().fuente });
      pintarDetalle(cuerpo, r);
    } catch (error) {
      vaciar(cuerpo, cajaError(error));
    }
  }

  function pintarDetalle(cuerpo, r) {
    const d = r.datos;
    const dato = (t, v) => [h('dt', {}, t), h('dd', {}, v ?? '—')];
    const tablaSimple = (titulo_, columnas, filas) => (filas.length ? [
      h('h3', {}, titulo_),
      h('div', { class: 'tabla-contenedor' }, h('table', { class: 'tabla' },
        h('thead', {}, h('tr', {}, columnas.map((c) => h('th', { scope: 'col' }, c[0])))),
        h('tbody', {}, filas.map((f) => h('tr', {}, columnas.map((c) => h('td', {}, c[1](f) ?? '—'))))))),
    ] : [h('h3', {}, titulo_), h('p', { class: 'suave' }, 'Sin registros en la fuente.')]);
    vaciar(cuerpo,
      h('dl', { class: 'lista-datos' },
        dato('Fecha', `${fmtFecha(d.fecha)} (${capitalizar(d.dia_semana ?? '')})`),
        dato('Hora', fmtHora(d.hora, d.minuto)),
        dato('Localidad', d.localidad_nombre ?? 'Sin localidad'),
        dato('Dirección', d.direccion), dato('Barrio', d.barrio), dato('Vía', d.via),
        dato('Clase', d.clase), dato('Gravedad', d.gravedad),
        d.gravedad_tradicional ? dato('Gravedad tradicional', d.gravedad_tradicional) : null,
        dato('Ubicación', d.coordenada_valida ? `${d.latitud.toFixed(5)}, ${d.longitud.toFixed(5)}` : 'Sin ubicación válida'),
        dato('Fuente', r.fuente.nombre)),
      tablaSimple('Personas', [['Condición', (p) => titulo(p.condicion)], ['Estado', (p) => titulo(p.estado)],
        ['Sexo', (p) => titulo(p.sexo)], ['Rango de edad', (p) => p.rango_edad]], d.personas),
      tablaSimple('Vehículos', [['Clase', (v) => titulo(v.clase)], ['Servicio', (v) => titulo(v.servicio)],
        ['Modalidad', (v) => titulo(v.modalidad)]], d.vehiculos),
      d.causas.length ? tablaSimple('Causas registradas', [['Código', (c) => c.codigo_causa], ['Descripción', (c) => c.nombre]], d.causas) : null,
      listaAvisos(r.advertencias));
  }

  const alCambiarFiltros = () => { local.pagina = 1; cargar(); };
  cargar();
  const desuscribir = estado.suscribir(alCambiarFiltros);
  return () => { desuscribir(); pedir.cancelar(); if (dialogo.open) dialogo.close(); };
}
