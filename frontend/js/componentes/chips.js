// Chips de filtros activos: cada uno se puede quitar con un botón accesible.
import * as estado from '../estado.js';
import { fmtFecha, h, vaciar } from '../util.js';
import { nombreFiltro } from './filtros.js';

export function pintarChips(contenedor, { etiqueta, nombreFuente }) {
  const f = estado.filtros();
  const chips = [h('span', { class: 'chip chip--info' }, `Fuente: ${nombreFuente(f.fuente)}`)];

  if (!f.gravedad.length) {
    chips.push(h('span', { class: 'chip chip--info' }, 'Gravedad: con heridos o con muertos (por defecto)'));
  }
  for (const clave of ['fecha_desde', 'fecha_hasta']) {
    if (f[clave]) chips.push(chip(clave, f[clave], `${nombreFiltro(clave)}: ${fmtFecha(f[clave])}`));
  }
  for (const clave of estado.CLAVES_LISTA) {
    for (const valor of f[clave]) chips.push(chip(clave, valor, `${nombreFiltro(clave)}: ${etiqueta(clave, valor)}`));
  }
  if (estado.conteoActivos()) {
    chips.push(h('button', { class: 'boton boton--enlace', type: 'button', onclick: () => estado.limpiar() },
      'Limpiar todos los filtros'));
  }
  vaciar(contenedor, chips);

  const conteo = document.querySelector('[data-conteo-filtros]');
  if (conteo) {
    const n = estado.conteoActivos();
    conteo.hidden = n === 0;
    conteo.textContent = n;
  }
}

function chip(clave, valor, texto) {
  return h('span', { class: 'chip' }, texto,
    h('button', { type: 'button', 'aria-label': `Quitar filtro ${texto}`, title: 'Quitar filtro',
      onclick: () => estado.quitar(clave, valor) }, '×'));
}
