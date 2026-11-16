// Utilidades sin dependencias: creación segura de elementos (sin innerHTML con datos) y formatos en español.

/**
 * Crea un elemento. Los hijos de texto se insertan como nodos de texto (nunca como HTML),
 * así ningún dato de la API puede inyectar código.
 *   h('p', { class: 'x', 'aria-live': 'polite' }, 'Hola ', h('strong', {}, 'mundo'))
 */
export function h(etiqueta, atributos = {}, ...hijos) {
  const el = document.createElement(etiqueta);
  for (const [clave, valor] of Object.entries(atributos || {})) {
    if (valor === null || valor === undefined || valor === false) continue;
    if (clave.startsWith('on') && typeof valor === 'function') {
      el.addEventListener(clave.slice(2).toLowerCase(), valor);
    } else if (clave === 'dataset') {
      Object.assign(el.dataset, valor);
    } else if (valor === true) {
      el.setAttribute(clave, '');
    } else {
      el.setAttribute(clave, String(valor));
    }
  }
  agregar(el, hijos);
  return el;
}

/** Como el.append, pero ignora null/undefined/false (append los convertiría en el texto "null"). */
export function anexar(el, ...hijos) {
  agregar(el, hijos);
  return el;
}

function agregar(el, hijos) {
  for (const hijo of hijos.flat(Infinity)) {
    if (hijo === null || hijo === undefined || hijo === false) continue;
    el.append(hijo instanceof Node ? hijo : document.createTextNode(String(hijo)));
  }
}

export function vaciar(el, ...hijos) {
  el.replaceChildren();
  agregar(el, hijos);
  return el;
}

const numero = new Intl.NumberFormat('es-CO');
const decimal = new Intl.NumberFormat('es-CO', { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const formatoFecha = new Intl.DateTimeFormat('es-CO', { day: 'numeric', month: 'short', year: 'numeric' });
const formatoFechaCorta = new Intl.DateTimeFormat('es-CO', { day: '2-digit', month: '2-digit', year: 'numeric' });

export const fmtNumero = (n) => (n === null || n === undefined ? '—' : numero.format(n));
export const fmtDecimal = (n) => (n === null || n === undefined ? '—' : decimal.format(n));

/** '2025-03-01' -> '1 mar 2025'. Se construye la fecha local para no correr el día por zona horaria. */
export function fmtFecha(iso) {
  if (!iso) return '—';
  const [a, m, d] = iso.slice(0, 10).split('-').map(Number);
  if (!a || !m || !d) return iso;
  return formatoFecha.format(new Date(a, m - 1, d));
}

/** '2025-03-01' -> '01/03/2025' (para tablas). */
export function fmtFechaCorta(iso) {
  if (!iso) return '—';
  const [a, m, d] = iso.slice(0, 10).split('-').map(Number);
  return a && m && d ? formatoFechaCorta.format(new Date(a, m - 1, d)) : iso;
}

export function fmtFechaHora(iso) {
  if (!iso) return '—';
  const f = new Date(iso);
  return Number.isNaN(f.getTime()) ? iso : f.toLocaleString('es-CO', { dateStyle: 'medium', timeStyle: 'short' });
}

export const fmtHora = (h, m) => (h === null || h === undefined ? 'Sin hora'
  : `${String(h).padStart(2, '0')}:${String(m ?? 0).padStart(2, '0')}`);

export const capitalizar = (t) => (t ? t.charAt(0).toUpperCase() + t.slice(1).toLowerCase() : t);

/** 'CIUDAD BOLIVAR' -> 'Ciudad Bolivar' para categorías en mayúsculas sin nombre visible. */
export const titulo = (t) => (t ? t.toLowerCase().replace(/(^|\s)\S/g, (c) => c.toUpperCase()) : t);

export const MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre',
  'Octubre', 'Noviembre', 'Diciembre'];

export function anunciar(texto) {
  const region = document.getElementById('anuncio');
  if (!region) return;
  region.textContent = '';
  // Pequeña espera para que los lectores de pantalla detecten el cambio.
  setTimeout(() => { region.textContent = texto; }, 50);
}

export function retrasar(fn, ms) {
  let id;
  return (...args) => { clearTimeout(id); id = setTimeout(() => fn(...args), ms); };
}

// ---------------------------------------------------------------- iconos (SVG en línea, decorativos)
const TRAZOS = {
  inicio: 'M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z',
  mapa: 'M9 4L3 6v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14',
  grafico: 'M4 20V11M10 20V4M16 20v-8M21 20H3',
  tabla: 'M3 5h18v14H3zM3 10h18M9 5v14',
  libro: 'M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3zM5 17a3 3 0 0 1 3-3h11',
  ayuda: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM9.6 9.2a2.5 2.5 0 1 1 3.3 2.4c-.6.3-.9.8-.9 1.4v.5M12 16.8v.2',
  candado: 'M6 11h12v10H6zM8.5 11V7.5a3.5 3.5 0 0 1 7 0V11',
  filtro: 'M3 5h18l-7 8.5V19l-4 2v-7.5z',
  buscar: 'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-4-4',
  info: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 8v.2M11 11.5h1V16h1',
  calor: 'M12 3c1 3.5 5 5.5 5 10a5 5 0 0 1-10 0c0-2.2 1.1-3.6 2.3-4.8.3 1.6 1 2.6 2 3.1C11 9 11.3 5.6 12 3z',
  auto: 'M4 16.5h16v-3.2l-2-4.8H6l-2 4.8zM6.5 16.5V19M17.5 16.5V19M7.5 13.5h.01M16.5 13.5h.01',
  persona: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4.5 20.5a7.5 7.5 0 0 1 15 0',
  herida: 'M10 4h4v6h6v4h-6v6h-4v-6H4v-4h6z',
  lazo: 'M12 3.5c1.9 0 3.3 1.5 3.3 3.3 0 2.4-3.3 5.7-3.3 5.7S8.7 9.2 8.7 6.8c0-1.8 1.4-3.3 3.3-3.3zM10.2 11.5l-3.7 8.7 2.7-.8 1.2 1.9 1.9-4.6M13.8 11.5l3.7 8.7-2.7-.8-1.2 1.9-1.9-4.6',
  flecha: 'M5 12h14M13 6l6 6-6 6',
  capas: 'M12 3l9 5-9 5-9-5zM3 13l9 5 9-5',
  calendario: 'M4 6h16v14H4zM4 10h16M8 3v4M16 3v4',
  descarga: 'M12 4v11M7 10.5l5 5 5-5M5 20h14',
  subir: 'M12 20V9M7 13.5l5-5 5 5M5 4h14',
  imprimir: 'M7 9V4h10v5M7 17H5a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-2M7 14h10v7H7z',
  sincronizar: 'M20 11a8 8 0 0 0-14.7-3.5M4 4v4h4M4 13a8 8 0 0 0 14.7 3.5M20 20v-4h-4',
  reloj: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2',
  salir: 'M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10',
  enlace: 'M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5',
  ok: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM8 12.5l2.7 2.7L16 9.8',
  alerta: 'M12 4l9 16H3zM12 10v4M12 17v.2',
  base: 'M12 8c4.4 0 8-1.3 8-3s-3.6-3-8-3-8 1.3-8 3 3.6 3 8 3zM4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3',
};

export function icono(nombre, clase = 'icono') {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('class', clase);
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  const trazo = document.createElementNS(ns, 'path');
  trazo.setAttribute('d', TRAZOS[nombre] ?? TRAZOS.info);
  trazo.setAttribute('fill', 'none');
  trazo.setAttribute('stroke', 'currentColor');
  trazo.setAttribute('stroke-width', '2');
  trazo.setAttribute('stroke-linecap', 'round');
  trazo.setAttribute('stroke-linejoin', 'round');
  svg.append(trazo);
  return svg;
}

/** Quita tildes y pasa a minúsculas, para comparar textos de búsqueda. */
export const normalizar = (t) => String(t ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim();
