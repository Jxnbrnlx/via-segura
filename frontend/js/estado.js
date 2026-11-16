// Estado global ÚNICO de filtros. Cualquier cambio notifica a todos los suscriptores
// (tarjetas, tabla, gráficos y mapa) y se refleja en la URL para poder compartir la vista:
//   #/tablero?fuente=anuario_2025&anio=2025&localidad=SUBA

export const CLAVES_LISTA = ['anio', 'mes', 'localidad', 'clase', 'gravedad', 'actor'];
export const CLAVES_TEXTO = ['fuente', 'fecha_desde', 'fecha_hasta'];

const VACIO = Object.freeze({
  fuente: '', fecha_desde: '', fecha_hasta: '', anio: [], mes: [], localidad: [], clase: [], gravedad: [], actor: [],
});

let estado = copiar(VACIO);
const suscriptores = new Set();
let pendiente = null;

function copiar(e) {
  const salida = {};
  for (const c of CLAVES_TEXTO) salida[c] = e[c] ?? '';
  for (const c of CLAVES_LISTA) salida[c] = [...(e[c] ?? [])];
  return salida;
}

export function filtros() {
  return copiar(estado);
}

/** Parámetros listos para la API (sin vacíos). */
export function parametros(extra = {}) {
  const p = {};
  for (const c of CLAVES_TEXTO) if (estado[c]) p[c] = estado[c];
  for (const c of CLAVES_LISTA) if (estado[c].length) p[c] = [...estado[c]];
  return { ...p, ...extra };
}

/** Número de filtros activos (sin contar la fuente). */
export function conteoActivos() {
  return CLAVES_LISTA.reduce((n, c) => n + estado[c].length, 0)
    + (estado.fecha_desde ? 1 : 0) + (estado.fecha_hasta ? 1 : 0);
}

export function actualizar(parcial, { notificar: avisar = true } = {}) {
  const nuevo = copiar({ ...estado, ...parcial });
  for (const c of CLAVES_LISTA) nuevo[c] = [...new Set(nuevo[c].map(String))];
  if (JSON.stringify(nuevo) === JSON.stringify(estado)) return;
  estado = nuevo;
  escribirURL();
  if (avisar) programarAviso();
}

export function alternar(clave, valor, activo) {
  const lista = new Set(estado[clave]);
  if (activo) lista.add(String(valor)); else lista.delete(String(valor));
  actualizar({ [clave]: [...lista] });
}

export function quitar(clave, valor) {
  if (CLAVES_LISTA.includes(clave)) actualizar({ [clave]: estado[clave].filter((v) => v !== String(valor)) });
  else actualizar({ [clave]: '' });
}

/** Limpia todos los filtros, pero conserva la fuente elegida. */
export function limpiar() {
  actualizar({ ...copiar(VACIO), fuente: estado.fuente });
}

export function suscribir(fn) {
  suscriptores.add(fn);
  return () => suscriptores.delete(fn);
}

// Varios cambios seguidos (p. ej. marcar tres localidades) producen una sola actualización.
function programarAviso() {
  clearTimeout(pendiente);
  pendiente = setTimeout(() => {
    const copia = filtros();
    suscriptores.forEach((fn) => fn(copia));
  }, 120);
}

// ---------------------------------------------------------------- URL
export function rutaActual() {
  const [ruta] = window.location.hash.replace(/^#\/?/, '').split('?');
  return ruta || 'tablero';
}

export function consultaURL() {
  const p = new URLSearchParams();
  for (const c of CLAVES_TEXTO) if (estado[c]) p.set(c, estado[c]);
  for (const c of CLAVES_LISTA) estado[c].forEach((v) => p.append(c, v));
  return p.toString();
}

function escribirURL() {
  const consulta = consultaURL();
  const nuevo = `#/${rutaActual()}${consulta ? `?${consulta}` : ''}`;
  if (window.location.hash !== nuevo) window.history.replaceState(null, '', nuevo);
}

/** Lee los filtros de la URL (al cargar la página o al pegar un enlace compartido). */
export function leerURL() {
  const [, consulta = ''] = window.location.hash.split('?');
  const p = new URLSearchParams(consulta);
  const leido = copiar(VACIO);
  for (const c of CLAVES_TEXTO) leido[c] = p.get(c) || '';
  for (const c of CLAVES_LISTA) leido[c] = p.getAll(c);
  estado = leido;
}
