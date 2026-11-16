"""Recepción segura de archivos subidos por el administrador.

Controles (en este orden):
1. Nombre saneado: solo el nombre base, ASCII, sin rutas ni "..": nunca se usa la ruta del usuario.
2. Extensión permitida (.csv, .xlsx, .geojson, .json) y MIME declarado compatible con ella.
3. Tamaño: se copia por bloques y se aborta al superar el límite (no se carga todo en memoria).
4. Contenido real: firma ZIP + libro de Excel sin macros y sin "bomba ZIP" (xlsx); texto sin bytes
   NUL con un separador reconocible (csv); JSON con FeatureCollection (geojson).
El archivo se guarda en <directorio>/<token aleatorio>/<nombre saneado>; el token es lo único que se
registra para encontrarlo después.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import secrets
import shutil
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

EXTENSIONES = {".csv", ".xlsx", ".geojson", ".json"}
MIME_PERMITIDOS = {
    # Windows suele declarar los CSV como application/vnd.ms-excel; varios navegadores usan octet-stream.
    ".csv": {"text/csv", "application/csv", "text/plain", "application/vnd.ms-excel", "application/octet-stream"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/zip",
              "application/x-zip-compressed", "application/octet-stream"},
    ".geojson": {"application/geo+json", "application/json", "text/plain", "application/octet-stream"},
    ".json": {"application/geo+json", "application/json", "text/plain", "application/octet-stream"},
}
_TOKEN = re.compile(r"^[a-f0-9]{32}$")
_BLOQUE = 1024 * 1024


class ErrorArchivo(ValueError):
    """Archivo rechazado. El mensaje es apto para mostrar al administrador."""


@dataclass(frozen=True)
class ArchivoRecibido:
    token: str
    nombre: str          # nombre saneado
    extension: str
    ruta: Path
    tamano: int
    sha256: str


def sanear_nombre(nombre: str | None) -> str:
    """'../../x/Base Anuario 2025 (2).CSV' -> 'Base_Anuario_2025_2.csv'. Lanza ErrorArchivo si no queda nada útil."""
    if not nombre:
        raise ErrorArchivo("El archivo no tiene nombre.")
    base = re.split(r"[\\/]", nombre.strip())[-1]  # descarta cualquier ruta (Windows o POSIX)
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii")
    raiz, punto, extension = base.rpartition(".")
    if not punto:
        raise ErrorArchivo("El archivo no tiene extensión. Se aceptan: " + ", ".join(sorted(EXTENSIONES)))
    raiz = re.sub(r"[^A-Za-z0-9_-]+", "_", raiz).strip("_.-")[:100]
    extension = extension.lower()
    if not raiz:
        raiz = "archivo"
    return f"{raiz}.{extension}"


def validar_extension_y_mime(nombre_saneado: str, mime: str | None) -> str:
    extension = Path(nombre_saneado).suffix.lower()
    if extension not in EXTENSIONES:
        raise ErrorArchivo(f"Extensión '{extension}' no permitida. Se aceptan: " + ", ".join(sorted(EXTENSIONES)))
    tipo = (mime or "application/octet-stream").split(";")[0].strip().lower()
    if tipo not in MIME_PERMITIDOS[extension]:
        raise ErrorArchivo(f"El tipo declarado '{tipo}' no corresponde a un archivo {extension}.")
    return extension


def _validar_xlsx(ruta: Path, max_descomprimido: int) -> None:
    with ruta.open("rb") as f:
        if f.read(4) != b"PK\x03\x04":
            raise ErrorArchivo("El archivo .xlsx no es un libro de Excel válido (firma incorrecta).")
    try:
        with zipfile.ZipFile(ruta) as z:
            nombres = set(z.namelist())
            if "xl/workbook.xml" not in nombres or "[Content_Types].xml" not in nombres:
                raise ErrorArchivo("El .xlsx no contiene un libro de Excel (falta xl/workbook.xml).")
            if any(n.lower().endswith("vbaproject.bin") for n in nombres):
                raise ErrorArchivo("El libro contiene macros; no se aceptan archivos con macros.")
            total = sum(i.file_size for i in z.infolist())
            if total > max_descomprimido:
                raise ErrorArchivo(f"El libro descomprimido ocuparía {total // 1_048_576} MB; supera el límite de "
                                   f"{max_descomprimido // 1_048_576} MB.")
    except zipfile.BadZipFile as exc:
        raise ErrorArchivo("El .xlsx está dañado o no es un ZIP válido.") from exc


def detectar_codificacion(muestra: bytes) -> str:
    """utf-8-sig (con o sin BOM) y, si falla, cp1252 (Excel en español en Windows)."""
    for codificacion in ("utf-8-sig", "cp1252"):
        try:
            muestra.decode(codificacion)
            return codificacion
        except UnicodeDecodeError as exc:
            # Un carácter multibyte cortado al final de la muestra no invalida el UTF-8.
            if codificacion == "utf-8-sig" and exc.start >= len(muestra) - 3:
                return codificacion
    raise ErrorArchivo("No se pudo leer el texto del CSV (codificación desconocida).")


def detectar_separador(texto: str) -> str:
    primera = texto.splitlines()[0] if texto else ""
    try:
        return csv.Sniffer().sniff(texto[:20_000], delimiters=",;\t|").delimiter
    except csv.Error:
        conteos = {s: primera.count(s) for s in ",;\t|"}
        separador = max(conteos, key=conteos.get)
        if conteos[separador] == 0:
            raise ErrorArchivo("No se reconoce el separador del CSV (se esperaba coma, punto y coma o tabulador).")
        return separador


def _validar_csv(ruta: Path) -> None:
    with ruta.open("rb") as f:
        muestra = f.read(65_536)
    if not muestra.strip():
        raise ErrorArchivo("El CSV está vacío.")
    if b"\x00" in muestra:
        raise ErrorArchivo("El archivo contiene bytes binarios: no es un CSV de texto.")
    texto = muestra.decode(detectar_codificacion(muestra), errors="ignore")
    separador = detectar_separador(texto)
    encabezado = next(csv.reader(io.StringIO(texto), delimiter=separador), [])
    if len([c for c in encabezado if c.strip()]) < 2:
        raise ErrorArchivo("El CSV debe tener una fila de encabezados con al menos dos columnas.")


def _validar_geojson(ruta: Path) -> None:
    with ruta.open("rb") as f:
        inicio = f.read(4096)
    texto = inicio.decode("utf-8-sig", errors="ignore").lstrip()
    if not texto.startswith("{") or "FeatureCollection" not in texto:
        raise ErrorArchivo("El archivo no parece un GeoJSON (se esperaba un FeatureCollection).")


def validar_contenido(ruta: Path, extension: str, max_descomprimido: int) -> None:
    if extension == ".xlsx":
        _validar_xlsx(ruta, max_descomprimido)
    elif extension == ".csv":
        _validar_csv(ruta)
    else:
        _validar_geojson(ruta)


def recibir_archivo(
    flujo: BinaryIO,
    nombre: str | None,
    mime: str | None,
    directorio: Path,
    *,
    max_bytes: int,
    max_descomprimido: int = 3 * 1024 ** 3,
) -> ArchivoRecibido:
    """Valida y guarda el archivo. Si algo falla, no deja nada en disco."""
    nombre_saneado = sanear_nombre(nombre)
    extension = validar_extension_y_mime(nombre_saneado, mime)
    token = secrets.token_hex(16)
    carpeta = Path(directorio) / token
    carpeta.mkdir(parents=True, exist_ok=False)
    ruta = carpeta / nombre_saneado
    resumen = hashlib.sha256()
    tamano = 0
    try:
        with ruta.open("wb") as destino:
            while True:
                bloque = flujo.read(_BLOQUE)
                if not bloque:
                    break
                tamano += len(bloque)
                if tamano > max_bytes:
                    raise ErrorArchivo(f"El archivo supera el tamaño máximo permitido ({max_bytes // 1_048_576} MB).")
                resumen.update(bloque)
                destino.write(bloque)
        if tamano == 0:
            raise ErrorArchivo("El archivo está vacío.")
        validar_contenido(ruta, extension, max_descomprimido)
    except BaseException:
        shutil.rmtree(carpeta, ignore_errors=True)
        raise
    return ArchivoRecibido(token, nombre_saneado, extension, ruta, tamano, resumen.hexdigest())


def ruta_de_token(directorio: Path, token: str, nombre_saneado: str) -> Path:
    """Reconstruye la ruta de un archivo recibido, verificando que no escape del directorio."""
    if not _TOKEN.match(token or "") or sanear_nombre(nombre_saneado) != nombre_saneado:
        raise ErrorArchivo("Referencia de archivo inválida.")
    base = Path(directorio).resolve()
    ruta = (base / token / nombre_saneado).resolve()
    if base not in ruta.parents:
        raise ErrorArchivo("Referencia de archivo inválida.")
    return ruta


def sha256_de(ruta: Path) -> str:
    resumen = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(_BLOQUE), b""):
            resumen.update(bloque)
    return resumen.hexdigest()


def eliminar_recibido(directorio: Path, token: str) -> None:
    if _TOKEN.match(token or ""):
        shutil.rmtree(Path(directorio) / token, ignore_errors=True)
