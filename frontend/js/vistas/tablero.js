// Inicio: buscador, 4 indicadores clave, 2 gráficos y accesos. Los detalles quedan en "Notas sobre estos datos".
import { canal } from '../api.js';
import { crearAtajos, crearBuscador } from '../componentes/buscador.js';
import { cargarEn, listaAvisos, vacio } from '../componentes/carga.js';
import { COLORES, dibujar, fmtEje, tablaDatos } from '../componentes/graficos.js';
import * as estado from '../estado.js';
import { anexar, anunciar, fmtDecimal, fmtFecha, fmtNumero, h, icono, vaciar } from '../util.js';

export function lineaFuente(r) {
  const f = r.fuente ?? {};
  const p = r.periodo ?? {};
  return h('p', { class: 'linea-fuente' },
    icono('libro'),
    h('span', {}, 'Fuente: ', h('strong', {}, f.nombre ?? '—')),
    h('span', {}, 'Periodo: ', h('strong', {}, p.inicio ? `${fmtFecha(p.inicio)} – ${fmtFecha(p.fin)}` : 'sin registros')),
    f.fecha_descarga ? h('span', {}, 'Actualizado: ', h('strong', {}, fmtFecha(f.fecha_descarga))) : null);
}

export function subtituloGrafico(r, unidad) {
  const p = r.periodo?.inicio ? ` · ${fmtFecha(r.periodo.inicio)} – ${fmtFecha(r.periodo.fin)}` : '';
  return h('p', { class: 'subtitulo' }, `Unidad: ${unidad} · Fuente: ${r.fuente?.nombre ?? ''}${p}`);
}

function kpi({ etiqueta, valor, nota, iconoNombre, color, derivado }) {
  return h('article', { class: `kpi kpi--${color}` },
    h('span', { class: 'kpi__icono' }, icono(iconoNombre)),
    h('div', {},
      h('p', { class: 'kpi__etiqueta' }, etiqueta),
      h('p', { class: 'kpi__valor' }, valor),
      nota ? h('p', { class: 'kpi__nota' }, nota) : null,
      derivado ? h('span', { class: 'etiqueta-derivado' }, 'Derivado de actor vial') : null));
}

export function montar(contenedor, ctx) {
  const graficos = {};
  const pedir = { resumen: canal(), periodo: canal(), localidades: canal() };
  const zonaAtajos = h('div');
  const zonaFuente = h('div');
  const zonaKpis = h('div');
  const zonaTendencia = h('div');
  const zonaLocalidades = h('div');
  const zonaNotas = h('div', { class: 'notas__cuerpo' });

  const buscador = crearBuscador({
    metadatos: ctx.metadatos,
    alBuscarDireccion: (texto) => { ctx.busquedaPendiente = texto; ctx.irA('explorador'); },
  });

  const acceso = (ruta, titulo, texto, iconoNombre, fondo) => {
    const ic = h('span', { class: 'acceso__icono' }, icono(iconoNombre));
    ic.style.background = fondo;
    return h('a', { class: 'acceso', href: `#/${ruta}`, onclick: (e) => { e.preventDefault(); ctx.irA(ruta); } },
      ic, h('div', {}, h('strong', {}, titulo), h('span', {}, texto)));
  };

  anexar(contenedor,
    h('section', { class: 'portada', 'aria-labelledby': 'titulo-portada' },
      h('div', { class: 'portada__interior' },
        h('h1', { id: 'titulo-portada' }, '¿Qué quieres consultar?'),
        h('p', {}, 'Siniestros viales registrados en Bogotá. Busca por localidad, año, tipo de siniestro o actor vial.'),
        buscador, zonaAtajos)),
    zonaFuente,
    zonaKpis,
    h('div', { class: 'rejilla-2' },
      h('section', { class: 'seccion', 'aria-labelledby': 't-tendencia' },
        h('div', { class: 'seccion__cabecera' }, h('h2', { id: 't-tendencia' }, 'Siniestros por año')),
        zonaTendencia),
      h('section', { class: 'seccion', 'aria-labelledby': 't-localidades' },
        h('div', { class: 'seccion__cabecera' }, h('h2', { id: 't-localidades' }, 'Localidades con más registros'),
          h('a', { href: '#/analitica', onclick: (e) => { e.preventDefault(); ctx.irA('analitica'); } }, 'Ver todas')),
        zonaLocalidades)),
    h('nav', { class: 'accesos', 'aria-label': 'Explorar más' },
      acceso('mapa', 'Ver en el mapa', 'Puntos, calor y concentración', 'mapa', 'linear-gradient(135deg,#0b7d78,#19b5c4)'),
      acceso('analitica', 'Analítica', 'Gráficos por hora, actor vial y más', 'grafico', 'linear-gradient(135deg,#5b3fd1,#2b3a8c)'),
      acceso('explorador', 'Explorador', 'Cada siniestro, con su detalle', 'tabla', 'linear-gradient(135deg,#1f5fc4,#2b3a8c)')),
    h('details', { class: 'notas' }, h('summary', {}, 'Notas sobre estos datos (cómo leer las cifras)'), zonaNotas));

  function pintarResumen(_zona, r) {
    const d = r.datos;
    const valor = (clave) => d.kpis.find((k) => k.clave === clave)?.valor;
    const tasa = d.tasa_siniestros?.disponible ? `≈ ${fmtDecimal(d.tasa_siniestros.valor)} por 100.000 hab. al año` : null;
    const tarjetas = [
      kpi({ etiqueta: d.kpis[0]?.etiqueta ?? 'Siniestros', valor: fmtNumero(valor('siniestros')), nota: tasa ?? 'siniestros',
        iconoNombre: 'auto', color: 'indigo' }),
      kpi({ etiqueta: 'Siniestros con muertos', valor: fmtNumero(valor('siniestros_con_muertos')), nota: 'siniestros',
        iconoNombre: 'lazo', color: 'ciruela' }),
    ];
    if (d.personas) {
      tarjetas.push(
        kpi({ etiqueta: 'Personas heridas', valor: fmtNumero(valor('personas_heridas')), nota: 'personas',
          iconoNombre: 'herida', color: 'azul', derivado: true }),
        kpi({ etiqueta: 'Personas fallecidas', valor: fmtNumero(valor('personas_fallecidas')), nota: 'personas',
          iconoNombre: 'persona', color: 'teal', derivado: true }));
    } else {
      tarjetas.push(kpi({ etiqueta: 'Personas', valor: '—', nota: 'No disponibles en esta fuente', iconoNombre: 'persona', color: 'teal' }));
    }
    vaciar(zonaFuente, lineaFuente(r));
    vaciar(zonaKpis,
      h('h2', { class: 'solo-lectores' }, 'Indicadores principales'),
      h('div', { class: 'kpis' }, tarjetas),
      h('p', { class: 'franja' }, icono('info'),
        h('span', {}, h('strong', {}, fmtNumero(d.solo_danos_aparte.valor)), ' siniestros solo daños, contados aparte (no comparables entre años).'),
        h('span', {}, h('strong', {}, fmtNumero(d.coordenadas.validas)), ' con ubicación válida para el mapa; ',
          fmtNumero(d.coordenadas.sin_coordenada_valida), ' sin ubicación.')));
    const tasaFallecidos = d.tasa_fallecidos?.disponible
      ? `Tasa de personas fallecidas: ${fmtDecimal(d.tasa_fallecidos.valor)} ${d.tasa_fallecidos.unidad}.` : null;
    vaciar(zonaNotas,
      listaAvisos([
        ...r.advertencias, d.solo_danos_aparte.advertencia,
        d.tasa_siniestros?.disponible ? `Tasa: ${d.tasa_siniestros.formula} (población: ${d.tasa_siniestros.fuente_denominador?.nombre ?? ''}).`
          : `Tasa por habitante no disponible: ${d.tasa_siniestros?.motivo ?? ''}`,
        tasaFallecidos,
        ...(d.tasa_siniestros?.advertencias ?? []),
        'Un número mayor indica más registros, no necesariamente mayor riesgo: influyen la población y el tránsito.',
      ]));
    anunciar(`Resultados actualizados: ${fmtNumero(valor('siniestros') ?? 0)} siniestros.`);
  }

  async function pintarTendencia(zona, r) {
    graficos.tendencia?.destroy();
    const serie = r.datos.serie;
    if (!serie.length) { anexar(zona, vacio()); return; }
    const lienzo = h('div', { class: 'grafico' });
    anexar(zona, subtituloGrafico(r, 'siniestros'), lienzo,
      tablaDatos('Siniestros por año', ['Año', 'Siniestros', 'Personas heridas', 'Personas fallecidas'],
        serie.map((s) => [s.periodo, s.siniestros, s.personas_heridas, s.personas_fallecidas])));
    const etiquetas = serie.map((s) => s.periodo);
    const valores = serie.map((s) => s.siniestros);
    graficos.tendencia = await dibujar(lienzo, {
      type: 'bar',
      data: { labels: etiquetas, datasets: [{ label: 'Siniestros', data: valores, backgroundColor: COLORES.indigo,
        hoverBackgroundColor: COLORES.violeta, borderRadius: 8, maxBarThickness: 48 }] },
      options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { callback: fmtEje } },
        x: { grid: { display: false } } } },
    }, { descripcion: `Siniestros por año: ${etiquetas.map((e, i) => `${e}: ${valores[i]}`).join(', ')}`,
      respaldo: { etiquetas, valores } });
  }

  async function pintarLocalidades(zona, r) {
    graficos.localidades?.destroy();
    const filas = r.datos.localidades.filter((f) => f.siniestros).slice(0, 8);
    if (!filas.length) { anexar(zona, vacio()); return; }
    const lienzo = h('div', { class: 'grafico' });
    anexar(zona, subtituloGrafico(r, 'siniestros'), lienzo,
      tablaDatos('Localidades con más registros', ['Localidad', 'Siniestros', 'Personas fallecidas'],
        filas.map((f) => [f.nombre, f.siniestros, f.personas_fallecidas])));
    const etiquetas = filas.map((f) => f.nombre);
    const valores = filas.map((f) => f.siniestros);
    graficos.localidades = await dibujar(lienzo, {
      type: 'bar',
      data: { labels: etiquetas, datasets: [{ label: 'Siniestros', data: valores, backgroundColor: COLORES.teal,
        hoverBackgroundColor: COLORES.cian, borderRadius: 8, maxBarThickness: 26 }] },
      options: { indexAxis: 'y', plugins: { legend: { display: false } },
        scales: { x: { beginAtZero: true, ticks: { callback: fmtEje } }, y: { grid: { display: false } } } },
    }, { descripcion: `Localidades con más siniestros: ${etiquetas.map((e, i) => `${e}: ${valores[i]}`).join(', ')}`,
      respaldo: { etiquetas, valores } });
  }

  function cargar() {
    vaciar(zonaAtajos, crearAtajos(ctx.metadatos));
    const p = estado.parametros();
    cargarEn(zonaKpis, () => pedir.resumen('/dashboard/summary', p), pintarResumen);
    cargarEn(zonaTendencia, () => pedir.periodo('/analytics/by-period', { ...p, agrupacion: 'anio' }), pintarTendencia);
    cargarEn(zonaLocalidades, () => pedir.localidades('/analytics/by-locality', p), pintarLocalidades);
  }
  cargar();
  const desuscribir = estado.suscribir(cargar);
  return () => {
    desuscribir();
    Object.values(pedir).forEach((c) => c.cancelar());
    Object.values(graficos).forEach((g) => g?.destroy());
  };
}
