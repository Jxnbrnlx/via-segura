// Botones de descarga: CSV (para Excel o estándar) con los filtros actuales e informe imprimible (PDF).
import { solicitar } from '../api.js';
import * as estado from '../estado.js';
import { anunciar, fmtNumero, h, icono, vaciar } from '../util.js';

function nombreDesdeCabecera(cabeceras, porDefecto) {
  const coincide = /filename="([^"]+)"/.exec(cabeceras.get('content-disposition') || '');
  return coincide ? coincide[1] : porDefecto;
}

function guardarBlob(blob, nombre) {
  const url = URL.createObjectURL(blob);
  const enlace = h('a', { href: url, download: nombre, hidden: true });
  document.body.append(enlace);
  enlace.click();
  enlace.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

/**
 * @param ctx contexto de la aplicación (para ir al informe)
 * @param extra función que devuelve parámetros propios de la vista (búsqueda, solo con coordenada…)
 */
export function crearExportar(ctx, { extra = () => ({}), compacto = false } = {}) {
  const estadoTexto = h('p', { class: 'exportar__estado', role: 'status' });
  const botones = [];

  async function descargar(formato, boton) {
    botones.forEach((b) => { b.disabled = true; });
    boton.setAttribute('aria-busy', 'true');
    estadoTexto.className = 'exportar__estado';
    vaciar(estadoTexto, 'Preparando el archivo… (con muchos registros puede tardar un poco)');
    try {
      const { blob, cabeceras } = await solicitar('/export/accidents.csv', {
        parametros: estado.parametros({ formato, ...extra() }), binario: true });
      const nombre = nombreDesdeCabecera(cabeceras, 'via-segura.csv');
      guardarBlob(blob, nombre);
      const total = Number(cabeceras.get('x-total-registros'));
      const texto = `Descargado ${nombre}${Number.isFinite(total) ? ` con ${fmtNumero(total)} siniestros` : ''}.`;
      vaciar(estadoTexto, texto);
      anunciar(texto);
    } catch (error) {
      estadoTexto.className = 'exportar__estado exportar__estado--error';
      vaciar(estadoTexto, error.message || 'No se pudo descargar el archivo.');
    } finally {
      botones.forEach((b) => { b.disabled = false; });
      boton.removeAttribute('aria-busy');
    }
  }

  const boton = (texto, titulo, formato) => {
    const b = h('button', { type: 'button', class: 'boton boton--secundario', title: titulo,
      onclick: () => descargar(formato, b) }, icono('descarga'), texto);
    botones.push(b);
    return b;
  };

  return h('div', { class: `exportar${compacto ? ' exportar--compacto' : ''}`, role: 'group', 'aria-label': 'Descargar datos' },
    h('div', { class: 'exportar__botones' },
      boton('CSV para Excel', 'Separado por punto y coma, con coma decimal (Excel en español)', 'excel'),
      boton('CSV estándar', 'Separado por comas, con punto decimal (Python, R, QGIS…)', 'estandar'),
      h('button', { type: 'button', class: 'boton boton--secundario',
        onclick: () => ctx.irA('informe') }, icono('imprimir'), 'Informe / PDF')),
    compacto ? null : h('p', { class: 'suave exportar__nota' },
      'Se descargan los siniestros con los filtros activos (una fila por siniestro). Las personas van en columnas '
      + 'aparte, marcadas como derivadas de actor vial. No incluye el número de formulario ni datos personales.'),
    estadoTexto);
}
