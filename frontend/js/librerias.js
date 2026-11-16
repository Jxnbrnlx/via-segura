// Carga bajo demanda de las librerías de terceros servidas desde /static/vendor (CSP 'self', sin CDN).
// Si faltan, se informa cómo instalarlas en lugar de romper la página.

const BASE = '/static/vendor';
const promesas = new Map();

export class LibreriaFaltante extends Error {
  constructor(nombre) {
    super(`No se encontró la librería ${nombre}. Un administrador debe ejecutar una vez: `
      + 'python scripts/descargar_librerias.py');
    this.nombre = nombre;
  }
}

function cargarScript(ruta, nombre) {
  if (!promesas.has(ruta)) {
    promesas.set(ruta, new Promise((resolver, rechazar) => {
      const s = document.createElement('script');
      s.src = `${BASE}/${ruta}`;
      s.onload = resolver;
      s.onerror = () => { promesas.delete(ruta); s.remove(); rechazar(new LibreriaFaltante(nombre)); };
      document.head.append(s);
    }));
  }
  return promesas.get(ruta);
}

function cargarEstilo(ruta) {
  if (document.querySelector(`link[data-vendor="${ruta}"]`)) return;
  const l = document.createElement('link');
  l.rel = 'stylesheet';
  l.href = `${BASE}/${ruta}`;
  l.dataset.vendor = ruta;
  document.head.append(l);
}

let chartConfigurado = false;

export async function cargarChart() {
  if (!window.Chart) await cargarScript('chart.js/chart.umd.js', 'Chart.js');
  const { Chart } = window;
  if (!chartConfigurado && Chart?.defaults) {
    Chart.defaults.locale = 'es-CO';
    Chart.defaults.font.family = '"Segoe UI", system-ui, -apple-system, Roboto, Arial, sans-serif';
    Chart.defaults.font.size = 13;
    Chart.defaults.color = '#4b5872';
    Chart.defaults.borderColor = '#e6e9f3';
    Chart.defaults.maintainAspectRatio = false;
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
    Chart.defaults.plugins.legend.position = 'bottom';
    Chart.defaults.plugins.tooltip.backgroundColor = '#0f1f3d';
    Chart.defaults.plugins.tooltip.padding = 10;
    Chart.defaults.plugins.tooltip.cornerRadius = 10;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) Chart.defaults.animation = false;
    chartConfigurado = true;
  }
  return Chart;
}

export async function cargarLeaflet() {
  cargarEstilo('leaflet/leaflet.css');
  cargarEstilo('leaflet.markercluster/MarkerCluster.css');
  if (!window.L) await cargarScript('leaflet/leaflet.js', 'Leaflet');
  if (!window.L.markerClusterGroup) await cargarScript('leaflet.markercluster/leaflet.markercluster.js', 'Leaflet.markercluster');
  if (!window.L.heatLayer) await cargarScript('leaflet.heat/leaflet-heat.js', 'Leaflet.heat');
  return window.L;
}
