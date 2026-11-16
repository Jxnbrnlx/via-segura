// Ayuda: preguntas frecuentes con buscador (sin tildes ni mayúsculas) y glosario.
import { anunciar, h, icono, normalizar } from '../util.js';

const PREGUNTAS = [
  ['Primeros pasos', [
    ['¿Qué es VÍA SEGURA?',
      'Una aplicación para consultar los siniestros viales registrados oficialmente en Bogotá: cuántos, dónde, cuándo y '
      + 'a quiénes afectaron. Usa datos históricos de la Secretaría Distrital de Movilidad. No es navegación, no es tiempo '
      + 'real y no predice siniestros.'],
    ['¿Por dónde empiezo?',
      'En Inicio, escriba en el buscador lo que quiere ver: una localidad («Kennedy»), un año («2024»), un tipo de '
      + 'siniestro («atropello») o un actor vial («peatones»). Elija una sugerencia y toda la aplicación se filtra. También '
      + 'puede usar los botones de búsqueda rápida debajo del buscador.'],
    ['¿Cómo comparto lo que estoy viendo?',
      'Copie la dirección de la página: los filtros quedan guardados en ella. Quien abra el enlace verá la misma consulta.'],
  ]],
  ['Buscar y filtrar', [
    ['¿Cómo combino varios filtros?',
      'Pulse «Filtros» (arriba a la izquierda). Dentro de un mismo grupo, las opciones se suman (Kennedy o Suba); entre '
      + 'grupos se combinan (Kennedy y 2024). Los filtros activos aparecen como etiquetas; pulse la × de una etiqueta para '
      + 'quitarla, o «Limpiar» para quitarlos todos.'],
    ['¿Por qué no aparecen los siniestros «solo daños»?',
      'Por defecto se cuentan los siniestros con heridos o con muertos, porque es la serie comparable entre años. Para '
      + 'incluir «solo daños», abra Filtros y elija «Todas las gravedades». Tenga en cuenta que su registro cae mucho desde '
      + '2023 en las fuentes.'],
    ['¿Qué es la «fuente» y por qué no se suman?',
      'Hay varias bases oficiales (ArcGIS de la Secretaría de Movilidad y anuarios). Un mismo siniestro puede estar en '
      + 'varias, así que sumarlas lo contaría dos veces. Por eso siempre se consulta una sola; puede cambiarla en Filtros.'],
    ['Busqué una dirección y no encuentro el siniestro',
      'La búsqueda revisa la dirección, el barrio y el nombre de la vía tal como los escribió la fuente. Pruebe con menos '
      + 'palabras («calle 80» en lugar de «calle 80 # 70-20») o con otra forma de escribirla («CL 80», «AC 80»).'],
  ]],
  ['Mapa', [
    ['¿Qué significa cada capa del mapa?',
      'Por localidad: color según la cantidad de siniestros (o la tasa por habitante). Puntos: cada siniestro con ubicación '
      + 'válida; los cercanos se agrupan en círculos con un número. Calor: dónde se acumulan los puntos. Concentración: '
      + 'cuántos registros hay en cada cuadro de 250 m, 500 m o 1 km.'],
    ['¿Una zona con más puntos es más peligrosa?',
      'No necesariamente. Más registros puede deberse a más población, más tránsito o más vías. El mapa muestra dónde se '
      + 'registraron siniestros, no el riesgo de cada lugar.'],
    ['¿Por qué hay registros «sin ubicación válida»?',
      'Algunos registros no traen coordenadas o traen coordenadas fuera de Bogotá o lejos de su localidad. No se inventa '
      + 'una ubicación: esos registros no se dibujan, pero sí cuentan en tablas y gráficos.'],
    ['El mapa no carga',
      'Si ve el aviso «El mapa no está disponible», un administrador debe ejecutar una vez: python '
      + 'scripts/descargar_librerias.py. El fondo del mapa viene de OpenStreetMap y necesita Internet.'],
  ]],
  ['Gráficos y cifras', [
    ['¿Cuál es la diferencia entre siniestros y personas?',
      'Un siniestro es un evento; una persona herida o fallecida es una víctima. Un choque puede dejar tres heridos. Por '
      + 'eso las cifras de personas van aparte, con la marca «derivado de actor vial», y nunca se suman con siniestros.'],
    ['¿Qué es la tasa por 100.000 habitantes?',
      'Los siniestros divididos por la población oficial del periodo, multiplicados por 100.000. Permite comparar '
      + 'localidades de distinto tamaño. Solo se muestra cuando hay población oficial para todos los años del periodo.'],
    ['¿Puedo ver los números exactos de un gráfico?',
      'Sí. Pase el cursor por el gráfico o abra «Ver los datos en tabla» debajo de cada uno.'],
  ]],
  ['Descargar', [
    ['¿Cómo descargo los datos?',
      'En el Explorador o en Fuentes y metodología use «CSV para Excel» (se abre directamente en Excel en español) o «CSV '
      + 'estándar» (para Python, R o QGIS). Se descargan los siniestros con los filtros activos.'],
    ['¿Cómo obtengo un PDF?',
      'Pulse «Informe / PDF». Se abre un resumen listo para imprimir; en la ventana de impresión elija «Guardar como PDF».'],
    ['La descarga dice que hay demasiados registros',
      'Cada archivo tiene un máximo de filas. Acote los filtros (por ejemplo, un año a la vez) y descargue por partes.'],
  ]],
  ['Accesibilidad', [
    ['¿Puedo usar la aplicación solo con el teclado?',
      'Sí. Tab y Mayús+Tab recorren los controles; Enter o Espacio los activan; en el buscador, las flechas recorren las '
      + 'sugerencias, Enter elige y Escape cierra. Escape también cierra el panel de filtros y las ventanas de detalle.'],
    ['¿Funciona con lector de pantalla?',
      'Los gráficos tienen una tabla equivalente, las tablas tienen títulos y los cambios importantes se anuncian. Los '
      + 'colores no son la única forma de distinguir datos.'],
  ]],
];

const GLOSARIO = [
  ['Siniestro vial', 'Evento de tránsito registrado por la autoridad, con o sin víctimas.'],
  ['Actor vial', 'Persona involucrada: conductor, pasajero, peatón, ciclista o motociclista.'],
  ['Con muertos / Con heridos / Solo daños', 'Gravedad del siniestro según su peor consecuencia.'],
  ['Clase de siniestro', 'Tipo de evento según la fuente: choque, atropello, volcamiento, caída de ocupante, etc.'],
  ['Derivado de actor vial', 'Cifra calculada a partir de la tabla de personas, no publicada directamente por la fuente.'],
  ['Coordenada válida', 'Ubicación dentro de Bogotá y coherente con la localidad registrada.'],
  ['IPAT', 'Informe Policial de Accidentes de Tránsito. Su número no se publica.'],
];

export function montar(contenedor) {
  const entrada = h('input', { type: 'search', id: 'buscar-ayuda', placeholder: 'Ej.: solo daños, tasa, descargar…',
    autocomplete: 'off' });
  const sinResultados = h('p', { class: 'estado estado--vacio', hidden: true, role: 'status' },
    'No hay preguntas con esas palabras. Pruebe con otra o revise el glosario.');

  const grupos = PREGUNTAS.map(([tema, preguntas]) => {
    const items = preguntas.map(([p, r]) => {
      const el = h('details', { class: 'pregunta' }, h('summary', {}, p), h('p', {}, r));
      el.dataset.buscar = normalizar(`${tema} ${p} ${r}`);
      return el;
    });
    const seccion = h('section', { class: 'ayuda-grupo', 'aria-label': tema }, h('h2', {}, tema), items);
    return { seccion, items };
  });

  function filtrar() {
    const palabras = normalizar(entrada.value).split(/\s+/).filter(Boolean);
    let visibles = 0;
    for (const { seccion, items } of grupos) {
      let enGrupo = 0;
      for (const el of items) {
        const coincide = palabras.every((p) => el.dataset.buscar.includes(p));
        el.hidden = !coincide;
        el.open = Boolean(palabras.length) && coincide;
        enGrupo += coincide;
      }
      seccion.hidden = !enGrupo;
      visibles += enGrupo;
    }
    sinResultados.hidden = visibles > 0;
    if (palabras.length) anunciar(`${visibles} ${visibles === 1 ? 'pregunta encontrada' : 'preguntas encontradas'}`);
  }
  entrada.addEventListener('input', filtrar);

  contenedor.append(
    h('div', { class: 'portada portada--ayuda' },
      h('h1', {}, '¿En qué le ayudamos?'),
      h('div', { class: 'buscador' },
        h('label', { for: 'buscar-ayuda', class: 'solo-lectores' }, 'Buscar en la ayuda'),
        h('div', { class: 'buscador__caja' }, icono('buscar'), entrada))),
    h('div', { class: 'ayuda' },
      h('div', { class: 'ayuda__preguntas' }, sinResultados, grupos.map((g) => g.seccion)),
      h('aside', { class: 'seccion ayuda__glosario', 'aria-labelledby': 'tit-glosario' },
        h('h2', { id: 'tit-glosario' }, 'Glosario'),
        h('dl', {}, GLOSARIO.map(([t, d]) => [h('dt', {}, t), h('dd', {}, d)])),
        h('p', { class: 'suave' }, 'Más detalle en ', h('a', { href: '#/fuentes' }, 'Fuentes y metodología'), '.'))));
  return () => {};
}
