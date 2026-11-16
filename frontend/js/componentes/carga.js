// Estados de carga, error y "sin datos" reutilizables por todas las vistas.
import { esCancelacion } from '../api.js';
import { h, vaciar } from '../util.js';

export const cargando = (texto = 'Cargando datos…') => h('p', { class: 'estado cargando', role: 'status' }, texto);

export const vacio = (texto = 'No hay registros para estos filtros. Pruebe ampliando el periodo o quitando filtros.') =>
  h('div', { class: 'estado estado--vacio', role: 'status' }, texto);

export function cajaError(error, reintentar) {
  const detalles = Array.isArray(error?.detalles) ? error.detalles : [];
  return h('div', { class: 'estado estado--error', role: 'alert' },
    h('p', {}, h('strong', {}, 'No se pudieron cargar los datos.')),
    h('p', {}, error?.message || 'Ocurrió un error inesperado.'),
    detalles.length ? h('ul', {}, detalles.map((d) => h('li', {}, d.campo ? `${d.campo}: ${d.mensaje}` : d.mensaje))) : null,
    reintentar ? h('button', { class: 'boton boton--secundario', type: 'button', onclick: reintentar }, 'Reintentar') : null);
}

// Algunos avisos de la API hablan de parámetros; en la interfaz se explican con los controles visibles.
const TRADUCCIONES = [
  [/Use gravedad=todas para incluir 'Solo Daños'\./, 'Para incluir «Solo daños», elija «Todas las gravedades» en los filtros.'],
];
const traducir = (texto) => TRADUCCIONES.reduce((t, [patron, nuevo]) => t.replace(patron, nuevo), texto);

export function listaAvisos(avisos = []) {
  const unicos = [...new Set(avisos.filter(Boolean).map(traducir))];
  if (!unicos.length) return null;
  return h('ul', { class: 'avisos', 'aria-label': 'Advertencias sobre los datos' },
    unicos.map((a) => h('li', { class: 'aviso' }, a)));
}

/**
 * Pide datos y los pinta en `contenedor`. En la primera carga muestra un indicador; en las
 * siguientes deja el contenido anterior atenuado (aria-busy) hasta que llega el nuevo.
 * Si la petición fue cancelada por otra más reciente, no hace nada.
 */
export async function cargarEn(contenedor, pedir, pintar) {
  const primera = !contenedor.hasChildNodes() || contenedor.querySelector('.estado');
  if (primera) vaciar(contenedor, cargando());
  contenedor.setAttribute('aria-busy', 'true');
  try {
    const datos = await pedir();
    vaciar(contenedor);
    await pintar(contenedor, datos);
    contenedor.removeAttribute('aria-busy');
    return datos;
  } catch (error) {
    if (esCancelacion(error)) return null;
    contenedor.removeAttribute('aria-busy');
    vaciar(contenedor, cajaError(error, () => cargarEn(contenedor, pedir, pintar)));
    return null;
  }
}
