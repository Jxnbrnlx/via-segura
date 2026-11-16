// Sesión del administrador. El token se guarda en sessionStorage: se borra al cerrar la pestaña y no se
// comparte con otras pestañas. Nunca se guarda la contraseña. Si el token vence, se pide iniciar sesión de nuevo.
import { ErrorApi, solicitar } from './api.js';

const CLAVE = 'via-segura.admin';
let actual = null;
const oyentes = new Set();

function leer() {
  try {
    const guardada = JSON.parse(window.sessionStorage.getItem(CLAVE) || 'null');
    if (guardada?.token && guardada.expira && new Date(guardada.expira) > new Date()) return guardada;
  } catch { /* almacenamiento no disponible o dañado: se ignora */ }
  return null;
}

function guardar(valor) {
  actual = valor;
  try {
    if (valor) window.sessionStorage.setItem(CLAVE, JSON.stringify(valor));
    else window.sessionStorage.removeItem(CLAVE);
  } catch { /* sin almacenamiento: la sesión dura mientras la página siga abierta */ }
  oyentes.forEach((fn) => fn(valor));
}

export function sesion() {
  if (actual && new Date(actual.expira) <= new Date()) guardar(null);
  return actual ?? (actual = leer());
}

export function alCambiar(fn) {
  oyentes.add(fn);
  return () => oyentes.delete(fn);
}

export async function iniciarSesion(correo, contrasena) {
  const r = await solicitar('/admin/auth/login', { metodo: 'POST', json: { correo, contrasena } });
  guardar({ token: r.access_token, expira: r.expira_en, correo: r.usuario.correo, rol: r.usuario.rol });
  return actual;
}

export function cerrarSesion() {
  guardar(null);
}

/** Petición autenticada. Si el servidor responde 401, se cierra la sesión local. */
export async function pedirAdmin(ruta, opciones = {}) {
  const s = sesion();
  if (!s) throw new ErrorApi('La sesión terminó. Inicie sesión de nuevo.', 'no_autenticado', 401);
  try {
    return await solicitar(`/admin${ruta}`, { ...opciones, token: s.token });
  } catch (error) {
    if (error.estado === 401) guardar(null);
    throw error;
  }
}
