// Analítica: gráficos por periodo, localidad, actor vial, clase, gravedad y día × hora.
// Cada gráfico indica unidad, fuente y periodo, y ofrece sus datos en una tabla (no depende solo del color).
import { canal } from '../api.js';
import { cargarEn, listaAvisos, vacio } from '../componentes/carga.js';
import {
  COLOR_ESTADO, COLOR_GRAVEDAD, COLORES, ESCALA, cortes, dibujar, fmtEje, indiceClase, tablaDatos,
} from '../componentes/graficos.js';
import * as estado from '../estado.js';
import { anexar, capitalizar, fmtDecimal, fmtNumero, h, titulo, vaciar } from '../util.js';
import { lineaFuente, subtituloGrafico } from './tablero.js';

const preferencias = { agrupacion: 'anio', medidaLocalidad: 'siniestros', dimension: 'condicion' };
const ETIQUETA_DIMENSION = { condicion: 'Condición', sexo: 'Sexo', rango_edad: 'Rango de edad' };

// Evita huecos en la rejilla de dos columnas: si un tramo de tarjetas a media anchura
// tiene un número impar, la última pasa a ancho completo.
function equilibrar(rejilla) {
  let tramo = [];
  const cerrar = () => { if (tramo.length % 2) tramo[tramo.length - 1].classList.add('ancho-completo'); tramo = []; };
  [...rejilla.children].forEach((s) => (s.classList.contains('ancho-completo') ? cerrar() : tramo.push(s)));
  cerrar();
  return rejilla;
}

function segmentado(nombre, leyenda, opciones, actual, alCambiar) {
  return h('fieldset', { class: 'segmentado' }, h('legend', {}, leyenda),
    opciones.map(([valor, texto]) => h('label', {},
      h('input', { type: 'radio', name: nombre, value: valor, checked: valor === actual, onchange: () => alCambiar(valor) }),
      h('span', {}, texto))));
}

function tarjeta(id, tituloTexto, { ancho = false, controles = null } = {}) {
  const cuerpo = h('div');
  const seccion = h('section', { class: `seccion${ancho ? ' ancho-completo' : ''}`, 'aria-labelledby': id },
    h('div', { class: 'seccion__cabecera' }, h('h2', { id }, tituloTexto), controles), cuerpo);
  return { seccion, cuerpo };
}

export function montar(contenedor, ctx) {
  const graficos = {};
  const canales = {};
  const pedir = (clave, ruta, p) => { canales[clave] ??= canal(); return canales[clave](ruta, p); };
  const personasDisponibles = (ctx.metadatos?.datos?.dimensiones ?? []).find((d) => d.clave === 'personas')?.disponible;

  const zonaFuente = h('div');
  const periodo = tarjeta('g-periodo', 'Siniestros por periodo', { controles:
    segmentado('agrupacion', 'Agrupar por', [['anio', 'Año'], ['mes', 'Mes']], preferencias.agrupacion,
      (v) => { preferencias.agrupacion = v; cargarPeriodo(); }) });
  const personasPeriodo = tarjeta('g-personas', 'Personas heridas y fallecidas por periodo');
  const localidad = tarjeta('g-localidad', 'Siniestros por localidad', { ancho: true, controles:
    segmentado('medida-loc', 'Medida', [['siniestros', 'Siniestros'], ['tasa', 'Tasa por habitante']], preferencias.medidaLocalidad,
      (v) => { preferencias.medidaLocalidad = v; cargarLocalidad(); }) });
  const actor = tarjeta('g-actor', 'Personas por actor vial', { controles:
    segmentado('dimension', 'Ver por', [['condicion', 'Condición'], ['sexo', 'Sexo'], ['rango_edad', 'Edad']], preferencias.dimension,
      (v) => { preferencias.dimension = v; cargarActor(); }) });
  const clase = tarjeta('g-clase', 'Siniestros por clase');
  const gravedad = tarjeta('g-gravedad', 'Siniestros por gravedad');
  const horaDia = tarjeta('g-hora', 'Día de la semana y hora', { ancho: true });

  anexar(contenedor,
    h('div', { class: 'cabecera-vista' }, h('h1', {}, 'Analítica'),
      h('p', {}, 'Gráficos de los siniestros con los filtros elegidos. Siniestros y personas se muestran por separado: '
        + 'nunca se suman.')),
    zonaFuente,
    equilibrar(h('div', { class: 'rejilla-graficos' }, periodo.seccion, personasDisponibles ? personasPeriodo.seccion : null,
      localidad.seccion, actor.seccion, clase.seccion, gravedad.seccion, horaDia.seccion)));

  // ---------------------------------------------------------------- periodo
  function cargarPeriodo() {
    cargarEn(periodo.cuerpo, () => pedir('periodo', '/analytics/by-period', estado.parametros({ agrupacion: preferencias.agrupacion })),
      async (zona, r) => {
        vaciar(zonaFuente, lineaFuente(r));
        graficos.periodo?.destroy();
        graficos.personas?.destroy();
        const serie = r.datos.serie;
        if (!serie.length) { anexar(zona, vacio()); if (personasDisponibles) vaciar(personasPeriodo.cuerpo, vacio()); return; }
        const etiquetas = serie.map((s) => s.periodo);
        const gravedades = [...new Set(serie.flatMap((s) => Object.keys(s.por_gravedad)))]
          .sort((a, b) => Object.keys(COLOR_GRAVEDAD).indexOf(a) - Object.keys(COLOR_GRAVEDAD).indexOf(b));
        const lienzo = h('div', { class: 'grafico' });
        anexar(zona, subtituloGrafico(r, 'siniestros'), lienzo,
          tablaDatos('Siniestros por periodo', ['Periodo', ...gravedades, 'Total'],
            serie.map((s) => [s.periodo, ...gravedades.map((g) => s.por_gravedad[g] ?? 0), s.siniestros])),
          listaAvisos(r.advertencias.filter((a) => /en curso|Solo Daños/i.test(a))));
        graficos.periodo = await dibujar(lienzo, {
          type: 'bar',
          data: { labels: etiquetas, datasets: gravedades.map((g) => ({ label: g, data: serie.map((s) => s.por_gravedad[g] ?? 0),
            backgroundColor: COLOR_GRAVEDAD[g] ?? COLORES.pizarra, borderRadius: 4, maxBarThickness: 44 })) },
          options: { scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, beginAtZero: true, ticks: { callback: fmtEje } } } },
        }, { descripcion: 'Siniestros por periodo, apilados por gravedad', respaldo: { etiquetas, valores: serie.map((s) => s.siniestros) } });

        if (!personasDisponibles) return;
        const cuerpo = vaciar(personasPeriodo.cuerpo);
        const lienzo2 = h('div', { class: 'grafico' });
        anexar(cuerpo, subtituloGrafico(r, 'personas (derivado de actor vial)'), lienzo2,
          tablaDatos('Personas por periodo', ['Periodo', 'Heridas', 'Fallecidas'],
            serie.map((s) => [s.periodo, s.personas_heridas, s.personas_fallecidas])));
        graficos.personas = await dibujar(lienzo2, {
          type: 'line',
          data: { labels: etiquetas, datasets: [
            { label: 'Personas heridas', data: serie.map((s) => s.personas_heridas), borderColor: COLOR_ESTADO.heridas,
              backgroundColor: COLOR_ESTADO.heridas, tension: 0.3, pointStyle: 'circle', pointRadius: 4 },
            { label: 'Personas fallecidas', data: serie.map((s) => s.personas_fallecidas), borderColor: COLOR_ESTADO.fallecidas,
              backgroundColor: COLOR_ESTADO.fallecidas, tension: 0.3, pointStyle: 'rectRot', pointRadius: 5, borderDash: [6, 4] }] },
          options: { interaction: { mode: 'index', intersect: false }, scales: { y: { beginAtZero: true, ticks: { callback: fmtEje } },
            x: { grid: { display: false } } } },
        }, { descripcion: 'Personas heridas y fallecidas por periodo', respaldo: { etiquetas, valores: serie.map((s) => s.personas_fallecidas ?? 0) } });
      });
  }

  // ---------------------------------------------------------------- localidad
  function cargarLocalidad() {
    cargarEn(localidad.cuerpo, () => pedir('localidad', '/analytics/by-locality', estado.parametros()), async (zona, r) => {
      graficos.localidad?.destroy();
      const conTasa = r.datos.localidades.some((f) => f.tasa_siniestros?.disponible);
      const usarTasa = preferencias.medidaLocalidad === 'tasa' && conTasa;
      const valor = (f) => (usarTasa ? f.tasa_siniestros?.valor ?? 0 : f.siniestros);
      const filas = r.datos.localidades.filter((f) => f.siniestros).sort((a, b) => valor(b) - valor(a));
      if (!filas.length) { anexar(zona, vacio()); return; }
      const lienzo = h('div', { class: 'grafico grafico--alto' });
      const unidad = usarTasa ? 'siniestros por 100.000 habitantes por año' : 'siniestros';
      anexar(zona, subtituloGrafico(r, unidad), lienzo,
        preferencias.medidaLocalidad === 'tasa' && !conTasa
          ? h('p', { class: 'subtitulo' }, 'Tasa no disponible: falta población oficial. Se muestran conteos.') : null,
        tablaDatos('Siniestros por localidad', ['Localidad', 'Siniestros', 'Personas heridas', 'Personas fallecidas', 'Tasa por 100.000 hab./año'],
          filas.map((f) => [f.nombre, f.siniestros, f.personas_heridas, f.personas_fallecidas,
            f.tasa_siniestros?.disponible ? fmtDecimal(f.tasa_siniestros.valor) : 'No disponible'])),
        listaAvisos(r.advertencias.filter((a) => /riesgo|localidad/i.test(a))));
      const etiquetas = filas.map((f) => f.nombre);
      const valores = filas.map(valor);
      graficos.localidad = await dibujar(lienzo, {
        type: 'bar',
        data: { labels: etiquetas, datasets: [{ label: usarTasa ? 'Tasa por 100.000 hab./año' : 'Siniestros', data: valores,
          backgroundColor: usarTasa ? COLORES.violeta : COLORES.teal, borderRadius: 6, maxBarThickness: 22 }] },
        options: { indexAxis: 'y', plugins: { legend: { display: false } },
          scales: { x: { beginAtZero: true, ticks: { callback: usarTasa ? (v) => fmtDecimal(v) : fmtEje } }, y: { grid: { display: false } } } },
      }, { descripcion: `Localidades por ${unidad}`, respaldo: { etiquetas, valores } });
    });
  }

  // ---------------------------------------------------------------- actor vial
  function cargarActor() {
    cargarEn(actor.cuerpo, () => pedir('actor', '/analytics/by-actor', estado.parametros({ dimension: preferencias.dimension })),
      async (zona, r) => {
        graficos.actor?.destroy();
        if (!r.datos.disponible) { anexar(zona, listaAvisos(r.advertencias)); return; }
        const grupos = r.datos.grupos.slice(0, 10);
        if (!grupos.length) { anexar(zona, vacio()); return; }
        const etiquetas = grupos.map((g) => titulo(g.valor));
        const lienzo = h('div', { class: 'grafico' });
        anexar(zona, subtituloGrafico(r, 'personas (derivado de actor vial)'), lienzo,
          tablaDatos('Personas por actor vial', [ETIQUETA_DIMENSION[preferencias.dimension], 'Fallecidas', 'Heridas', 'Ilesas', 'Total'],
            grupos.map((g) => [titulo(g.valor), g.fallecidas, g.heridas, g.ilesas, g.personas])));
        const serie = (clave, etiqueta) => ({ label: etiqueta, data: grupos.map((g) => g[clave]), backgroundColor: COLOR_ESTADO[clave],
          borderRadius: 4, maxBarThickness: 26 });
        graficos.actor = await dibujar(lienzo, {
          type: 'bar',
          data: { labels: etiquetas, datasets: [serie('fallecidas', 'Fallecidas'), serie('heridas', 'Heridas'), serie('ilesas', 'Ilesas')] },
          options: { indexAxis: 'y', scales: { x: { stacked: true, beginAtZero: true, ticks: { callback: fmtEje } },
            y: { stacked: true, grid: { display: false } } } },
        }, { descripcion: 'Personas por actor vial y estado', respaldo: { etiquetas, valores: grupos.map((g) => g.personas) } });
      });
  }

  // ---------------------------------------------------------------- clase y gravedad
  function cargarClase() {
    cargarEn(clase.cuerpo, () => pedir('clase', '/analytics/by-class', estado.parametros()), async (zona, r) => {
      graficos.clase?.destroy();
      const clases = r.datos.clases;
      if (!clases.length) { anexar(zona, vacio()); return; }
      const etiquetas = clases.map((c) => c.clase);
      const valores = clases.map((c) => c.siniestros);
      const lienzo = h('div', { class: 'grafico' });
      anexar(zona, subtituloGrafico(r, 'siniestros'), lienzo,
        tablaDatos('Siniestros por clase', ['Clase', 'Siniestros'], clases.map((c) => [c.clase, c.siniestros])));
      graficos.clase = await dibujar(lienzo, {
        type: 'bar',
        data: { labels: etiquetas, datasets: [{ label: 'Siniestros', data: valores, borderRadius: 8, maxBarThickness: 46,
          backgroundColor: etiquetas.map((_, i) => [COLORES.indigo, COLORES.teal, COLORES.violeta, COLORES.cian, COLORES.azul, COLORES.menta, COLORES.ciruela][i % 7]) }] },
        options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { callback: fmtEje } }, x: { grid: { display: false } } } },
      }, { descripcion: 'Siniestros por clase', respaldo: { etiquetas, valores } });
    });
  }

  function cargarGravedad() {
    cargarEn(gravedad.cuerpo, () => pedir('gravedad', '/analytics/by-severity', estado.parametros()), async (zona, r) => {
      graficos.gravedad?.destroy();
      const pares = Object.entries(r.datos.siniestros_por_gravedad);
      if (!pares.length) { anexar(zona, vacio()); return; }
      const etiquetas = pares.map(([g]) => g);
      const valores = pares.map(([, n]) => n);
      const lienzo = h('div', { class: 'grafico' });
      const p = r.datos.personas_por_estado;
      anexar(zona, subtituloGrafico(r, 'siniestros'), lienzo,
        h('p', { class: 'franja' }, `Solo daños, aparte: ${fmtNumero(r.datos.solo_danos_aparte.valor)} siniestros (no comparables entre años).`),
        p ? h('p', { class: 'subtitulo' }, `Personas (derivado de actor vial): ${fmtNumero(p.fallecidas)} fallecidas, `
          + `${fmtNumero(p.heridas)} heridas, ${fmtNumero(p.ilesas)} ilesas.`) : null,
        tablaDatos('Siniestros por gravedad', ['Gravedad', 'Siniestros'], pares));
      graficos.gravedad = await dibujar(lienzo, {
        type: 'doughnut',
        data: { labels: etiquetas, datasets: [{ data: valores, backgroundColor: etiquetas.map((g) => COLOR_GRAVEDAD[g] ?? COLORES.pizarra),
          borderColor: '#ffffff', borderWidth: 3 }] },
        options: { cutout: '62%' },
      }, { descripcion: `Siniestros por gravedad: ${etiquetas.map((e, i) => `${e}: ${valores[i]}`).join(', ')}`, respaldo: { etiquetas, valores } });
    });
  }

  // ---------------------------------------------------------------- día × hora (tabla de calor accesible)
  function cargarHoraDia() {
    cargarEn(horaDia.cuerpo, () => pedir('hora', '/analytics/by-hour-day', estado.parametros()), (zona, r) => {
      const d = r.datos;
      const valores = d.matriz.flatMap((m) => m.conteos);
      if (!valores.some(Boolean)) { anexar(zona, vacio()); return; }
      const limites = cortes(valores);
      anexar(zona, subtituloGrafico(r, 'siniestros'),
        h('div', { class: 'tabla-contenedor' }, h('table', { class: 'tabla matriz' },
          h('caption', { class: 'solo-lectores' }, 'Siniestros por día de la semana (filas) y hora (columnas)'),
          h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, h('span', { class: 'solo-lectores' }, 'Día')),
            d.horas.map((hh) => h('th', { scope: 'col' }, String(hh))))),
          h('tbody', {}, d.matriz.map((fila) => h('tr', {}, h('th', { scope: 'row' }, capitalizar(fila.dia)),
            fila.conteos.map((n, hh) => {
              const celda = h('td', { title: `${capitalizar(fila.dia)}, ${hh}:00: ${fmtNumero(n)} siniestros` },
                h('span', { class: 'solo-lectores' }, fmtNumero(n)));
              const i = indiceClase(n, limites);
              celda.style.background = i < 0 ? '#f3f5fb' : ESCALA[i];
              return celda;
            })))))),
        h('p', { class: 'subtitulo' }, 'Más oscuro = más siniestros. Pase el cursor (o use un lector de pantalla) para ver la cifra exacta. '
          + (d.sin_hora ? `${fmtNumero(d.sin_hora)} siniestros sin hora no se incluyen.` : '')));
    });
  }

  function cargarTodo() {
    cargarPeriodo();
    cargarLocalidad();
    cargarActor();
    cargarClase();
    cargarGravedad();
    cargarHoraDia();
  }
  cargarTodo();
  const desuscribir = estado.suscribir(cargarTodo);
  return () => {
    desuscribir();
    Object.values(canales).forEach((c) => c.cancelar());
    Object.values(graficos).forEach((g) => g?.destroy());
  };
}
