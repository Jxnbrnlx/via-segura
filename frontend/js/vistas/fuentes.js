// Fuentes y metodología: de dónde vienen los datos, cómo se cuentan y qué límites tienen.
// Las fichas se leen de /sources (no se escriben cifras a mano en esta página).
import { crearExportar } from '../componentes/exportar.js';
import * as estado from '../estado.js';
import { fmtFecha, fmtFechaHora, fmtNumero, h, icono } from '../util.js';

const TIPOS = {
  siniestros: ['Siniestros', 'fuente-ficha--siniestros'],
  denominador: ['Población (para tasas)', 'fuente-ficha--denominador'],
  geografia: ['Geografía (para el mapa)', 'fuente-ficha--geografia'],
};
const ESTADOS = { completada: 'completada', fallida: 'fallida (se conservan los datos anteriores)' };

function dato(etiqueta, valor) {
  return [h('dt', {}, etiqueta), h('dd', {}, valor ?? '—')];
}

function ficha(f, enUso) {
  const [tipoTexto, tipoClase] = TIPOS[f.tipo] ?? ['Fuente', ''];
  const periodo = f.periodo_inicio ? `${fmtFecha(f.periodo_inicio)} – ${fmtFecha(f.periodo_fin)}` : null;
  const ultima = f.ultima_actualizacion;
  const registros = f.registros === null || f.registros === undefined ? null
    : `${fmtNumero(f.registros)} ${f.tipo === 'denominador' ? 'cifras de población' : 'siniestros'}`;
  return h('article', { class: `fuente-ficha ${tipoClase}`, 'aria-labelledby': `ficha-${f.codigo}` },
    h('div', { class: 'fuente-ficha__etiquetas' },
      h('span', { class: 'etiqueta-tipo' }, tipoTexto),
      f.por_defecto ? h('span', { class: 'etiqueta-tipo etiqueta-tipo--defecto' }, 'Por defecto') : null,
      enUso ? h('span', { class: 'etiqueta-tipo etiqueta-tipo--uso' }, 'En uso ahora') : null,
      f.tipo === 'siniestros' && !f.registros ? h('span', { class: 'etiqueta-tipo etiqueta-tipo--vacia' }, 'Sin datos cargados') : null),
    h('h3', { id: `ficha-${f.codigo}` }, f.nombre),
    h('p', { class: 'suave' }, f.entidad),
    h('dl', { class: 'lista-datos' },
      dato('Registros', registros),
      dato('Periodo', periodo),
      dato('Formato', f.formato),
      dato('Publicación', f.fecha_publicacion ? fmtFecha(f.fecha_publicacion) : null),
      dato('Descarga', f.fecha_descarga ? fmtFecha(f.fecha_descarga) : null),
      dato('Última carga', ultima ? `${fmtFechaHora(ultima.finalizada_en)} · ${ESTADOS[ultima.estado] ?? ultima.estado}` : null)),
    f.notas ? h('p', { class: 'fuente-ficha__nota' }, f.notas) : null,
    f.url ? h('a', { class: 'enlace-externo', href: f.url, target: '_blank', rel: 'noopener noreferrer' },
      'Ver la fuente oficial', icono('enlace')) : null);
}

const METODO = [
  ['base', 'Una fuente a la vez',
    'Cada consulta usa una sola fuente (por defecto, el servicio ArcGIS de la Secretaría de Movilidad). Las cifras de '
    + 'fuentes distintas nunca se suman: un mismo siniestro puede estar en ArcGIS y en un anuario. Dentro de una fuente, '
    + 'cada siniestro se guarda una sola vez (por su código), y al actualizar se reemplaza en lugar de duplicarse.'],
  ['persona', 'Siniestros y personas son cosas distintas',
    'Un siniestro es un evento; una persona herida o fallecida es una víctima. Un siniestro puede tener varias víctimas o '
    + 'ninguna. Las personas se cuentan a partir de la tabla de actores viales (por eso dicen «derivado de actor vial») y '
    + 'nunca se suman con los siniestros.'],
  ['herida', 'Gravedad: por defecto, con heridos o con muertos',
    'Las cifras principales cuentan solo los siniestros con heridos o con muertos, porque es la serie comparable entre '
    + 'años. Los siniestros «solo daños» se muestran aparte: su registro cae fuertemente desde 2023 en las fuentes y la '
    + 'causa no está documentada. Puede incluirlos eligiendo «Todas las gravedades».'],
  ['mapa', 'La ubicación nunca se inventa',
    'Si un registro no trae coordenadas o estas no son confiables, no se dibuja en el mapa y se cuenta como «sin '
    + 'ubicación válida». Motivos: sin coordenada; fuera de rango; fuera de Bogotá; o no coincide con su localidad (punto '
    + 'muy alejado del resto de puntos de esa localidad). Esos registros sí cuentan en tablas y gráficos.'],
  ['grafico', 'Tasas por habitante',
    'Solo se calculan con la población oficial por localidad y año (ficha «Población» en esta página). Fórmula: '
    + 'siniestros ÷ suma de la población de cada año del periodo × 100.000. Si falta la población de algún año, la tasa '
    + 'no se muestra. Un conteo alto no significa por sí solo mayor riesgo: influyen la población y el tránsito.'],
  ['capas', 'Mapa por localidad y concentración',
    'El mapa por localidad usa los polígonos oficiales cuando están cargados; si no, círculos en el promedio de las '
    + 'coordenadas de cada localidad, rotulados así. La concentración se calcula en el servidor sobre una cuadrícula '
    + '(250 m por defecto) y solo se envían los conteos por celda. Ninguna zona se califica como «peligrosa».'],
  ['calendario', 'Fechas y horas',
    'Se usa la fecha local de Bogotá tal como la publica la fuente. Los registros sin hora no aparecen en la matriz '
    + 'día × hora, y se indica cuántos son. Los datos más recientes pueden cambiar cuando la fuente los actualice.'],
  ['candado', 'Privacidad',
    'No se importan placas, fechas de nacimiento ni códigos de las personas. El número de formulario (IPAT) se guarda '
    + 'para enlazar tablas, pero no se publica ni se exporta. La edad se muestra solo por rangos.'],
];

const LIMITACIONES = [
  'Son registros oficiales de siniestros reportados: puede haber subregistro, sobre todo de los leves.',
  'No es información en tiempo real, no sirve para navegar y no predice siniestros.',
  'Las categorías (clase, gravedad, condición del actor) son las de la fuente; pueden cambiar de criterio entre años.',
  'Los anuarios no incluyen causas ni barrio; el anuario 2025 no incluye «solo daños».',
  'Algunas cifras de personas dependen de que la fuente traiga la tabla de actores viales.',
];

export function montar(contenedor, ctx) {
  const fuenteUso = estado.filtros().fuente;
  const porTipo = (t) => ctx.fuentes.filter((f) => f.tipo === t);
  const meta = ctx.metadatos?.datos;

  contenedor.append(
    h('div', { class: 'cabecera-vista' },
      h('h1', {}, 'Fuentes y metodología'),
      h('p', {}, 'De dónde vienen los datos, cómo se cuentan y qué no se puede concluir con ellos.')),

    h('nav', { class: 'indice', 'aria-label': 'En esta página' },
      [['#fuentes-datos', 'Fuentes'], ['#fuentes-contenido', 'Qué contiene'], ['#fuentes-metodo', 'Cómo se cuenta'],
        ['#fuentes-limites', 'Limitaciones'], ['#fuentes-descarga', 'Descargar']].map(([href, texto]) =>
        h('a', { href: '#', 'data-destino': href.slice(1), onclick: (e) => {
          e.preventDefault();
          document.getElementById(e.currentTarget.dataset.destino)?.scrollIntoView({ behavior: 'smooth' });
        } }, texto))),

    h('section', { class: 'seccion', id: 'fuentes-datos', 'aria-labelledby': 'tit-fuentes' },
      h('h2', { id: 'tit-fuentes' }, 'De dónde vienen los datos'),
      h('div', { class: 'fichas' }, ...porTipo('siniestros').map((f) => ficha(f, f.codigo === fuenteUso))),
      h('h3', { class: 'subtitulo-seccion' }, 'Fuentes de apoyo'),
      h('div', { class: 'fichas' }, ...[...porTipo('denominador'), ...porTipo('geografia')].map((f) => ficha(f, false)))),

    h('section', { class: 'seccion', id: 'fuentes-contenido', 'aria-labelledby': 'tit-contenido' },
      h('h2', { id: 'tit-contenido' }, 'Qué contiene la fuente en uso'),
      meta ? [
        h('table', { class: 'tabla tabla--compacta' },
          h('caption', {}, `Datos disponibles en «${ctx.fuentes.find((f) => f.codigo === fuenteUso)?.nombre ?? fuenteUso}»`),
          h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, 'Dato'), h('th', { scope: 'col' }, 'Disponible'),
            h('th', { scope: 'col' }, 'Nota'))),
          h('tbody', {}, meta.dimensiones.map((d) => h('tr', {},
            h('th', { scope: 'row' }, d.etiqueta ?? d.clave),
            h('td', {}, h('span', { class: `marca-si-no marca-si-no--${d.disponible ? 'si' : 'no'}` },
              d.disponible ? `Sí (${fmtNumero(d.registros)})` : 'No')),
            h('td', {}, d.nota ?? ''))))),
        meta.no_publicados?.length ? h('p', { class: 'suave' },
          h('strong', {}, 'Nunca se publica: '), meta.no_publicados.join(', '), '.') : null,
      ] : h('p', { class: 'suave' }, 'Todavía no hay una fuente de siniestros con datos.')),

    h('section', { class: 'seccion', id: 'fuentes-metodo', 'aria-labelledby': 'tit-metodo' },
      h('h2', { id: 'tit-metodo' }, 'Cómo se cuentan las cifras'),
      h('div', { class: 'metodo' }, METODO.map(([ic, tit, texto]) => h('article', { class: 'metodo__item' },
        h('span', { class: 'metodo__icono' }, icono(ic)), h('div', {}, h('h3', {}, tit), h('p', {}, texto)))))),

    h('section', { class: 'seccion', id: 'fuentes-limites', 'aria-labelledby': 'tit-limites' },
      h('h2', { id: 'tit-limites' }, 'Limitaciones'),
      h('ul', { class: 'lista-limites' }, LIMITACIONES.map((t) => h('li', {}, t)))),

    h('section', { class: 'seccion', id: 'fuentes-descarga', 'aria-labelledby': 'tit-descarga' },
      h('h2', { id: 'tit-descarga' }, 'Descargar los datos'),
      ctx.sinDatos ? h('p', { class: 'suave' }, 'Disponible cuando haya datos cargados.') : crearExportar(ctx)));
  return () => {};
}
