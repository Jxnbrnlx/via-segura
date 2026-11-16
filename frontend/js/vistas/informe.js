// Informe imprimible con los filtros activos. El PDF se obtiene con «Imprimir → Guardar como PDF»
// del navegador (no se instala ninguna librería de PDF). Tablas en lugar de gráficos: se leen bien en papel.
import { obtener } from '../api.js';
import { cajaError, cargando, listaAvisos } from '../componentes/carga.js';
import { nombreFiltro } from '../componentes/filtros.js';
import * as estado from '../estado.js';
import { fmtDecimal, fmtFecha, fmtNumero, h, icono, vaciar } from '../util.js';

function tabla(titulo, columnas, filas, nota) {
  return h('section', { class: 'informe__bloque' },
    h('h2', {}, titulo),
    filas.length ? h('div', { class: 'tabla-contenedor' }, h('table', { class: 'tabla tabla--compacta' },
      h('caption', { class: 'solo-lectores' }, titulo),
      h('thead', {}, h('tr', {}, columnas.map((c, i) => h('th', { scope: 'col', class: i ? 'num' : null }, c)))),
      h('tbody', {}, filas.map((f) => h('tr', {}, f.map((v, i) => (i
        ? h('td', { class: 'num' }, v) : h('th', { scope: 'row' }, v))))))))
      : h('p', { class: 'suave' }, 'Sin registros.'),
    nota ? h('p', { class: 'suave' }, nota) : null);
}

function filtrosTexto(ctx) {
  const f = estado.filtros();
  const partes = [];
  partes.push(f.gravedad.length ? null : 'Gravedad: con heridos o con muertos (por defecto)');
  for (const c of ['fecha_desde', 'fecha_hasta']) if (f[c]) partes.push(`${nombreFiltro(c)}: ${fmtFecha(f[c])}`);
  for (const c of estado.CLAVES_LISTA) {
    if (f[c].length) partes.push(`${nombreFiltro(c)}: ${f[c].map((v) => ctx.etiqueta(c, v)).join(', ')}`);
  }
  return partes.filter(Boolean);
}

export function montar(contenedor, ctx) {
  const cuerpo = h('div', { class: 'informe__cuerpo' }, cargando('Preparando el informe…'));
  contenedor.append(
    h('div', { class: 'cabecera-vista informe__acciones no-imprimir' },
      h('h1', {}, 'Informe para imprimir'),
      h('p', {}, 'Resumen con los filtros activos. Para obtener un PDF, pulse «Imprimir» y elija «Guardar como PDF».'),
      h('div', { class: 'acciones' },
        h('button', { type: 'button', class: 'boton', onclick: () => window.print() }, icono('imprimir'), 'Imprimir o guardar como PDF'),
        h('button', { type: 'button', class: 'boton boton--secundario', onclick: () => window.history.back() }, 'Volver'))),
    h('article', { class: 'informe', 'aria-label': 'Informe' }, cuerpo));

  const p = estado.parametros();
  let vigente = true;
  Promise.all([
    obtener('/dashboard/summary', p),
    obtener('/analytics/by-period', { ...p, agrupacion: 'anio' }),
    obtener('/analytics/by-locality', p),
    obtener('/analytics/by-class', p),
    obtener('/analytics/by-severity', p),
  ]).then(([resumen, periodo, localidad, clase, gravedad]) => {
    if (!vigente) return;
    const r = resumen.datos;
    const fuente = resumen.fuente ?? {};
    const per = resumen.periodo ?? {};
    const kpi = (clave) => r.kpis.find((k) => k.clave === clave);
    const tasa = r.tasa_siniestros;
    const avisos = [...(resumen.advertencias ?? []), ...(periodo.advertencias ?? [])];

    vaciar(cuerpo,
      h('header', { class: 'informe__cabecera' },
        h('p', { class: 'informe__marca' }, 'VÍA SEGURA · Siniestralidad vial histórica de Bogotá'),
        h('h2', { class: 'informe__titulo' }, 'Resumen de siniestros viales'),
        h('dl', { class: 'lista-datos' },
          h('dt', {}, 'Fuente'), h('dd', {}, `${fuente.nombre ?? '—'} (${fuente.entidad ?? ''})`),
          h('dt', {}, 'Periodo con datos'), h('dd', {}, per.inicio ? `${fmtFecha(per.inicio)} – ${fmtFecha(per.fin)}` : 'sin registros'),
          h('dt', {}, 'Filtros'), h('dd', {}, filtrosTexto(ctx).join(' · ') || 'Ninguno'),
          h('dt', {}, 'Generado'), h('dd', {}, new Date().toLocaleString('es-CO', { dateStyle: 'long', timeStyle: 'short' })))),

      h('section', { class: 'informe__bloque informe__cifras' },
        r.kpis.map((k) => h('div', { class: 'informe__cifra' },
          h('p', { class: 'informe__valor' }, fmtNumero(k.valor)),
          h('p', {}, k.etiqueta, k.derivado ? ' (derivado de actor vial)' : '')))),
      h('p', { class: 'suave' },
        `Siniestros «solo daños», aparte: ${fmtNumero(r.solo_danos_aparte?.valor)}. `,
        `Con ubicación válida: ${fmtNumero(r.coordenadas?.validas)}; sin ubicación válida: ${fmtNumero(r.coordenadas?.sin_coordenada_valida)}.`),
      tasa?.disponible ? h('p', { class: 'suave' },
        `Tasa: ${fmtDecimal(tasa.valor)} ${tasa.unidad}. Fórmula: ${tasa.formula}. Denominador: ${tasa.fuente_denominador?.nombre ?? '—'}.`)
        : null,

      tabla('Siniestros por año', ['Año', 'Siniestros', 'Personas heridas*', 'Personas fallecidas*'],
        periodo.datos.serie.map((s) => [s.periodo, fmtNumero(s.siniestros), fmtNumero(s.personas_heridas),
          fmtNumero(s.personas_fallecidas)]),
        '* Personas: derivado de actor vial; no se suman con siniestros.'),
      tabla('Siniestros por localidad', ['Localidad', 'Siniestros', 'Tasa por 100.000 hab./año'],
        localidad.datos.localidades.filter((l) => l.siniestros > 0).map((l) => [l.nombre, fmtNumero(l.siniestros),
          l.tasa_siniestros?.disponible ? fmtDecimal(l.tasa_siniestros.valor) : 'no disponible']),
        'Solo localidades con registros. Un conteo mayor indica más registros, no necesariamente mayor riesgo.'),
      tabla('Siniestros por clase', ['Clase', 'Siniestros'],
        clase.datos.clases.map((c) => [c.clase ?? 'Sin dato', fmtNumero(c.siniestros)])),
      tabla('Siniestros por gravedad', ['Gravedad', 'Siniestros'],
        Object.entries(gravedad.datos.siniestros_por_gravedad ?? {}).map(([g, n]) => [g, fmtNumero(n)])),

      h('section', { class: 'informe__bloque' },
        h('h2', {}, 'Notas'),
        listaAvisos(avisos),
        h('p', { class: 'suave' }, 'Datos históricos oficiales; no es información en tiempo real ni una predicción. '
          + 'Las cifras de fuentes distintas no se suman. Metodología completa en la sección «Fuentes y metodología».')));
  }).catch((error) => {
    if (vigente) vaciar(cuerpo, cajaError(error, () => ctx.irA('informe')));
  });
  return () => { vigente = false; };
}
