"""Pruebas del descargador de librerías del frontend, sin Internet (se sustituye _leer)."""
import base64
import hashlib
import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest

RUTA = Path(__file__).resolve().parents[2] / "scripts" / "descargar_librerias.py"


@pytest.fixture
def modulo(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("descargar_librerias", RUTA)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, "RAIZ", tmp_path)
    monkeypatch.setattr(m, "DESTINO", tmp_path / "frontend" / "vendor")
    return m


def tarball(archivos: dict[str, bytes]) -> bytes:
    salida = io.BytesIO()
    with tarfile.open(fileobj=salida, mode="w:gz") as tar:
        for nombre, datos in archivos.items():
            info = tarfile.TarInfo(f"package/{nombre}")
            info.size = len(datos)
            tar.addfile(info, io.BytesIO(datos))
    return salida.getvalue()


def integridad(datos: bytes) -> str:
    return "sha512-" + base64.b64encode(hashlib.sha512(datos).digest()).decode()


def registro_falso(paquete: bytes, integ: str | None = None):
    def leer(url):
        if url.endswith(".tgz"):
            return paquete
        return json.dumps({"dist": {"tarball": "https://registro/x.tgz", "integrity": integ or integridad(paquete)}}).encode()
    return leer


def test_extrae_solo_los_archivos_listados(modulo, tmp_path, monkeypatch):
    paquete = tarball({"dist/lib.js": b"// lib", "dist/otro.js": b"// no", "LICENSE": b"MIT"})
    monkeypatch.setattr(modulo, "_leer", registro_falso(paquete))
    destino = tmp_path / "t"
    instalados = modulo.descargar("lib", "1.0.0", {"dist/lib.js": "lib/lib.js", "LICENSE": "licencias/lib.txt"}, destino)
    assert sorted(instalados) == ["lib/lib.js", "licencias/lib.txt"]
    assert (destino / "lib" / "lib.js").read_bytes() == b"// lib"
    assert not list(destino.rglob("otro.js"))


def test_huella_distinta_no_instala_nada(modulo, tmp_path, monkeypatch):
    paquete = tarball({"dist/lib.js": b"// lib"})
    monkeypatch.setattr(modulo, "_leer", registro_falso(paquete, integridad(b"otra cosa")))
    with pytest.raises(ValueError, match="SHA-512"):
        modulo.descargar("lib", "1.0.0", {"dist/lib.js": "lib/lib.js"}, tmp_path / "t")
    assert not (tmp_path / "t" / "lib").exists()


def test_rechaza_algoritmo_distinto_a_sha512(modulo):
    with pytest.raises(ValueError, match="no soportado"):
        modulo._verificar(b"x", "sha1-abc")


def test_ruta_de_destino_fuera_de_la_carpeta(modulo, tmp_path, monkeypatch):
    paquete = tarball({"dist/lib.js": b"// lib"})
    monkeypatch.setattr(modulo, "_leer", registro_falso(paquete))
    with pytest.raises(ValueError, match="Ruta inválida"):
        modulo.descargar("lib", "1.0.0", {"dist/lib.js": "../../fuera.js"}, tmp_path / "t")
    assert not (tmp_path / "fuera.js").exists()


def test_archivo_faltante_en_el_paquete(modulo, tmp_path, monkeypatch):
    monkeypatch.setattr(modulo, "_leer", registro_falso(tarball({"dist/a.js": b"a"})))
    with pytest.raises(ValueError, match="no contiene dist/b.js"):
        modulo.descargar("lib", "1.0.0", {"dist/b.js": "lib/b.js"}, tmp_path / "t")


def test_principal_instala_todo_y_escribe_licencias(modulo, monkeypatch):
    contenido = {}
    for _, _, archivos in modulo.PAQUETES:
        for origen in archivos:
            contenido[origen] = f"contenido de {origen}".encode()
    paquete = tarball(contenido)
    monkeypatch.setattr(modulo, "_leer", registro_falso(paquete))
    assert modulo.principal() == 0
    vendor = modulo.DESTINO
    for ruta in ("leaflet/leaflet.js", "leaflet.markercluster/leaflet.markercluster.js",
                 "leaflet.heat/leaflet-heat.js", "chart.js/chart.umd.js", "LICENCIAS.txt"):
        assert (vendor / ruta).is_file(), ruta
    assert "chart.js 4.4.1" in (vendor / "LICENCIAS.txt").read_text(encoding="utf-8")
    assert not vendor.with_name("vendor.tmp").exists()


def test_principal_con_fallo_no_toca_lo_instalado(modulo, monkeypatch, capsys):
    modulo.DESTINO.mkdir(parents=True)
    (modulo.DESTINO / "previo.txt").write_text("versión anterior")
    def sin_red(url):
        raise OSError("sin conexión")
    monkeypatch.setattr(modulo, "_leer", sin_red)
    assert modulo.principal() == 1
    assert (modulo.DESTINO / "previo.txt").read_text() == "versión anterior"
    assert not modulo.DESTINO.with_name("vendor.tmp").exists()
    assert "No se modificó frontend/vendor" in capsys.readouterr().out
