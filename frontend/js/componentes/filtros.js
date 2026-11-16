// Panel de filtros construido con los valores reales de la fuente (/metadata/fields).
// Cada control escribe en el estado global; el panel solo refleja el estado (no guarda nada propio).
import * as estado from '../estado.js';
import { h, MESES, titulo, vaciar } from '../util.js';

export const OPCIONES_GRAVEDAD = [
  { valor: '', etiqueta: 'Con heridos o con muertos', nota: 'serie comparable (recomendado)' },
  { valor: 'Con Muertos', etiqueta: 'Solo con muertos' },
  { valor: 'Con Heridos', etiqueta: 'Solo con heridos' },
  { valor: 'Solo Daños', etiqueta: 'Solo daños', nota: 'no comparable entre años' },
  { valor: 'todas', etiqueta: 'Todas las gravedades', nota: 'incluye solo daños' },
];

/** Textos legibles para chips y leyendas, a partir de los metadatos de la fuente. */
export function crearEtiquetas(metadatos) {
  const valores = metadatos?.datos?.valores_para_filtros ?? {};
  const localidades = new Map((valores.localidades ?? []).map((l) => [l.clave, l.nombre]));
  return (clave, valor) => {
    switch (clave) {
      case 'localidad': return localidades.get(valor) ?? titulo(valor);
      case 'mes': return MESES[Number(valor) - 1] ?? valor;
      case 'actor': return titulo(valor);
      case 'gravedad': return OPCIONES_GRAVEDAD.find((o) => o.valor === valor)?.etiqueta ?? valor;
      default: return valor;
    }
  };
}

const NOMBRES = { anio: 'Año', mes: 'Mes', localidad: 'Localidad', clase: 'Clase', gravedad: 'Gravedad', actor: 'Actor vial',
  fecha_desde: 'Desde', fecha_hasta: 'Hasta' };
export const nombreFiltro = (clave) => NOMBRES[clave] ?? clave;

function grupoCasillas(titulo_, clave, opciones, { abierto = false, columnas = false, nota = null } = {}) {
  const insignia = h('span', { class: 'insignia', hidden: true, 'data-insignia': clave });
  return h('details', { class: 'grupo-filtro', open: abierto },
    h('summary', {}, titulo_, insignia),
    nota ? h('p', { class: 'nota-filtro' }, nota) : null,
    h('fieldset', {},
      h('legend', {}, titulo_),
      h('div', { class: `opciones${columnas ? ' opciones--columnas' : ''}` },
        opciones.map((o) => h('label', { class: 'opcion' },
          h('input', {
            type: 'checkbox', value: o.valor, 'data-clave': clave,
            onchange: (e) => estado.alternar(clave, o.valor, e.target.checked),
          }),
          o.etiqueta)))));
}

export function montarPanel(cuerpo, { fuentes, metadatos, alCambiarFuente }) {
  const valores = metadatos?.datos?.valores_para_filtros ?? {};
  const dimensiones = new Map((metadatos?.datos?.dimensiones ?? []).map((d) => [d.clave, d]));
  const fuentesSiniestros = fuentes.filter((f) => f.tipo === 'siniestros');
  const gravedadesFuente = new Set(valores.gravedades ?? []);
  const actual = estado.filtros();

  const selectorFuente = h('select', {
    id: 'filtro-fuente',
    onchange: (e) => alCambiarFuente(e.target.value),
  }, fuentesSiniestros.map((f) => h('option', { value: f.codigo, disabled: !f.registros, selected: f.codigo === actual.fuente },
    `${f.nombre}${f.registros ? '' : ' (sin datos)'}`)));

  const fecha = (clave, texto) => h('div', { class: 'campo' },
    h('label', { for: `filtro-${clave}` }, texto),
    h('input', {
      type: 'date', id: `filtro-${clave}`, 'data-clave-texto': clave,
      min: valores.anios?.length ? `${valores.anios[0]}-01-01` : null,
      max: valores.anios?.length ? `${valores.anios[valores.anios.length - 1]}-12-31` : null,
      onchange: (e) => estado.actualizar({ [clave]: e.target.value }),
    }));

  const opcionesGravedad = OPCIONES_GRAVEDAD.filter((o) => !o.valor || o.valor === 'todas' || gravedadesFuente.has(o.valor));
  const grupoGravedad = h('details', { class: 'grupo-filtro', open: true },
    h('summary', {}, 'Gravedad'),
    h('fieldset', {},
      h('legend', {}, 'Gravedad del siniestro'),
      h('div', { class: 'opciones' }, opcionesGravedad.map((o) => h('label', { class: 'opcion' },
        h('input', {
          type: 'radio', name: 'filtro-gravedad', value: o.valor, 'data-gravedad': '',
          onchange: () => estado.actualizar({ gravedad: o.valor ? [o.valor] : [] }),
        }),
        h('span', {}, o.etiqueta, o.nota ? h('small', {}, ` (${o.nota})`) : null))))));

  const personas = dimensiones.get('personas');
  const grupos = [
    grupoCasillas('Año', 'anio', [...(valores.anios ?? [])].reverse().map((a) => ({ valor: String(a), etiqueta: a })),
      { abierto: true, columnas: true }),
    grupoCasillas('Mes', 'mes', MESES.map((m, i) => ({ valor: String(i + 1), etiqueta: m })), { columnas: true }),
    grupoCasillas('Localidad', 'localidad', (valores.localidades ?? []).map((l) => ({ valor: l.clave, etiqueta: l.nombre }))),
    grupoCasillas('Clase de siniestro', 'clase', (valores.clases ?? []).map((c) => ({ valor: c, etiqueta: c }))),
    personas?.disponible
      ? grupoCasillas('Actor vial', 'actor', (valores.actores ?? []).map((a) => ({ valor: a, etiqueta: titulo(a) })),
        { nota: 'Siniestros con al menos una persona de esa condición.' })
      : h('p', { class: 'nota-filtro' }, 'Filtro por actor vial no disponible: esta fuente no tiene personas importadas. ',
        personas?.nota ?? ''),
  ];

  vaciar(cuerpo,
    h('p', { class: 'subtitulo' }, 'Los cambios se aplican al instante en todas las secciones.'),
    h('div', { class: 'campo' }, h('label', { for: 'filtro-fuente' }, 'Fuente de datos'), selectorFuente,
      h('small', {}, 'Las cifras de fuentes distintas no se suman.')),
    fecha('fecha_desde', 'Desde'),
    fecha('fecha_hasta', 'Hasta'),
    grupoGravedad,
    grupos);

  function sincronizar(f = estado.filtros()) {
    cuerpo.querySelectorAll('input[data-clave]').forEach((el) => {
      el.checked = f[el.dataset.clave].includes(el.value);
    });
    const gravedad = f.gravedad.length === 1 ? f.gravedad[0] : '';
    cuerpo.querySelectorAll('input[data-gravedad]').forEach((el) => { el.checked = el.value === gravedad; });
    cuerpo.querySelectorAll('input[data-clave-texto]').forEach((el) => { el.value = f[el.dataset.claveTexto] || ''; });
    cuerpo.querySelectorAll('[data-insignia]').forEach((el) => {
      const n = f[el.dataset.insignia].length;
      el.hidden = n === 0;
      el.textContent = n;
      el.setAttribute('aria-label', `${n} seleccionados`);
    });
    selectorFuente.value = f.fuente;
  }
  sincronizar();
  return { sincronizar };
}
