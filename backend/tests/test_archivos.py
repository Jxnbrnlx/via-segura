"""Recepción segura de archivos: nombre, extensión, MIME, tamaño y contenido."""
import io
import zipfile

import pytest

from app.services.archivos import (
    ErrorArchivo, eliminar_recibido, recibir_archivo, ruta_de_token, sanear_nombre, sha256_de,
)

MB = 1024 * 1024


@pytest.mark.parametrize("entrada, esperado", [
    ("Base Anuario 2025 (2).CSV", "Base_Anuario_2025_2.csv"),
    ("../../etc/passwd.csv", "passwd.csv"),
    ("C:\\Users\\x\\..\\Vehículos.xlsx", "Vehiculos.xlsx"),
    ("..\\..\\.csv", "archivo.csv"),
    ("a.csv.exe", "a_csv.exe"),
    ("localidades.GeoJSON", "localidades.geojson"),
])
def test_sanear_nombre(entrada, esperado):
    assert sanear_nombre(entrada) == esperado


@pytest.mark.parametrize("malo", ["", None, "sin_extension"])
def test_nombre_invalido(malo):
    with pytest.raises(ErrorArchivo):
        sanear_nombre(malo)


def recibir(tmp_path, contenido: bytes, nombre="datos.csv", mime="text/csv", max_bytes=5 * MB):
    return recibir_archivo(io.BytesIO(contenido), nombre, mime, tmp_path, max_bytes=max_bytes, max_descomprimido=MB)


def test_csv_valido_se_guarda_dentro_de_una_carpeta_aleatoria(tmp_path):
    r = recibir(tmp_path, "a;b\n1;2\n".encode())
    assert r.ruta.parent.parent == tmp_path and len(r.token) == 32
    assert r.nombre == "datos.csv" and r.tamano == 8 and sha256_de(r.ruta) == r.sha256


def test_csv_de_windows_declarado_como_excel(tmp_path):
    assert recibir(tmp_path, b"a,b\n1,2\n", mime="application/vnd.ms-excel").extension == ".csv"


@pytest.mark.parametrize("nombre, mime", [("datos.exe", "application/octet-stream"), ("datos.csv", "image/png"),
                                          ("datos.xlsm", "application/vnd.ms-excel")])
def test_extension_o_mime_no_permitidos(tmp_path, nombre, mime):
    with pytest.raises(ErrorArchivo):
        recibir(tmp_path, b"a,b\n1,2\n", nombre=nombre, mime=mime)
    assert list(tmp_path.iterdir()) == []


def test_tamano_maximo_aborta_y_no_deja_rastros(tmp_path):
    with pytest.raises(ErrorArchivo, match="tamaño máximo"):
        recibir(tmp_path, b"a,b\n" + b"1,2\n" * 1000, max_bytes=100)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("contenido, motivo", [
    (b"", "vacío"),
    (b"a,b\n\x00\x01\x02", "binarios"),
    (b"solo_una_columna\n1\n", "separador"),
    (b"a;\n1;\n", "dos columnas"),
])
def test_csv_con_contenido_invalido(tmp_path, contenido, motivo):
    with pytest.raises(ErrorArchivo, match=motivo):
        recibir(tmp_path, contenido)


def _zip(archivos: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre, datos in archivos.items():
            z.writestr(nombre, datos)
    return buf.getvalue()


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_xlsx_falso_se_rechaza(tmp_path):
    with pytest.raises(ErrorArchivo, match="firma"):
        recibir(tmp_path, b"a,b\n1,2\n", nombre="x.xlsx", mime=XLSX)
    with pytest.raises(ErrorArchivo, match="workbook"):
        recibir(tmp_path, _zip({"hola.txt": b"x"}), nombre="x.xlsx", mime=XLSX)


def test_xlsx_con_macros_se_rechaza(tmp_path):
    contenido = _zip({"[Content_Types].xml": b"x", "xl/workbook.xml": b"x", "xl/vbaProject.bin": b"x"})
    with pytest.raises(ErrorArchivo, match="macros"):
        recibir(tmp_path, contenido, nombre="x.xlsx", mime=XLSX)


def test_bomba_zip_se_rechaza(tmp_path):
    contenido = _zip({"[Content_Types].xml": b"x", "xl/workbook.xml": b"x", "xl/grande.xml": b"0" * (3 * MB)})
    with pytest.raises(ErrorArchivo, match="descomprimido"):
        recibir(tmp_path, contenido, nombre="x.xlsx", mime=XLSX)


def test_xlsx_real_se_acepta(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    libro = openpyxl.Workbook()
    libro.active.append(["a", "b"])
    buf = io.BytesIO()
    libro.save(buf)
    assert recibir(tmp_path, buf.getvalue(), nombre="x.xlsx", mime=XLSX).extension == ".xlsx"


def test_geojson_que_no_es_featurecollection(tmp_path):
    with pytest.raises(ErrorArchivo, match="GeoJSON"):
        recibir(tmp_path, b'{"type": "Point"}', nombre="l.geojson", mime="application/geo+json")


def test_ruta_de_token_impide_salir_del_directorio(tmp_path):
    r = recibir(tmp_path, b"a,b\n1,2\n")
    assert ruta_de_token(tmp_path, r.token, r.nombre) == r.ruta.resolve()
    for token, nombre in [("../" + r.token, r.nombre), (r.token, "../x.csv"), ("abc", "x.csv")]:
        with pytest.raises(ErrorArchivo):
            ruta_de_token(tmp_path, token, nombre)
    eliminar_recibido(tmp_path, r.token)
    assert not r.ruta.exists()
