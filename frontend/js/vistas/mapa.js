// Mapa (Leaflet + OpenStreetMap): por localidad, puntos agrupados, calor y cuadrícula de concentración.
// Solo se dibujan coordenadas válidas; los registros sin ubicación se cuentan y se informan.
// Escalas secuenciales menta → índigo → violeta (sin rojo ni amarillo). No es una predicción de riesgo.
import { canal, esCancelacion } from '../api.js';
import { listaAvisos } from '../componentes/carga.js';
import { COLOR_GRAVEDAD, colorPara, cortes } from '../componentes/graficos.js';
import * as estado from '../estado.js';
import { cargarLeaflet, LibreriaFaltante } from '../librerias.js';
import { anexar, fmtDecimal, fmtFecha, fmtHora, fmtNumero, h, icono, retrasar, vaciar } from '../util.js';

const CAPAS = [
  { valor: 'localidad', texto: 'Por localidad', icono: 'capas' },
  { valor: 'puntos', texto: 'Puntos', icono: 'mapa' },
  { valor: 'calor', texto: 'Calor', icono: 'calor' },
  { valor: 'cuadricula', texto: 'Concentración', icono: 'tabla' },
];
const GRADIENTE_CALOR = { 0.2: '#c9f1ea', 0.4: '#34d1b0', 0.6: '#0b7d78', 0.8: '#2b3a8c', 1: '#3a2a9a' };
const CENTRO = [4.65, -74.1];
const LIMITES = [[3.65, -74.55], [4.95, -73.85]];
const OSM = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const ATRIBUCION = '&copy; <a href="https://www.openstreetmap.org/copyright">colaboradores de OpenStreetMap</a>';

// Se recuerdan entre visitas a la vista (no entre recargas de página).
const preferencias = { modo: 'localidad', metrica: 'siniestros', celda: 250 };

function leyendaClases(limites, unidad, formato = fmtNumero) {
  if (!limites.length) return h('p', { class: 'subtitulo' }, 'Sin registros para colorear.');
  let desde = null;
  return h('ul', { class: 'leyenda' }, limites.map((l) => {
    const muestra = h('span', { class: 'muestra', 'aria-hidden': 'true' });
    muestra.style.background = colorPara(l, limites);
    // Rangos sin solaparse: «Hasta 28», «Más de 28 a 35»… (sirve para conteos y tasas)
    const texto = desde === null ? `Hasta ${formato(l)}` : `Más de ${formato(desde)} a ${formato(l)}`;
    desde = l;
    return h('li', {}, muestra, `${texto} ${unidad}`);
  }));
}

function popupSiniestro(p) {
  return h('div', { class: 'popup-siniestro' },
    h('strong', {}, `Siniestro ${p.id_registro}`),
    h('dl', {},
      h('dt', {}, 'Fecha'), h('dd', {}, fmtFecha(p.fecha)),
      h('dt', {}, 'Hora'), h('dd', {}, fmtHora(p.hora, 0)),
      h('dt', {}, 'Gravedad'), h('dd', {}, p.gravedad ?? 'Sin dato'),
      h('dt', {}, 'Clase'), h('dd', {}, p.clase ?? '—')));
}

export function montar(contenedor, ctx) {
  const pedir = canal();
  let mapa = null;
  let L = null;
  let capa = null;
  let primeraVista = true;

  const divMapa = h('div', { id: 'mapa', role: 'region', 'aria-label': 'Mapa de siniestros. Use el panel para cambiar de capa.' });
  const mensaje = h('div', { class: 'mapa-mensaje', role: 'status', hidden: true });
  const zonaOpciones = h('div');
  const zonaEscala = h('div', { class: 'escala-temporal', role: 'group', 'aria-label': 'Escala temporal' });
  const zonaLeyenda = h('div');
  const zonaResumen = h('div');

  const radios = h('fieldset', { class: 'segmentado' }, h('legend', {}, 'Capa del mapa'),
    CAPAS.map((c) => h('label', {},
      h('input', { type: 'radio', name: 'capa-mapa', value: c.valor, checked: c.valor === preferencias.modo,
        onchange: () => { preferencias.modo = c.valor; pintarOpciones(); cargar(); } }),
      h('span', {}, icono(c.icono), c.texto))));

  anexar(contenedor, h('div', { class: 'vista-mapa' },
    h('aside', { class: 'mapa-panel', 'aria-label': 'Controles del mapa' },
      h('h1', {}, 'Mapa'),
      h('p', { class: 'subtitulo' }, 'Dónde se registraron los siniestros. Más registros no significa más riesgo: '
        + 'influyen la población y el tránsito. No es una predicción.'),
      radios, zonaOpciones,
      h('h2', {}, 'Escala temporal'), zonaEscala,
      h('h2', {}, 'Leyenda'), zonaLeyenda,
      h('h2', {}, 'Resumen'), zonaResumen,
      h('p', {}, h('a', { href: '#/explorador', onclick: (e) => { e.preventDefault(); ctx.irA('explorador'); } },
        'Ver estos registros en una tabla'))),
    h('div', { class: 'mapa-lienzo' }, divMapa, mensaje)));

  function avisar(texto) {
    mensaje.hidden = !texto;
    mensaje.textContent = texto || '';
  }

  function pintarOpciones() {
    if (preferencias.modo === 'localidad') {
      vaciar(zonaOpciones, h('fieldset', { class: 'segmentado' }, h('legend', {}, 'Medida'),
        [['siniestros', 'Siniestros'], ['tasa', 'Tasa por habitante']].map(([v, t]) => h('label', {},
          h('input', { type: 'radio', name: 'metrica-mapa', value: v, checked: v === preferencias.metrica,
            onchange: () => { preferencias.metrica = v; cargar(); } }), h('span', {}, t)))));
    } else if (preferencias.modo === 'cuadricula') {
      vaciar(zonaOpciones, h('fieldset', { class: 'segmentado' }, h('legend', {}, 'Tamaño de celda'),
        [250, 500, 1000].map((m) => h('label', {},
          h('input', { type: 'radio', name: 'celda-mapa', value: m, checked: m === preferencias.celda,
            onchange: () => { preferencias.celda = m; cargar(); } }), h('span', {}, m === 1000 ? '1 km' : `${m} m`)))));
    } else vaciar(zonaOpciones);
    zonaOpciones.style.marginTop = zonaOpciones.hasChildNodes() ? '.6rem' : '0';
  }

  function pintarEscala() {
    const anios = ctx.metadatos?.datos?.valores_para_filtros?.anios ?? [];
    const actual = estado.filtros().anio;
    const boton = (texto, valor) => h('button', {
      type: 'button', 'aria-pressed': String(valor ? actual.length === 1 && actual[0] === valor : !actual.length),
      onclick: () => estado.actualizar({ anio: valor ? [valor] : [] }),
    }, texto);
    vaciar(zonaEscala, boton('Todos', null), anios.map((a) => boton(String(a), String(a))));
  }

  function resumen(meta, extra = []) {
    const p = meta.periodo ?? {};
    vaciar(zonaResumen,
      h('p', { class: 'subtitulo' }, `Fuente: ${meta.fuente?.nombre ?? '—'}. Periodo: `
        + (p.inicio ? `${fmtFecha(p.inicio)} – ${fmtFecha(p.fin)}.` : 'sin registros.')),
      extra.length ? h('ul', { class: 'leyenda' }, extra.map((t) => h('li', {}, t))) : null,
      listaAvisos((meta.advertencias ?? []).filter((a) => /coordenada|recientes|límite oficial|no predice/i.test(a))));
  }

  function reemplazarCapa(nueva) {
    if (capa) mapa.removeLayer(capa);
    capa = nueva;
    if (capa) capa.addTo(mapa);
  }

  function limitePorZoom() {
    const z = mapa.getZoom();
    return z >= 15 ? 10000 : z >= 13 ? 5000 : 2500;
  }

  async function cargarLocalidades(p) {
    const r = await pedir('/localities/geojson', p);
    const meta = r.metadatos;
    const hayTasa = r.features.some((f) => f.properties.tasa_siniestros !== null && f.properties.tasa_siniestros !== undefined);
    const usarTasa = preferencias.metrica === 'tasa' && hayTasa;
    const valor = (f) => (usarTasa ? f.properties.tasa_siniestros : f.properties.siniestros) ?? 0;
    const limites = cortes(r.features.map(valor));
    // Leaflet inserta los textos de tooltip como HTML: se pasa un nodo para que los datos queden como texto.
    const tooltip = (f) => h('span', {}, `${f.properties.nombre}: ${usarTasa ? `${fmtDecimal(valor(f))} por 100.000 hab./año`
      : `${fmtNumero(f.properties.siniestros)} siniestros`}`);
    let nueva;
    if (meta.tipo_geometria === 'poligonos_oficiales') {
      nueva = L.geoJSON(r, {
        style: (f) => ({ fillColor: colorPara(valor(f), limites), color: '#ffffff', weight: 1.5, fillOpacity: 0.72 }),
        onEachFeature: (f, l) => l.bindTooltip(tooltip(f), { sticky: true }),
      });
    } else {
      const maximo = Math.max(1, ...r.features.map(valor));
      nueva = L.layerGroup(r.features.map((f) => {
        const [lon, lat] = f.geometry.coordinates;
        return L.circleMarker([lat, lon], {
          radius: 10 + 28 * Math.sqrt(valor(f) / maximo), fillColor: colorPara(valor(f), limites), color: '#ffffff',
          weight: 2, fillOpacity: 0.8,
        }).bindTooltip(tooltip(f));
      }));
    }
    reemplazarCapa(nueva);
    if (primeraVista && meta.tipo_geometria === 'poligonos_oficiales' && nueva.getBounds?.().isValid()) mapa.fitBounds(nueva.getBounds());
    vaciar(zonaLeyenda,
      leyendaClases(limites, usarTasa ? 'por 100.000 hab./año' : 'siniestros', usarTasa ? fmtDecimal : fmtNumero),
      meta.tipo_geometria === 'poligonos_oficiales' ? null
        : h('p', { class: 'subtitulo' }, 'Círculos ubicados en el promedio de las coordenadas de cada localidad: no son límites oficiales. '
          + 'El tamaño y el color indican la cantidad.'),
      preferencias.metrica === 'tasa' && !hayTasa
        ? h('p', { class: 'subtitulo' }, 'Tasa no disponible (falta población oficial); se muestran conteos.') : null);
    resumen(meta, [
      meta.sin_localidad ? `${fmtNumero(meta.sin_localidad)} siniestros sin localidad reconocida no se dibujan.` : null,
    ].filter(Boolean));
  }

  async function cargarPuntos(p, calor) {
    const r = await pedir('/accidents/geojson', { ...p, bbox: mapa.getBounds().toBBoxString(), limite: limitePorZoom() });
    const meta = r.metadatos;
    if (calor) {
      reemplazarCapa(L.heatLayer(r.features.map((f) => [f.geometry.coordinates[1], f.geometry.coordinates[0], 1]),
        { radius: 20, blur: 18, maxZoom: 15, minOpacity: 0.35, gradient: GRADIENTE_CALOR }));
      vaciar(zonaLeyenda, h('div', { class: 'muestra muestra--degradado', 'aria-hidden': 'true' }),
        h('p', { class: 'subtitulo' }, 'De menos (claro) a más (oscuro) registros cercanos. La intensidad es relativa a lo visible.'));
    } else {
      const grupo = L.markerClusterGroup({
        chunkedLoading: true, showCoverageOnHover: false, maxClusterRadius: 50,
        iconCreateFunction: (c) => {
          const n = c.getChildCount();
          const t = n < 50 ? 'p' : n < 500 ? 'm' : 'g';
          return L.divIcon({ html: `<span>${n}</span>`, className: `cluster cluster--${t}`, iconSize: L.point(42, 42) });
        },
      });
      grupo.addLayers(r.features.map((f) => {
        const [lon, lat] = f.geometry.coordinates;
        return L.circleMarker([lat, lon], { radius: 7, color: '#ffffff', weight: 1.5, fillOpacity: 0.95,
          fillColor: COLOR_GRAVEDAD[f.properties.gravedad] ?? COLOR_GRAVEDAD['Sin dato'] })
          .bindPopup(popupSiniestro(f.properties));
      }));
      reemplazarCapa(grupo);
      const muestra = (color) => { const m = h('span', { class: 'muestra muestra--circulo', 'aria-hidden': 'true' }); m.style.background = color; return m; };
      vaciar(zonaLeyenda, h('ul', { class: 'leyenda' },
        Object.entries(COLOR_GRAVEDAD).filter(([g]) => g !== 'Sin dato').map(([g, c]) => h('li', {}, muestra(c), g)),
        h('li', {}, h('span', { class: 'muestra muestra--circulo cluster--m', 'aria-hidden': 'true' }), 'Grupo de registros (el número indica cuántos)')),
      h('p', { class: 'subtitulo' }, 'Pulse un punto para ver su fecha, hora, gravedad y clase.'));
    }
    resumen(meta, [
      `${fmtNumero(meta.devueltos)} de ${fmtNumero(meta.con_coordenada_valida)} registros con ubicación en esta vista.`,
      meta.sin_coordenada_valida ? `${fmtNumero(meta.sin_coordenada_valida)} registros sin ubicación válida no aparecen.` : null,
      meta.truncado ? 'Hay más registros: acerque el mapa o agregue filtros para verlos.' : null,
    ].filter(Boolean));
  }

  async function cargarCuadricula(p) {
    const r = await pedir('/analytics/concentration', { ...p, bbox: mapa.getBounds().toBBoxString(), tamano_celda_m: preferencias.celda });
    const d = r.datos;
    const limites = cortes(d.celdas.map((c) => c.conteo));
    reemplazarCapa(L.layerGroup(d.celdas.map((c) => L.rectangle([[c.lat_min, c.lon_min], [c.lat_max, c.lon_max]], {
      stroke: false, fillColor: colorPara(c.conteo, limites), fillOpacity: 0.72,
    }).bindTooltip(h('span', {}, `${fmtNumero(c.conteo)} registros en esta celda`)))));
    vaciar(zonaLeyenda, leyendaClases(limites, 'registros por celda'),
      h('p', { class: 'subtitulo' }, `Celdas de ${preferencias.celda === 1000 ? '1 km' : `${preferencias.celda} m`} de lado. Solo se envían conteos por celda.`));
    resumen({ ...r, advertencias: r.advertencias }, [
      `${fmtNumero(d.celdas.length)} celdas con registros en la vista.`,
      d.sin_coordenada_valida ? `${fmtNumero(d.sin_coordenada_valida)} registros sin ubicación válida no se incluyen.` : null,
    ].filter(Boolean));
  }

  async function cargar() {
    pintarEscala();
    if (!mapa) return;
    avisar('Cargando…');
    const p = estado.parametros();
    try {
      if (preferencias.modo === 'localidad') await cargarLocalidades(p);
      else if (preferencias.modo === 'cuadricula') await cargarCuadricula(p);
      else await cargarPuntos(p, preferencias.modo === 'calor');
      primeraVista = false;
      avisar(null);
    } catch (error) {
      if (esCancelacion(error)) return;
      avisar(error.message || 'No se pudieron cargar los datos del mapa.');
    }
  }

  pintarOpciones();
  pintarEscala();
  const alMover = retrasar(() => { if (preferencias.modo !== 'localidad') cargar(); }, 350);
  const desuscribir = estado.suscribir(cargar);

  (async () => {
    try {
      L = await cargarLeaflet();
    } catch (error) {
      if (!(error instanceof LibreriaFaltante)) throw error;
      vaciar(divMapa.parentElement, h('div', { class: 'estado estado--error', role: 'alert' },
        h('p', {}, h('strong', {}, 'El mapa no está disponible.')), h('p', {}, error.message)));
      return;
    }
    if (!divMapa.isConnected) return;  // el usuario ya cambió de vista
    mapa = L.map(divMapa, { center: CENTRO, zoom: 11, minZoom: 10, maxZoom: 18, maxBounds: LIMITES, preferCanvas: true });
    L.tileLayer(OSM, { maxZoom: 19, attribution: ATRIBUCION }).addTo(mapa);
    L.control.scale({ imperial: false }).addTo(mapa);
    mapa.on('moveend', alMover);
    cargar();
  })();

  return () => {
    desuscribir();
    pedir.cancelar();
    if (mapa) { mapa.off(); mapa.remove(); }
  };
}
