// Cliente de la API REST. Construye parámetros repetidos para listas (?localidad=A&localidad=B),
// convierte los errores JSON de la API en ErrorApi con un mensaje legible y permite cancelar
// peticiones que quedaron viejas cuando cambian los filtros.

const BASE = '/api/v1';

export class ErrorApi extends Error {
  constructor(mensaje, codigo = 'error', estado = 0, detalles = null) {
    super(mensaje);
    this.codigo = codigo;
    this.estado = estado;
    this.detalles = detalles;
  }
}

export function construirURL(ruta, parametros = {}) {
  const url = new URL(BASE + ruta, window.location.origin);
  for (const [clave, valor] of Object.entries(parametros)) {
    if (Array.isArray(valor)) {
      valor.forEach((v) => url.searchParams.append(clave, v));
    } else if (valor !== '' && valor !== null && valor !== undefined && valor !== false) {
      url.searchParams.set(clave, valor);
    }
  }
  return url;
}

/**
 * Petición genérica. `json` envía un cuerpo JSON; `formulario` un FormData (subida de archivos);
 * `token` añade la cabecera Authorization; `binario` devuelve la respuesta como Blob (descargas).
 */
export async function solicitar(ruta, {
  metodo = 'GET', parametros = {}, json, formulario, token, senal, binario = false,
} = {}) {
  const url = construirURL(ruta, parametros);
  const cabeceras = { Accept: binario ? '*/*' : 'application/json' };
  if (token) cabeceras.Authorization = `Bearer ${token}`;
  let cuerpoPeticion;
  if (json !== undefined) {
    cabeceras['Content-Type'] = 'application/json';
    cuerpoPeticion = JSON.stringify(json);
  } else if (formulario) {
    cuerpoPeticion = formulario;  // el navegador pone el Content-Type multipart con su separador
  }
  let respuesta;
  try {
    respuesta = await fetch(url, { method: metodo, signal: senal, headers: cabeceras, body: cuerpoPeticion });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new ErrorApi('No se pudo conectar con el servidor. Verifique que esté en ejecución e intente de nuevo.',
      'sin_conexion', 0);
  }
  if (respuesta.ok && binario) return { blob: await respuesta.blob(), cabeceras: respuesta.headers };
  let cuerpo = null;
  try {
    cuerpo = await respuesta.json();
  } catch {
    cuerpo = null;
  }
  if (!respuesta.ok) {
    const error = cuerpo?.error ?? {};
    const mensaje = error.mensaje || (respuesta.status === 429
      ? 'Demasiadas consultas seguidas. Espere unos segundos.'
      : respuesta.status === 413 ? 'El archivo es demasiado grande para el servidor.'
        : `El servidor respondió con un error (${respuesta.status}).`);
    throw new ErrorApi(mensaje, error.codigo || 'error_http', respuesta.status, error.detalles || null);
  }
  if (cuerpo === null) throw new ErrorApi('La respuesta del servidor no es válida.', 'respuesta_invalida', respuesta.status);
  return cuerpo;
}

export function obtener(ruta, parametros = {}, { senal } = {}) {
  return solicitar(ruta, { parametros, senal });
}

/**
 * Devuelve una función `pedir(ruta, parametros)` que cancela la petición anterior del mismo canal.
 * Así, si el usuario cambia varios filtros seguidos, solo se pinta la respuesta más reciente.
 */
export function canal() {
  let controlador = null;
  const pedir = (ruta, parametros) => {
    controlador?.abort();
    controlador = new AbortController();
    return obtener(ruta, parametros, { senal: controlador.signal });
  };
  pedir.cancelar = () => controlador?.abort();
  return pedir;
}

export const esCancelacion = (error) => error?.name === 'AbortError';
