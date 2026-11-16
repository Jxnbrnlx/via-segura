"""Descarga las librerías del frontend (Leaflet, plugins y Chart.js) a frontend/vendor/.

Se ejecuta UNA vez (necesita Internet):
    python scripts/descargar_librerias.py

Por qué así: la página solo carga scripts del propio servidor (política CSP 'self'), sin CDN.
Cómo se protege la descarga:
- Versiones fijas (no "la última").
- Cada paquete se descarga del registro oficial de npm y se compara con la huella SHA-512 que el
  propio registro publica (campo dist.integrity). Si no coincide, no se instala nada.
- Del paquete solo se extraen los archivos listados abajo (nunca rutas arbitrarias).
- Se copian las licencias a frontend/vendor/LICENCIAS.txt.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DESTINO = RAIZ / "frontend" / "vendor"
REGISTRO = "https://registry.npmjs.org"

# paquete, versión, {archivo dentro del paquete: ruta destino relativa a vendor/}
PAQUETES = [
    ("leaflet", "1.9.4", {
        "dist/leaflet.js": "leaflet/leaflet.js",
        "dist/leaflet.css": "leaflet/leaflet.css",
        "dist/images/layers.png": "leaflet/images/layers.png",
        "dist/images/layers-2x.png": "leaflet/images/layers-2x.png",
        "dist/images/marker-icon.png": "leaflet/images/marker-icon.png",
        "dist/images/marker-icon-2x.png": "leaflet/images/marker-icon-2x.png",
        "dist/images/marker-shadow.png": "leaflet/images/marker-shadow.png",
        "LICENSE": "licencias/leaflet.txt",
    }),
    ("leaflet.markercluster", "1.5.3", {
        "dist/leaflet.markercluster.js": "leaflet.markercluster/leaflet.markercluster.js",
        "dist/MarkerCluster.css": "leaflet.markercluster/MarkerCluster.css",
        "MIT-LICENCE.txt": "licencias/leaflet.markercluster.txt",
    }),
    ("leaflet.heat", "0.2.0", {
        "dist/leaflet-heat.js": "leaflet.heat/leaflet-heat.js",
    }),
    ("chart.js", "4.4.1", {
        "dist/chart.umd.js": "chart.js/chart.umd.js",
        "LICENSE.md": "licencias/chart.js.txt",
    }),
]


def _leer(url: str) -> bytes:
    peticion = urllib.request.Request(url, headers={"User-Agent": "via-segura-descargador/1.0"})
    with urllib.request.urlopen(peticion, timeout=60) as respuesta:
        return respuesta.read()


def _verificar(datos: bytes, integridad: str) -> None:
    algoritmo, _, esperado = integridad.partition("-")
    if algoritmo != "sha512":
        raise ValueError(f"Algoritmo de integridad no soportado: {algoritmo}")
    obtenido = base64.b64encode(hashlib.sha512(datos).digest()).decode()
    if obtenido != esperado:
        raise ValueError("La huella SHA-512 no coincide con la publicada por npm: descarga alterada o dañada.")


def descargar(nombre: str, version: str, archivos: dict[str, str], temporal: Path) -> list[str]:
    metadatos = json.loads(_leer(f"{REGISTRO}/{nombre}/{version}"))
    dist = metadatos["dist"]
    paquete = _leer(dist["tarball"])
    _verificar(paquete, dist["integrity"])
    instalados = []
    faltan = []
    with tarfile.open(fileobj=io.BytesIO(paquete), mode="r:gz") as tar:
        miembros = {m.name.split("/", 1)[1]: m for m in tar.getmembers() if m.isfile() and "/" in m.name}
        for origen, destino in archivos.items():
            miembro = miembros.get(origen)
            if miembro is None:
                if origen.lower().startswith(("license", "mit-licence")):
                    continue  # algunas versiones nombran distinto la licencia
                faltan.append(origen)
                continue
            ruta = (temporal / destino).resolve()
            if temporal.resolve() not in ruta.parents:
                raise ValueError(f"Ruta inválida en el paquete: {destino}")
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_bytes(tar.extractfile(miembro).read())
            instalados.append(destino)
    if faltan:
        raise ValueError(f"{nombre}@{version}: el paquete no contiene {', '.join(faltan)}")
    return instalados


def principal() -> int:
    temporal = DESTINO.with_name("vendor.tmp")
    shutil.rmtree(temporal, ignore_errors=True)
    temporal.mkdir(parents=True)
    try:
        for nombre, version, archivos in PAQUETES:
            print(f"Descargando {nombre}@{version}…", end=" ", flush=True)
            instalados = descargar(nombre, version, archivos, temporal)
            print(f"verificado ({len(instalados)} archivos)")
    except Exception as exc:  # noqa: BLE001 - se informa y no se deja nada a medias
        shutil.rmtree(temporal, ignore_errors=True)
        print(f"\nNo se pudieron instalar las librerías: {exc}")
        print("Revise la conexión a Internet (o el proxy) e intente de nuevo. No se modificó frontend/vendor.")
        return 1
    licencias = sorted((temporal / "licencias").glob("*.txt"))
    resumen = "\n\n".join(f"===== {p.stem} =====\n{p.read_text(encoding='utf-8', errors='replace')}" for p in licencias)
    (temporal / "LICENCIAS.txt").write_text(
        "Librerías de terceros incluidas en frontend/vendor (versiones fijas, verificadas con npm):\n"
        + "\n".join(f"- {n} {v}" for n, v, _ in PAQUETES) + "\n\n" + resumen, encoding="utf-8")
    shutil.rmtree(DESTINO, ignore_errors=True)
    temporal.rename(DESTINO)
    print(f"\nListo: librerías instaladas en {DESTINO.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
