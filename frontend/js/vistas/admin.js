// Administración: inicio de sesión, importación de archivos en dos pasos (previsualizar → confirmar),
// sincronización con ArcGIS e historial. Todo pasa por la API con el token de sesión (sessionStorage).
import { obtener } from '../api.js';
import { cajaError, cargando, listaAvisos } from '../componentes/carga.js';
import { alCambiar, cerrarSesion, iniciarSesion, pedirAdmin, sesion } from '../sesion.js';
import { anunciar, fmtFecha, fmtFechaHora, fmtNumero, h, icono, vaciar } from '../util.js';

const TIPOS = [
  { valor: 'siniestros', texto: 'Siniestros', ayuda: 'Hoja principal del anuario (un registro por siniestro). Impórtela primero.' },
  { valor: 'actores', texto: 'Actores viales (personas)', ayuda: 'Se enlazan con los siniestros ya importados de la misma fuente.' },
  { valor: 'vehiculos', texto: 'Vehículos', ayuda: 'Se enlazan con los siniestros ya importados de la misma fuente.' },
  { valor: 'poblacion', texto: 'Población por localidad', ayuda: 'Denominador oficial para las tasas por habitante.' },
  { valor: 'localidades', texto: 'Polígonos de localidades', ayuda: 'GeoJSON oficial con los límites de las 20 localidades.' },
];
const ESTADOS = {
  previsualizada: ['Previsualizada', 'info'], en_proceso: ['En proceso', 'proceso'], completada: ['Completada', 'ok'],
  fallida: ['Fallida', 'error'], cancelada: ['Cancelada', 'neutro'], pendiente: ['Pendiente', 'neutro'],
};
const FINALES = new Set(['completada', 'fallida', 'cancelada']);

const pildoraEstado = (e) => {
  const [texto, clase] = ESTADOS[e] ?? [e, 'neutro'];
  return h('span', { class: `estado-carga estado-carga--${clase}` }, texto);
};
const textoError = (e) => (typeof e === 'string' ? e : e?.mensaje ?? e?.motivo ?? JSON.stringify(e));

export function montar(contenedor) {
  const raiz = h('div', { class: 'admin' });
  contenedor.append(raiz);
  const relojes = new Set();
  let vigente = true;
  let pestanaActual = 'importar';

  const esperar = (fn, ms) => {
    const id = setTimeout(() => { relojes.delete(id); if (vigente) fn(); }, ms);
    relojes.add(id);
  };
  const pararRelojes = () => { relojes.forEach(clearTimeout); relojes.clear(); };

  const quitarOyente = alCambiar(() => { pararRelojes(); pintar(); });
  pintar();
  return () => { vigente = false; pararRelojes(); quitarOyente(); };

  function pintar() {
    if (sesion()) panel(); else login();
  }

  // ================================================================ inicio de sesión
  function login(mensajePrevio) {
    const error = h('div', { role: 'alert', class: 'form-error', hidden: true });
    const correo = h('input', { id: 'adm-correo', type: 'email', required: true, autocomplete: 'username', maxlength: 254 });
    const clave = h('input', { id: 'adm-clave', type: 'password', required: true, autocomplete: 'current-password', maxlength: 200 });
    const enviar = h('button', { class: 'boton boton--ancho', type: 'submit' }, 'Entrar');
    const form = h('form', { class: 'tarjeta-login', 'aria-labelledby': 'tit-login', novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        error.hidden = true;
        if (!correo.value.trim() || !clave.value) {
          vaciar(error, 'Escriba el correo y la contraseña.');
          error.hidden = false;
          return;
        }
        enviar.disabled = true;
        vaciar(enviar, 'Entrando…');
        try {
          await iniciarSesion(correo.value.trim(), clave.value);
          clave.value = '';
          anunciar('Sesión iniciada');
        } catch (err) {
          clave.value = '';
          vaciar(error, err.estado === 422 ? 'Revise el formato del correo.' : err.message);
          error.hidden = false;
          enviar.disabled = false;
          vaciar(enviar, 'Entrar');
          clave.focus();
        }
      } },
    h('span', { class: 'tarjeta-login__icono' }, icono('candado')),
    h('h1', { id: 'tit-login' }, 'Administración'),
    h('p', { class: 'suave' }, 'Solo para administradores: cargar archivos, sincronizar ArcGIS y revisar el historial. '
      + 'La consulta de datos no necesita cuenta.'),
    mensajePrevio ? h('p', { class: 'aviso' }, mensajePrevio) : null,
    error,
    h('div', { class: 'campo' }, h('label', { for: 'adm-correo' }, 'Correo'), correo),
    h('div', { class: 'campo' }, h('label', { for: 'adm-clave' }, 'Contraseña'), clave),
    enviar,
    h('p', { class: 'suave pequeno' }, '¿No tiene cuenta? Se crea en el servidor con: python scripts/crear_admin.py'));
    vaciar(raiz, form);
    correo.focus();
  }

  // ================================================================ panel
  function panel() {
    const s = sesion();
    const pestanas = [
      ['importar', 'Importar archivo', 'subir'],
      ['arcgis', 'Sincronizar ArcGIS', 'sincronizar'],
      ['historial', 'Historial', 'reloj'],
    ];
    const zona = h('div', { class: 'admin__zona', role: 'tabpanel', id: 'admin-panel', tabindex: '-1' });
    const botones = pestanas.map(([clave, texto, ic]) => h('button', {
      type: 'button', role: 'tab', id: `tab-${clave}`, 'aria-controls': 'admin-panel',
      'aria-selected': String(clave === pestanaActual), tabindex: clave === pestanaActual ? '0' : '-1',
      onclick: () => elegir(clave),
    }, icono(ic), texto));
    const lista = h('div', { class: 'admin__pestanas', role: 'tablist', 'aria-label': 'Tareas de administración',
      onkeydown: (e) => {
        const i = pestanas.findIndex(([c]) => c === pestanaActual);
        const salto = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
        if (salto) { e.preventDefault(); elegir(pestanas[(i + salto + pestanas.length) % pestanas.length][0], true); }
      } }, botones);

    function elegir(clave, enfocar = false) {
      pararRelojes();
      pestanaActual = clave;
      botones.forEach((b, i) => {
        const activo = pestanas[i][0] === clave;
        b.setAttribute('aria-selected', String(activo));
        b.tabIndex = activo ? 0 : -1;
        if (activo && enfocar) b.focus();
      });
      zona.setAttribute('aria-labelledby', `tab-${clave}`);
      vaciar(zona);
      ({ importar: vistaImportar, arcgis: vistaArcgis, historial: vistaHistorial })[clave](zona);
    }

    vaciar(raiz,
      h('div', { class: 'cabecera-vista admin__cabecera' },
        h('div', {}, h('h1', {}, 'Administración'),
          h('p', { class: 'suave' }, 'Sesión: ', h('strong', {}, s.correo), ` · vence ${fmtFechaHora(s.expira)}`)),
        h('button', { type: 'button', class: 'boton boton--secundario', onclick: () => { cerrarSesion(); anunciar('Sesión cerrada'); } },
          icono('salir'), 'Cerrar sesión')),
      lista, zona);
    elegir(pestanaActual);
  }

  // Si la sesión venció a mitad de una tarea, vuelve al formulario con un aviso.
  function manejarError(zona, error, reintentar) {
    if (error.estado === 401) { login('Su sesión terminó. Inicie sesión de nuevo.'); return; }
    vaciar(zona, cajaError(error, reintentar));
  }

  // ================================================================ importar
  async function vistaImportar(zona) {
    vaciar(zona, cargando('Cargando mapeos…'));
    let mapeos;
    try {
      mapeos = (await pedirAdmin('/mappings')).datos;
    } catch (error) { manejarError(zona, error, () => vistaImportar(zona)); return; }
    if (!vigente) return;
    paso1(zona, mapeos);
  }

  function pasos(actual) {
    return h('ol', { class: 'pasos', 'aria-label': 'Pasos de la importación' },
      ['Elegir archivo', 'Revisar', 'Confirmar'].map((t, i) => h('li', {
        class: i + 1 === actual ? 'pasos__actual' : i + 1 < actual ? 'pasos__hecho' : null,
        'aria-current': i + 1 === actual ? 'step' : null }, h('span', {}, String(i + 1)), t)));
  }

  function paso1(zona, mapeos, previo = {}) {
    const error = h('div', { role: 'alert', class: 'form-error', hidden: true });
    const ayudaTipo = h('p', { class: 'suave pequeno', id: 'ayuda-tipo' });
    const notaMapeo = h('p', { class: 'suave pequeno', id: 'nota-mapeo' });
    const tipo = h('select', { id: 'imp-tipo', 'aria-describedby': 'ayuda-tipo' },
      TIPOS.map((t) => h('option', { value: t.valor, selected: t.valor === (previo.tipo ?? 'siniestros') }, t.texto)));
    const mapeo = h('select', { id: 'imp-mapeo', 'aria-describedby': 'nota-mapeo' });
    const campoMapeo = h('div', { class: 'campo' }, h('label', { for: 'imp-mapeo' }, 'Formato del archivo (mapeo de columnas)'), mapeo, notaMapeo);
    const archivo = h('input', { id: 'imp-archivo', type: 'file', accept: '.csv,.xlsx,.geojson,.json', required: true });
    const enviar = h('button', { class: 'boton', type: 'submit' }, icono('subir'), 'Subir y previsualizar');

    function actualizarTipo() {
      const t = TIPOS.find((x) => x.valor === tipo.value);
      vaciar(ayudaTipo, t.ayuda);
      const aptos = mapeos.filter((m) => m.hojas[tipo.value]);
      campoMapeo.hidden = tipo.value === 'localidades';
      vaciar(mapeo, aptos.map((m) => h('option', { value: m.codigo, selected: m.codigo === previo.mapeo }, m.descripcion || m.codigo)));
      if (!aptos.length && tipo.value !== 'localidades') vaciar(mapeo, h('option', { value: '' }, 'No hay mapeos para este tipo'));
      actualizarNota();
    }
    function actualizarNota() {
      const m = mapeos.find((x) => x.codigo === mapeo.value);
      vaciar(notaMapeo, m ? `Fuente: ${m.fuente}. ${m.verificado ?? ''}` : '');
    }
    tipo.addEventListener('change', actualizarTipo);
    mapeo.addEventListener('change', actualizarNota);

    const form = h('form', { class: 'seccion formulario', novalidate: true, onsubmit: async (e) => {
      e.preventDefault();
      error.hidden = true;
      const fichero = archivo.files[0];
      if (!fichero) { vaciar(error, 'Elija un archivo.'); error.hidden = false; archivo.focus(); return; }
      enviar.disabled = true;
      vaciar(enviar, 'Subiendo y revisando…');
      const opciones = { archivo: fichero, tipo: tipo.value, mapeo: tipo.value === 'localidades' ? null : mapeo.value };
      try {
        const pv = await previsualizar(opciones);
        if (vigente) paso2(zona, mapeos, opciones, pv);
      } catch (err) {
        if (err.estado === 401) { login('Su sesión terminó. Inicie sesión de nuevo.'); return; }
        vaciar(error, err.message);
        error.hidden = false;
        enviar.disabled = false;
        vaciar(enviar, icono('subir'), 'Subir y previsualizar');
      }
    } },
    h('h2', {}, 'Importar un archivo oficial'),
    h('p', { class: 'suave' }, 'Primero se revisa el archivo y se muestra qué se va a cargar. Nada se guarda en la base '
      + 'hasta que usted confirme. Las columnas con datos personales (placa, fecha de nacimiento, código de la persona) '
      + 'se descartan automáticamente.'),
    error,
    h('div', { class: 'rejilla-campos' },
      h('div', { class: 'campo' }, h('label', { for: 'imp-tipo' }, 'Qué contiene el archivo'), tipo, ayudaTipo),
      campoMapeo),
    h('div', { class: 'campo' }, h('label', { for: 'imp-archivo' }, 'Archivo (.csv, .xlsx o .geojson)'), archivo),
    h('div', { class: 'acciones' }, enviar));

    vaciar(zona, pasos(1), form);
    actualizarTipo();
  }

  async function previsualizar({ archivo, tipo, mapeo, hoja, columnas }) {
    const datos = new FormData();
    datos.append('archivo', archivo, archivo.name);
    datos.append('tipo', tipo);
    if (mapeo) datos.append('mapeo', mapeo);
    if (hoja) datos.append('hoja', hoja);
    if (columnas && Object.keys(columnas).length) datos.append('columnas', JSON.stringify(columnas));
    return (await pedirAdmin('/imports', { metodo: 'POST', formulario: datos })).datos;
  }

  function paso2(zona, mapeos, opciones, pv) {
    const v = pv.validacion ?? {};
    const error = h('div', { role: 'alert', class: 'form-error', hidden: true });
    const visibles = pv.columnas.filter((c) => !c.personal).map((c) => c.nombre);
    const definicion = mapeos.find((m) => m.codigo === opciones.mapeo)?.hojas?.[pv.tipo]?.campos ?? {};
    const campos = [...new Set([...Object.keys(definicion), ...Object.keys(pv.mapeo ?? {}), ...pv.faltantes_obligatorios])];
    const selectores = new Map();

    async function rehacer(cambios) {
      error.hidden = true;
      try {
        await pedirAdmin(`/imports/${pv.importacion_id}/cancel`, { metodo: 'POST' }).catch(() => null);
        const nuevas = { ...opciones, ...cambios };
        vaciar(zona, pasos(2), cargando('Revisando de nuevo…'));
        const nuevo = await previsualizar(nuevas);
        if (vigente) paso2(zona, mapeos, nuevas, nuevo);
      } catch (err) {
        if (err.estado === 401) { login('Su sesión terminó. Inicie sesión de nuevo.'); return; }
        paso2(zona, mapeos, opciones, pv);
        const caja = zona.querySelector('.form-error');
        vaciar(caja, err.message);
        caja.hidden = false;
      }
    }

    const filaMapeo = (campo) => {
      const actual = pv.mapeo?.[campo] ?? '';
      const falta = pv.faltantes_obligatorios.includes(campo);
      const sel = h('select', { id: `map-${campo}`, 'aria-describedby': falta ? `falta-${campo}` : null },
        actual ? null : h('option', { value: '' }, '— sin columna —'),
        visibles.map((c) => h('option', { value: c, selected: c === actual }, c)));
      selectores.set(campo, sel);
      return h('tr', { class: falta ? 'fila-falta' : null },
        h('th', { scope: 'row' }, h('label', { for: `map-${campo}` }, campo)),
        h('td', {}, sel),
        h('td', {}, falta ? h('span', { id: `falta-${campo}`, class: 'marca-si-no marca-si-no--no' }, icono('alerta'), 'Obligatorio: falta')
          : actual ? h('span', { class: 'marca-si-no marca-si-no--si' }, 'Reconocida') : h('span', { class: 'suave' }, 'Quedará vacío')));
    };

    const motivos = Object.entries(v.motivos ?? {});
    const esGeo = pv.tipo === 'localidades';

    vaciar(zona, pasos(2),
      h('section', { class: 'seccion' },
        h('h2', {}, 'Revise antes de confirmar'),
        error,
        h('div', { class: 'resumen-carga' },
          [['Archivo', pv.archivo], ['Hoja', pv.hoja ?? '—'], [esGeo ? 'Polígonos' : 'Filas (aprox.)', fmtNumero(pv.filas_estimadas)],
            ['Revisadas en la muestra', fmtNumero(v.revisadas)], ['Válidas', fmtNumero(v.validas)], ['Rechazadas', fmtNumero(v.rechazadas)]]
            .map(([e, val]) => h('div', { class: 'resumen-carga__dato' }, h('span', {}, e), h('strong', {}, val)))),
        v.nota ? h('p', { class: 'suave pequeno' }, v.nota) : null,
        listaAvisos(pv.advertencias),
        pv.hojas?.length > 1 ? h('div', { class: 'campo campo--en-linea' },
          h('label', { for: 'imp-hoja' }, 'Hoja del libro'),
          h('select', { id: 'imp-hoja', onchange: (e) => rehacer({ hoja: e.target.value }) },
            pv.hojas.map((x) => h('option', { value: x, selected: x === pv.hoja }, x)))) : null),

      esGeo ? h('section', { class: 'seccion' },
        h('h3', {}, `Localidades encontradas (${pv.filas_muestra.length} de 20)`),
        h('p', {}, pv.filas_muestra.map((f) => f.localidad).join(', ') || '—'),
        v.localidades_faltantes?.length ? h('p', { class: 'aviso' }, `Faltan: ${v.localidades_faltantes.join(', ')}`) : null)
        : [
          h('section', { class: 'seccion' },
            h('h3', {}, 'Columnas del archivo → campos de VÍA SEGURA'),
            h('p', { class: 'suave' }, 'Se reconocieron automáticamente con el mapeo elegido. Si una columna se llama distinto '
              + 'en su archivo, elíjala aquí y vuelva a revisar.'),
            h('div', { class: 'tabla-contenedor' }, h('table', { class: 'tabla tabla--compacta' },
              h('caption', { class: 'solo-lectores' }, 'Mapeo de columnas'),
              h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, 'Campo'), h('th', { scope: 'col' }, 'Columna del archivo'),
                h('th', { scope: 'col' }, 'Estado'))),
              h('tbody', {}, campos.map(filaMapeo)))),
            h('div', { class: 'acciones' }, h('button', { type: 'button', class: 'boton boton--secundario', onclick: () => {
              const cambios = {};
              selectores.forEach((sel, campo) => { if (sel.value && sel.value !== (pv.mapeo?.[campo] ?? '')) cambios[campo] = sel.value; });
              if (!Object.keys(cambios).length) {
                vaciar(error, 'No cambió ninguna columna.');
                error.hidden = false;
                return;
              }
              rehacer({ columnas: { ...(opciones.columnas ?? {}), ...cambios } });
            } }, 'Aplicar cambios y volver a revisar')),
            pv.columnas_personales_omitidas?.length ? h('p', { class: 'nota-privacidad' }, icono('candado'),
              `Columnas omitidas por privacidad (no se leen ni se guardan): ${pv.columnas_personales_omitidas.join(', ')}.`) : null,
            pv.columnas_no_usadas?.length ? h('p', { class: 'suave pequeno' },
              `Columnas que no se usan: ${pv.columnas_no_usadas.join(', ')}.`) : null),

          motivos.length || v.ejemplos_error?.length ? h('section', { class: 'seccion' },
            h('h3', {}, 'Observaciones en la muestra'),
            motivos.length ? h('table', { class: 'tabla tabla--compacta' },
              h('caption', { class: 'solo-lectores' }, 'Observaciones por tipo'),
              h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, 'Observación'), h('th', { scope: 'col', class: 'num' }, 'Filas'))),
              h('tbody', {}, motivos.sort((a, b) => b[1] - a[1]).map(([m, n]) => h('tr', {},
                h('th', { scope: 'row' }, m.replaceAll('_', ' ')), h('td', { class: 'num' }, fmtNumero(n)))))) : null,
            v.ejemplos_error?.length ? h('details', {}, h('summary', {}, 'Ver ejemplos de filas rechazadas'),
              h('ul', {}, v.ejemplos_error.map((e) => h('li', {}, textoError(e))))) : null) : null,

          pv.filas_muestra?.length ? h('section', { class: 'seccion' },
            h('h3', {}, 'Primeras filas del archivo'),
            h('div', { class: 'tabla-contenedor' }, h('table', { class: 'tabla tabla--compacta tabla--muestra' },
              h('caption', { class: 'solo-lectores' }, 'Muestra del archivo'),
              h('thead', {}, h('tr', {}, visibles.map((c) => h('th', { scope: 'col' }, c)))),
              h('tbody', {}, pv.filas_muestra.slice(0, 8).map((f) => h('tr', {}, visibles.map((c) => h('td', {}, f[c] ?? '')))))))) : null,
        ],

      paso3(zona, mapeos, opciones, pv));
  }

  function paso3(zona, mapeos, opciones, pv) {
    const error = h('div', { role: 'alert', class: 'form-error', hidden: true });
    const url = h('input', { id: 'conf-url', type: 'url', maxlength: 500, placeholder: 'https://…' });
    const publicacion = h('input', { id: 'conf-pub', type: 'date' });
    const descarga = h('input', { id: 'conf-desc', type: 'date' });
    const confirmar = h('button', { type: 'submit', class: 'boton', disabled: !pv.puede_confirmar }, icono('ok'), 'Confirmar importación');
    const motivo = pv.puede_confirmar ? null
      : pv.faltantes_obligatorios.length ? 'No se puede confirmar: faltan columnas obligatorias (elíjalas arriba).'
        : 'No se puede confirmar: ninguna fila de la muestra es válida. Revise el tipo, el mapeo o el archivo.';

    return h('form', { class: 'seccion formulario', novalidate: true, onsubmit: async (e) => {
      e.preventDefault();
      error.hidden = true;
      if (url.value && !/^https?:\/\/\S+$/.test(url.value)) {
        vaciar(error, 'La dirección debe empezar por http:// o https://');
        error.hidden = false;
        return;
      }
      confirmar.disabled = true;
      vaciar(confirmar, 'Enviando…');
      const cuerpo = {};
      if (url.value) cuerpo.url = url.value.trim();
      if (publicacion.value) cuerpo.fecha_publicacion = publicacion.value;
      if (descarga.value) cuerpo.fecha_descarga = descarga.value;
      try {
        await pedirAdmin(`/imports/${pv.importacion_id}/confirm`, { metodo: 'POST', json: cuerpo });
        seguirImportacion(zona, mapeos, pv.importacion_id);
      } catch (err) {
        if (err.estado === 401) { login('Su sesión terminó. Inicie sesión de nuevo.'); return; }
        vaciar(error, err.message);
        error.hidden = false;
        confirmar.disabled = false;
        vaciar(confirmar, icono('ok'), 'Confirmar importación');
      }
    } },
    h('h2', {}, 'Confirmar'),
    h('p', { class: 'suave' }, 'Opcional: datos de la publicación oficial, para la ficha de la fuente.'),
    error,
    h('div', { class: 'rejilla-campos rejilla-campos--3' },
      h('div', { class: 'campo' }, h('label', { for: 'conf-url' }, 'Dirección de la publicación'), url),
      h('div', { class: 'campo' }, h('label', { for: 'conf-pub' }, 'Fecha de publicación'), publicacion),
      h('div', { class: 'campo' }, h('label', { for: 'conf-desc' }, 'Fecha de descarga'), descarga)),
    motivo ? h('p', { class: 'aviso' }, motivo) : null,
    h('p', { class: 'suave pequeno' }, 'Si un registro ya existe en la misma fuente (mismo código), se actualiza; no se duplica.'),
    h('div', { class: 'acciones' }, confirmar,
      h('button', { type: 'button', class: 'boton boton--secundario', onclick: async () => {
        await pedirAdmin(`/imports/${pv.importacion_id}/cancel`, { metodo: 'POST' }).catch(() => null);
        anunciar('Importación cancelada');
        paso1(zona, mapeos, opciones);
      } }, 'Cancelar')));
  }

  function seguirImportacion(zona, mapeos, id) {
    const estadoZona = h('div', { role: 'status', 'aria-live': 'polite' }, cargando('Procesando… con archivos grandes puede tardar varios minutos. Puede salir de esta pantalla: el proceso sigue en el servidor.'));
    vaciar(zona, pasos(3), h('section', { class: 'seccion' }, h('h2', {}, `Importación n.º ${id}`), estadoZona));
    const consultar = async () => {
      let imp;
      try {
        imp = (await pedirAdmin(`/imports/${id}`)).datos;
      } catch (err) {
        if (err.estado === 401) { login('Su sesión terminó. El proceso sigue en el servidor; revise el historial.'); return; }
        esperar(consultar, 5000);
        return;
      }
      if (!vigente) return;
      if (!FINALES.has(imp.estado)) {
        vaciar(estadoZona, h('p', {}, pildoraEstado(imp.estado), ` Filas revisadas hasta ahora: ${fmtNumero(imp.filas_revisadas)}.`));
        esperar(consultar, 2500);
        return;
      }
      const res = imp.resumen?.resultado ?? {};
      vaciar(estadoZona, detalleImportacion(imp, res),
        h('div', { class: 'acciones' },
          h('button', { type: 'button', class: 'boton', onclick: () => paso1(zona, mapeos) }, 'Importar otro archivo'),
          imp.estado === 'completada' ? h('button', { type: 'button', class: 'boton boton--secundario', onclick: () => {
            window.location.hash = '#/tablero';
            window.location.reload();
          } }, 'Ver los datos') : null));
      anunciar(`Importación ${ESTADOS[imp.estado]?.[0] ?? imp.estado}`);
    };
    consultar();
  }

  function detalleImportacion(imp, res = imp.resumen?.resultado ?? {}) {
    const errores = imp.errores ?? [];
    return h('div', { class: 'detalle-carga' },
      h('p', {}, pildoraEstado(imp.estado), ' ', imp.tipo === 'arcgis' ? `ArcGIS · ${imp.modo}` : `${imp.modo} · ${imp.archivo ?? ''}`),
      h('dl', { class: 'lista-datos' },
        h('dt', {}, 'Inicio'), h('dd', {}, fmtFechaHora(imp.iniciada_en)),
        h('dt', {}, 'Fin'), h('dd', {}, fmtFechaHora(imp.finalizada_en)),
        h('dt', {}, 'Filas revisadas'), h('dd', {}, fmtNumero(imp.filas_revisadas)),
        h('dt', {}, 'Válidas'), h('dd', {}, fmtNumero(imp.filas_validas)),
        h('dt', {}, 'Rechazadas'), h('dd', {}, fmtNumero(imp.filas_rechazadas)),
        res.nuevos !== undefined ? [h('dt', {}, 'Nuevos / actualizados'), h('dd', {}, `${fmtNumero(res.nuevos)} / ${fmtNumero(res.actualizados)}`)] : null,
        h('dt', {}, 'Fechas de los eventos'), h('dd', {}, imp.fecha_min_evento ? `${fmtFecha(imp.fecha_min_evento)} – ${fmtFecha(imp.fecha_max_evento)}` : '—')),
      errores.length ? h('details', { open: imp.estado === 'fallida' }, h('summary', {}, `Errores registrados (${fmtNumero(res.errores_totales ?? errores.length)})`),
        h('ul', {}, errores.slice(0, 50).map((e) => h('li', {}, textoError(e))))) : null);
  }

  // ================================================================ ArcGIS
  async function vistaArcgis(zona) {
    vaciar(zona, cargando());
    let fuentes;
    try {
      fuentes = (await obtener('/sources')).datos;
    } catch (error) { manejarError(zona, error, () => vistaArcgis(zona)); return; }
    if (!vigente) return;
    const f = fuentes.find((x) => x.codigo === 'arcgis_simur_accidentalidad') ?? {};
    const error = h('div', { role: 'alert', class: 'form-error', hidden: true });
    const progreso = h('div', { role: 'status', 'aria-live': 'polite' });
    const desde = h('input', { id: 'sync-desde', type: 'number', min: 2001, max: 2100, inputmode: 'numeric', placeholder: 'Ej.: 2015' });
    const iniciar = h('button', { class: 'boton', type: 'submit' }, icono('sincronizar'), 'Iniciar sincronización');
    const opcion = (valor, texto, nota, marcado) => h('label', { class: 'opcion-tarjeta' },
      h('input', { type: 'radio', name: 'sync-modo', value: valor, checked: marcado }),
      h('span', {}, h('strong', {}, texto), h('span', { class: 'suave' }, nota)));

    const form = h('form', { class: 'seccion formulario', novalidate: true, onsubmit: async (e) => {
      e.preventDefault();
      error.hidden = true;
      const modo = form.querySelector('input[name=sync-modo]:checked').value;
      const cuerpo = { modo };
      if (desde.value) {
        const n = Number(desde.value);
        if (!Number.isInteger(n) || n < 2001 || n > 2100) {
          vaciar(error, 'El año debe estar entre 2001 y 2100.');
          error.hidden = false;
          return;
        }
        cuerpo.desde_anio = n;
      }
      iniciar.disabled = true;
      try {
        const r = await pedirAdmin('/sync/arcgis', { metodo: 'POST', json: cuerpo });
        vaciar(progreso, h('p', { class: 'aviso aviso--ok' }, r.datos.mensaje));
        esperar(() => seguirSync(progreso, iniciar), 1500);
      } catch (err) {
        if (err.estado === 401) { login('Su sesión terminó. Inicie sesión de nuevo.'); return; }
        vaciar(error, err.message);
        error.hidden = false;
        iniciar.disabled = false;
      }
    } },
    h('h2', {}, 'Sincronizar con ArcGIS (SIMUR)'),
    h('dl', { class: 'lista-datos' },
      h('dt', {}, 'Registros guardados'), h('dd', {}, fmtNumero(f.registros ?? 0)),
      h('dt', {}, 'Periodo'), h('dd', {}, f.periodo_inicio ? `${fmtFecha(f.periodo_inicio)} – ${fmtFecha(f.periodo_fin)}` : 'sin datos'),
      h('dt', {}, 'Última sincronización'), h('dd', {}, f.ultima_actualizacion
        ? `${fmtFechaHora(f.ultima_actualizacion.finalizada_en)} (${f.ultima_actualizacion.estado})` : 'nunca')),
    error,
    h('fieldset', { class: 'opciones-tarjeta' }, h('legend', {}, 'Tipo de sincronización'),
      opcion('incremental', 'Incremental (recomendada)', 'Trae solo lo nuevo o modificado recientemente. Tarda poco.', true),
      opcion('completa', 'Completa', 'Vuelve a descargar todo el periodo. Puede tardar mucho (cientos de miles de registros).', false)),
    h('div', { class: 'campo campo--corto' }, h('label', { for: 'sync-desde' }, 'Desde el año (opcional)'), desde),
    h('p', { class: 'suave pequeno' }, 'Si el servicio no responde, se conservan los datos guardados y la sincronización '
      + 'queda como «fallida» en el historial. Para la primera carga completa también puede usar en el servidor: '
      + 'python scripts/sync_arcgis.py --modo completa --desde-anio 2015'),
    h('div', { class: 'acciones' }, iniciar),
    progreso);
    vaciar(zona, form);
    seguirSync(progreso, iniciar, true);
  }

  async function seguirSync(progreso, boton, silencioso = false) {
    let ultima;
    try {
      ultima = (await pedirAdmin('/imports', { parametros: { tipo: 'arcgis', tamano: 1 } })).datos[0];
    } catch (err) {
      if (err.estado === 401) login('Su sesión terminó. Inicie sesión de nuevo.');
      return;
    }
    if (!vigente || !ultima) return;
    if (ultima.estado === 'en_proceso') {
      boton.disabled = true;
      vaciar(progreso, h('p', {}, pildoraEstado('en_proceso'),
        ` Sincronización n.º ${ultima.id}: ${fmtNumero(ultima.filas_revisadas)} registros revisados…`));
      esperar(() => seguirSync(progreso, boton), 4000);
    } else {
      boton.disabled = false;
      if (!silencioso || FINALES.has(ultima.estado)) {
        const completa = await pedirAdmin(`/imports/${ultima.id}`).then((r) => r.datos).catch(() => ultima);
        if (vigente) vaciar(progreso, h('h3', {}, 'Última sincronización'), detalleImportacion(completa));
      }
    }
  }

  // ================================================================ historial
  function vistaHistorial(zona) {
    const filtro = { tipo: '', estado: '', pagina: 1 };
    const tabla = h('div', {});
    const dialogo = h('dialog', { class: 'dialogo', 'aria-labelledby': 'tit-detalle-carga' });
    const selector = (id, etiqueta, clave, opciones) => h('div', { class: 'campo' },
      h('label', { for: id }, etiqueta),
      h('select', { id, onchange: (e) => { filtro[clave] = e.target.value; filtro.pagina = 1; cargar(); } },
        opciones.map(([v, t]) => h('option', { value: v }, t))));

    vaciar(zona, h('section', { class: 'seccion' },
      h('div', { class: 'seccion__cabecera' }, h('h2', {}, 'Historial de cargas'),
        h('button', { type: 'button', class: 'boton boton--secundario', onclick: () => cargar() }, icono('sincronizar'), 'Actualizar')),
      h('div', { class: 'barra-herramientas' },
        selector('hist-tipo', 'Origen', 'tipo', [['', 'Todos'], ['excel', 'Archivos'], ['arcgis', 'ArcGIS']]),
        selector('hist-estado', 'Estado', 'estado', [['', 'Todos'], ...Object.entries(ESTADOS).map(([k, [t]]) => [k, t])])),
      tabla), dialogo);

    async function cargar() {
      pararRelojes();
      if (!tabla.hasChildNodes()) vaciar(tabla, cargando());
      let r;
      try {
        r = await pedirAdmin('/imports', { parametros: { tipo: filtro.tipo, estado: filtro.estado, pagina: filtro.pagina, tamano: 20 } });
      } catch (error) { manejarError(tabla, error, cargar); return; }
      if (!vigente) return;
      const { datos, paginacion: pag } = r;
      if (!datos.length) { vaciar(tabla, h('p', { class: 'estado estado--vacio' }, 'Todavía no hay cargas con estos filtros.')); return; }
      vaciar(tabla,
        h('div', { class: 'tabla-contenedor' }, h('table', { class: 'tabla tabla--compacta' },
          h('caption', {}, `${fmtNumero(pag.total)} cargas · página ${pag.pagina} de ${Math.max(1, pag.paginas)}`),
          h('thead', {}, h('tr', {}, ['N.º', 'Origen', 'Contenido', 'Estado', 'Inicio', 'Revisadas', 'Válidas', 'Rechazadas', 'Eventos']
            .map((t, i) => h('th', { scope: 'col', class: i >= 5 && i <= 7 ? 'num' : null }, t)))),
          h('tbody', {}, datos.map((imp) => h('tr', {},
            h('td', {}, h('button', { type: 'button', class: 'boton boton--enlace', 'aria-label': `Ver detalle de la carga ${imp.id}`,
              onclick: () => verDetalle(imp.id) }, String(imp.id))),
            h('td', {}, imp.tipo === 'arcgis' ? 'ArcGIS' : 'Archivo'),
            h('td', {}, imp.tipo === 'arcgis' ? imp.modo : `${imp.modo}${imp.archivo ? ` · ${imp.archivo}` : ''}`),
            h('td', {}, pildoraEstado(imp.estado)),
            h('td', {}, fmtFechaHora(imp.iniciada_en)),
            h('td', { class: 'num' }, fmtNumero(imp.filas_revisadas)),
            h('td', { class: 'num' }, fmtNumero(imp.filas_validas)),
            h('td', { class: 'num' }, fmtNumero(imp.filas_rechazadas)),
            h('td', {}, imp.fecha_min_evento ? `${fmtFecha(imp.fecha_min_evento)} – ${fmtFecha(imp.fecha_max_evento)}` : '—')))))),
        pag.paginas > 1 ? h('div', { class: 'paginacion' },
          h('button', { type: 'button', class: 'boton boton--secundario', disabled: pag.pagina <= 1,
            onclick: () => { filtro.pagina -= 1; cargar(); } }, 'Anterior'),
          h('button', { type: 'button', class: 'boton boton--secundario', disabled: pag.pagina >= pag.paginas,
            onclick: () => { filtro.pagina += 1; cargar(); } }, 'Siguiente')) : null);
      if (datos.some((d) => d.estado === 'en_proceso')) esperar(cargar, 5000);
    }

    async function verDetalle(id) {
      vaciar(dialogo, cargando());
      dialogo.showModal();
      try {
        const imp = (await pedirAdmin(`/imports/${id}`)).datos;
        const mapeo = Object.entries(imp.mapeo ?? {});
        vaciar(dialogo,
          h('div', { class: 'dialogo__cabecera' }, h('h2', { id: 'tit-detalle-carga' }, `Carga n.º ${imp.id}`),
            h('button', { type: 'button', class: 'boton boton--claro', 'aria-label': 'Cerrar', onclick: () => dialogo.close() }, '✕')),
          detalleImportacion(imp),
          listaAvisos(imp.resumen?.advertencias ?? []),
          mapeo.length ? h('details', {}, h('summary', {}, 'Mapeo de columnas usado'),
            h('table', { class: 'tabla tabla--compacta' }, h('tbody', {}, mapeo.map(([c, col]) =>
              h('tr', {}, h('th', { scope: 'row' }, c), h('td', {}, String(col))))))) : null,
          h('details', {}, h('summary', {}, 'Resumen técnico'),
            h('pre', { class: 'json' }, JSON.stringify(imp.resumen ?? {}, null, 2))));
      } catch (error) {
        if (error.estado === 401) { dialogo.close(); login('Su sesión terminó. Inicie sesión de nuevo.'); return; }
        vaciar(dialogo, cajaError(error), h('button', { type: 'button', class: 'boton', onclick: () => dialogo.close() }, 'Cerrar'));
      }
    }

    dialogo.addEventListener('click', (e) => { if (e.target === dialogo) dialogo.close(); });
    cargar();
  }

}
