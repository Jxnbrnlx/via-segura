// Buscador principal con autocompletado (patrón combobox de ARIA).
// Escribir "kenn", "2024", "atropello", "peatón", "marzo" o "con muertos" sugiere el filtro correspondiente;
// cualquier otro texto se puede buscar como dirección en el Explorador.
import * as estado from '../estado.js';
import { h, icono, MESES, normalizar, titulo, vaciar } from '../util.js';

let contador = 0;

export function opcionesBusqueda(metadatos) {
  const v = metadatos?.datos?.valores_para_filtros ?? {};
  const personas = (metadatos?.datos?.dimensiones ?? []).find((d) => d.clave === 'personas')?.disponible;
  const opciones = [
    ...(v.localidades ?? []).map((l) => ({ grupo: 'Localidad', clave: 'localidad', valor: l.clave, texto: l.nombre })),
    ...[...(v.anios ?? [])].reverse().map((a) => ({ grupo: 'Año', clave: 'anio', valor: String(a), texto: String(a) })),
    ...MESES.map((m, i) => ({ grupo: 'Mes', clave: 'mes', valor: String(i + 1), texto: m })),
    ...(v.clases ?? []).map((c) => ({ grupo: 'Clase', clave: 'clase', valor: c, texto: c })),
    ...(personas ? (v.actores ?? []) : []).map((a) => ({ grupo: 'Actor vial', clave: 'actor', valor: a, texto: titulo(a) })),
    ...(v.gravedades ?? []).map((g) => ({ grupo: 'Gravedad', clave: 'gravedad', valor: g, texto: g })),
  ];
  return opciones.map((o) => ({ ...o, buscable: normalizar(`${o.texto} ${o.grupo}`) }));
}

export function aplicarOpcion(o) {
  if (o.clave === 'gravedad') estado.actualizar({ gravedad: [o.valor] });
  else estado.alternar(o.clave, o.valor, true);
}

export function crearBuscador({ metadatos, alBuscarDireccion }) {
  const id = `buscador-${++contador}`;
  const todas = opcionesBusqueda(metadatos);
  let visibles = [];
  let activa = -1;

  const lista = h('ul', { class: 'sugerencias', id: `${id}-lista`, role: 'listbox', hidden: true, 'aria-label': 'Sugerencias' });
  const entrada = h('input', {
    id, type: 'text', role: 'combobox', autocomplete: 'off', 'aria-autocomplete': 'list', 'aria-expanded': 'false',
    'aria-controls': `${id}-lista`, maxlength: 100,
    placeholder: 'Busca una localidad, un año, "peatones", "atropello"…',
  });

  function cerrar() {
    lista.hidden = true;
    entrada.setAttribute('aria-expanded', 'false');
    entrada.removeAttribute('aria-activedescendant');
    activa = -1;
  }

  function marcar(i) {
    activa = i;
    [...lista.children].forEach((li, j) => li.setAttribute('aria-selected', String(j === i)));
    if (i >= 0) {
      entrada.setAttribute('aria-activedescendant', `${id}-op-${i}`);
      lista.children[i].scrollIntoView({ block: 'nearest' });
    } else entrada.removeAttribute('aria-activedescendant');
  }

  function elegir(o) {
    cerrar();
    entrada.value = '';
    if (o.clave === 'direccion') alBuscarDireccion(o.valor);
    else aplicarOpcion(o);
  }

  function sugerir() {
    const texto = normalizar(entrada.value);
    if (!texto) { cerrar(); return; }
    const palabras = texto.split(/\s+/);
    visibles = todas
      .filter((o) => palabras.every((p) => o.buscable.includes(p)))
      .sort((a, b) => Number(!normalizar(a.texto).startsWith(texto)) - Number(!normalizar(b.texto).startsWith(texto)))
      .slice(0, 8);
    if (entrada.value.trim().length >= 3) {
      visibles.push({ grupo: 'Dirección', clave: 'direccion', valor: entrada.value.trim(),
        texto: `Buscar “${entrada.value.trim()}” en direcciones y barrios` });
    }
    vaciar(lista, visibles.map((o, i) => h('li', {
      id: `${id}-op-${i}`, role: 'option', 'aria-selected': 'false',
      onmousedown: (e) => { e.preventDefault(); elegir(o); },
    }, h('span', { class: 'grupo' }, o.grupo), h('span', {}, o.texto))));
    if (!visibles.length) {
      lista.append(h('li', { role: 'option', 'aria-disabled': 'true' }, 'Sin coincidencias. Pruebe con otra palabra.'));
    }
    lista.hidden = false;
    entrada.setAttribute('aria-expanded', 'true');
    marcar(visibles.length ? 0 : -1);
  }

  entrada.addEventListener('input', sugerir);
  entrada.addEventListener('blur', () => setTimeout(cerrar, 120));
  entrada.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown' && visibles.length) { e.preventDefault(); if (lista.hidden) sugerir(); marcar((activa + 1) % visibles.length); }
    else if (e.key === 'ArrowUp' && visibles.length) { e.preventDefault(); marcar((activa - 1 + visibles.length) % visibles.length); }
    else if (e.key === 'Enter') {
      e.preventDefault();
      if (!lista.hidden && activa >= 0) elegir(visibles[activa]);
    } else if (e.key === 'Escape') { cerrar(); }
  });

  return h('div', { class: 'buscador' },
    h('label', { for: id, class: 'solo-lectores' }, 'Buscar en los datos'),
    h('div', { class: 'buscador__caja' }, icono('buscar'), entrada),
    lista);
}

/** Atajos de un clic (botones conmutables) según lo disponible en la fuente. */
export function crearAtajos(metadatos) {
  const v = metadatos?.datos?.valores_para_filtros ?? {};
  const personas = (metadatos?.datos?.dimensiones ?? []).find((d) => d.clave === 'personas')?.disponible;
  const actores = new Set(personas ? v.actores ?? [] : []);
  const ultimo = v.anios?.length ? String(v.anios[v.anios.length - 1]) : null;
  const atajos = [
    actores.has('PEATON') && { texto: 'Peatones', clave: 'actor', valor: 'PEATON', icono: 'persona' },
    actores.has('MOTOCICLISTA') && { texto: 'Motociclistas', clave: 'actor', valor: 'MOTOCICLISTA', icono: 'auto' },
    actores.has('CICLISTA') && { texto: 'Ciclistas', clave: 'actor', valor: 'CICLISTA', icono: 'persona' },
    (v.gravedades ?? []).includes('Con Muertos') && { texto: 'Con muertos', clave: 'gravedad', valor: 'Con Muertos', icono: 'lazo' },
    ultimo && { texto: `Año ${ultimo}`, clave: 'anio', valor: ultimo, icono: 'calendario' },
  ].filter(Boolean);
  const f = estado.filtros();
  return h('div', { class: 'atajos', role: 'group', 'aria-label': 'Búsquedas rápidas' }, atajos.map((a) => {
    const activo = a.clave === 'gravedad' ? f.gravedad.length === 1 && f.gravedad[0] === a.valor : f[a.clave].includes(a.valor);
    return h('button', {
      type: 'button', class: 'atajo', 'aria-pressed': String(activo),
      onclick: () => {
        if (a.clave === 'gravedad') estado.actualizar({ gravedad: activo ? [] : [a.valor] });
        else estado.alternar(a.clave, a.valor, !activo);
      },
    }, icono(a.icono), a.texto);
  }));
}
