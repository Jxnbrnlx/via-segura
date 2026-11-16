// Ayudas para Chart.js: paleta, creación con respaldo accesible y tabla "Ver datos".
// Cada gráfico tiene una tabla con las mismas cifras: la información nunca depende solo del color.
import { cargarChart, LibreriaFaltante } from '../librerias.js';
import { fmtNumero, h, vaciar } from '../util.js';

export const COLORES = {
  indigo: '#2b3a8c', azul: '#1f5fc4', teal: '#0b7d78', cian: '#19b5c4', menta: '#34d1b0', violeta: '#5b3fd1',
  ciruela: '#3a2a9a', pizarra: '#9aa5bd',
};
export const SERIE = [COLORES.indigo, COLORES.teal, COLORES.violeta, COLORES.cian, COLORES.azul, COLORES.menta,
  COLORES.ciruela, COLORES.pizarra];
export const COLOR_GRAVEDAD = { 'Con Muertos': COLORES.ciruela, 'Con Heridos': COLORES.azul, 'Solo Daños': COLORES.pizarra,
  'Sin dato': '#d3d8e4' };
export const COLOR_ESTADO = { fallecidas: COLORES.ciruela, heridas: COLORES.azul, ilesas: '#b9c1d3', sin_estado: '#e1e5ee' };

export const fmtEje = (v) => fmtNumero(v);

// Escala secuencial compartida por mapa y matrices: menta → teal → índigo → violeta (sin rojo ni amarillo).
export const ESCALA = ['#c9f1ea', '#34d1b0', '#0b7d78', '#2b3a8c', '#3a2a9a'];

/** Cortes por cuantiles (hasta 5 clases). */
export function cortes(valores, clases = 5) {
  const v = [...new Set(valores.filter((x) => x > 0))].sort((a, b) => a - b);
  if (!v.length) return [];
  if (v.length <= clases) return v;
  return Array.from({ length: clases }, (_, i) => v[Math.min(v.length - 1, Math.floor(((i + 1) * v.length) / clases) - 1)]);
}

export function indiceClase(valor, limites) {
  if (!limites.length || !valor) return -1;
  const i = limites.findIndex((l) => valor <= l);
  const clase = i === -1 ? limites.length - 1 : i;
  return Math.round((clase / Math.max(1, limites.length - 1)) * (ESCALA.length - 1));
}

export function colorPara(valor, limites) {
  const i = indiceClase(valor, limites);
  return i < 0 ? ESCALA[0] : ESCALA[i];
}

/** Barras HTML sencillas: se usan si Chart.js no está instalado. */
export function barrasSimples(etiquetas, valores) {
  const maximo = Math.max(1, ...valores);
  return h('div', { class: 'barras' }, etiquetas.map((e, i) => {
    const valor = h('span', { class: 'barras__valor' });
    valor.style.width = `${(valores[i] / maximo) * 100}%`;
    return h('div', { class: 'barras__fila' }, h('span', {}, e), h('span', { class: 'barras__pista', 'aria-hidden': 'true' }, valor),
      h('strong', {}, fmtNumero(valores[i])));
  }));
}

export function tablaDatos(titulo, columnas, filas, { abierta = false } = {}) {
  return h('details', { class: 'ver-datos', open: abierta },
    h('summary', {}, 'Ver los datos en tabla'),
    h('div', { class: 'tabla-contenedor' }, h('table', { class: 'tabla' },
      h('caption', { class: 'solo-lectores' }, titulo),
      h('thead', {}, h('tr', {}, columnas.map((c, i) => h('th', { scope: 'col', class: i ? 'num' : null }, c)))),
      h('tbody', {}, filas.map((f) => h('tr', {}, f.map((v, i) => (i === 0
        ? h('th', { scope: 'row' }, v)
        : h('td', { class: 'num' }, typeof v === 'number' ? fmtNumero(v) : v ?? '—')))))))));
}

/**
 * Dibuja un gráfico en `contenedor` (un div.grafico). Si Chart.js falta, muestra barras simples
 * (cuando se dan `respaldo.etiquetas` y `respaldo.valores`) y un aviso. Devuelve el gráfico o null.
 */
export async function dibujar(contenedor, config, { descripcion, respaldo } = {}) {
  try {
    const Chart = await cargarChart();
    const lienzo = h('canvas', { role: 'img', 'aria-label': descripcion });
    vaciar(contenedor, lienzo);
    return new Chart(lienzo, config);
  } catch (error) {
    if (!(error instanceof LibreriaFaltante)) throw error;
    contenedor.style.height = 'auto';
    vaciar(contenedor,
      respaldo ? barrasSimples(respaldo.etiquetas, respaldo.valores) : null,
      h('p', { class: 'subtitulo' }, error.message));
    return null;
  }
}
