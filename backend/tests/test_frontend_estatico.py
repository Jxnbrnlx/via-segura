"""Revisión estática del frontend: sin recursos externos (salvo las teselas de OpenStreetMap), sin HTML
construido con datos, sin rojo/amarillo para zonas y sin la palabra «peligrosa»."""
import colorsys
import re
from pathlib import Path

import pytest

FRONT = Path(__file__).resolve().parents[2] / "frontend"
JS = sorted((FRONT / "js").rglob("*.js"))
CSS = sorted((FRONT / "css").rglob("*.css"))
URLS_PERMITIDAS = {
    "http://www.w3.org/2000/svg",                         # espacio de nombres SVG, no es una petición
    "https://tile.openstreetmap.org/{z}/{x}/{y}.png",      # teselas del mapa base (CSP img-src)
    "https://www.openstreetmap.org/copyright",             # atribución obligatoria
    "https://…",                                           # texto de ejemplo en un campo
}


def test_hay_archivos_que_revisar():
    assert len(JS) >= 15 and CSS and (FRONT / "index.html").is_file()


def test_sin_librerias_ni_recursos_de_cdn():
    html = (FRONT / "index.html").read_text(encoding="utf-8")
    assert not re.search(r'<(script|link)[^>]+(src|href)="(https?:)?//', html)
    for ruta in JS:
        texto = ruta.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s'\"`)]+", texto):
            assert url in URLS_PERMITIDAS, (ruta.name, url)
        assert not re.search(r"import\s*\(?\s*['\"](https?:)?//", texto), ruta.name


@pytest.mark.parametrize("ruta", JS, ids=lambda r: r.name)
def test_sin_html_construido_con_datos(ruta):
    texto = ruta.read_text(encoding="utf-8")
    codigo = "\n".join(l for l in texto.splitlines() if not l.strip().startswith("//"))
    assert not re.search(r"\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\.write|\beval\(|new Function",
                         codigo), ruta.name
    # Única excepción: el icono de clúster de Leaflet, que solo recibe un número.
    for m in re.finditer(r"html:\s*(`[^`]*`|'[^']*'|\"[^\"]*\"|\S+)", codigo):
        assert re.fullmatch(r"`<span>\$\{[\w.()]+\}</span>`", m.group(1).strip()), (ruta.name, m.group(0))


def _hex_a_hls(valor: str):
    valor = valor.lstrip("#")
    if len(valor) == 3:
        valor = "".join(c * 2 for c in valor)
    r, g, b = (int(valor[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return colorsys.rgb_to_hls(r, g, b)


def test_sin_rojo_ni_amarillo_en_la_paleta():
    textos = [r.read_text(encoding="utf-8") for r in CSS] + [r.read_text(encoding="utf-8") for r in JS]
    for texto in textos:
        assert not re.search(r"(?<![\w-])(red|yellow|orange|gold)(?![\w-])\s*[;,)'\"]", texto, re.IGNORECASE)
        for valor in re.findall(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b", texto):
            h, l, s = _hex_a_hls(valor)
            tono = h * 360
            saturado = s > 0.45 and 0.2 < l < 0.85
            assert not (saturado and (tono < 25 or tono > 335 or 40 < tono < 70)), valor


def test_nunca_se_califica_una_zona_como_peligrosa():
    for ruta in JS + [FRONT / "index.html"]:
        texto = ruta.read_text(encoding="utf-8").lower()
        for m in re.finditer(r"peligros[ao]s?", texto):
            contexto = texto[max(0, m.start() - 60):m.end() + 10]
            assert "no" in contexto or "«peligrosa»" in contexto or "¿" in contexto, (ruta.name, contexto)
