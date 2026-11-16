"""Lectura por bloques de CSV y XLSX sin cargar el archivo completo en memoria.

- CSV: módulo csv de la biblioteca estándar (valores siempre como texto; '' -> None). Detecta
  codificación (UTF-8 con o sin BOM, o cp1252) y separador (coma, punto y coma, tabulador).
- XLSX: openpyxl en modo read_only (el anuario 2015-2024 pesa ~126 MB). Conserva el tipo de la
  celda (fecha, número o texto).
Cada fila se entrega como (numero_de_fila_en_el_archivo, {columna_original: valor}).
"""
from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path

from .archivos import ErrorArchivo, detectar_codificacion, detectar_separador

FilaNumerada = tuple[int, dict[str, object]]


def _encabezados_unicos(valores: list[object]) -> list[str]:
    salida: list[str] = []
    vistos: dict[str, int] = {}
    for i, v in enumerate(valores, start=1):
        nombre = str(v).strip().lstrip("﻿") if v is not None and str(v).strip() else f"columna_{i}"
        if nombre in vistos:
            vistos[nombre] += 1
            nombre = f"{nombre}_{vistos[nombre]}"
        else:
            vistos[nombre] = 1
        salida.append(nombre)
    return salida


def _limpiar(valor: object) -> object:
    if isinstance(valor, str):
        valor = valor.strip()
        return valor or None
    return valor


class LectorCSV:
    hojas: list[str] = []

    def __init__(self, ruta: Path):
        self.ruta = Path(ruta)
        with self.ruta.open("rb") as f:
            muestra = f.read(65_536)
        self.codificacion = detectar_codificacion(muestra)
        self.separador = detectar_separador(muestra.decode(self.codificacion, errors="ignore"))
        with self._abrir() as f:
            self._columnas = _encabezados_unicos(next(csv.reader(f, delimiter=self.separador), []))

    def _abrir(self):
        return self.ruta.open("r", encoding=self.codificacion, newline="")

    def columnas(self, hoja: str | None = None) -> list[str]:
        return list(self._columnas)

    def filas(self, hoja: str | None = None, bloque: int = 2000, limite: int | None = None) -> Iterator[list[FilaNumerada]]:
        actual: list[FilaNumerada] = []
        leidas = 0
        try:
            with self._abrir() as f:
                lector = csv.reader(f, delimiter=self.separador)
                next(lector, None)
                for numero, valores in enumerate(lector, start=2):
                    if not any(v.strip() for v in valores):
                        continue
                    if len(valores) > len(self._columnas) and any(v.strip() for v in valores[len(self._columnas):]):
                        raise ErrorArchivo(f"Fila {numero}: tiene más valores que encabezados.")
                    fila = {c: _limpiar(valores[i]) if i < len(valores) else None for i, c in enumerate(self._columnas)}
                    actual.append((numero, fila))
                    leidas += 1
                    if len(actual) >= bloque:
                        yield actual
                        actual = []
                    if limite and leidas >= limite:
                        break
        except UnicodeDecodeError as exc:
            raise ErrorArchivo(f"El CSV cambia de codificación a mitad del archivo (byte {exc.start}). "
                               "Guárdelo como 'CSV UTF-8'.") from exc
        if actual:
            yield actual

    def contar_filas(self, hoja: str | None = None) -> int:
        with self._abrir() as f:
            lector = csv.reader(f, delimiter=self.separador)
            next(lector, None)
            return sum(1 for valores in lector if any(v.strip() for v in valores))

    def cerrar(self) -> None:
        pass


class LectorXLSX:
    def __init__(self, ruta: Path):
        import openpyxl  # importación diferida

        self.ruta = Path(ruta)
        try:
            self._libro = openpyxl.load_workbook(self.ruta, read_only=True, data_only=True)
        except Exception as exc:  # openpyxl lanza varios tipos según el daño
            raise ErrorArchivo("No se pudo abrir el libro de Excel (¿está dañado o protegido?).") from exc
        self.hojas = list(self._libro.sheetnames)
        self._cache_columnas: dict[str, list[str]] = {}

    def _hoja(self, hoja: str | None):
        if hoja is None:
            if len(self.hojas) != 1:
                raise ErrorArchivo("El libro tiene varias hojas; indique cuál importar: " + ", ".join(self.hojas))
            hoja = self.hojas[0]
        if hoja not in self.hojas:
            raise ErrorArchivo(f"La hoja '{hoja}' no existe. Hojas disponibles: " + ", ".join(self.hojas))
        return self._libro[hoja], hoja

    def columnas(self, hoja: str | None = None) -> list[str]:
        ws, nombre = self._hoja(hoja)
        if nombre not in self._cache_columnas:
            primera = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
            self._cache_columnas[nombre] = _encabezados_unicos(list(primera))
        return list(self._cache_columnas[nombre])

    def filas(self, hoja: str | None = None, bloque: int = 2000, limite: int | None = None) -> Iterator[list[FilaNumerada]]:
        ws, nombre = self._hoja(hoja)
        columnas = self.columnas(nombre)
        actual: list[FilaNumerada] = []
        leidas = 0
        for numero, valores in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if not any(v is not None and str(v).strip() for v in valores):
                continue
            fila = {c: _limpiar(valores[i]) if i < len(valores) else None for i, c in enumerate(columnas)}
            actual.append((numero, fila))
            leidas += 1
            if len(actual) >= bloque:
                yield actual
                actual = []
            if limite and leidas >= limite:
                break
        if actual:
            yield actual

    def contar_filas(self, hoja: str | None = None) -> int | None:
        """Aproximado: lo que declara la hoja (puede incluir filas vacías al final)."""
        ws, _ = self._hoja(hoja)
        return (ws.max_row - 1) if ws.max_row else None

    def cerrar(self) -> None:
        self._libro.close()


def abrir_tabla(ruta: Path) -> LectorCSV | LectorXLSX:
    sufijo = Path(ruta).suffix.lower()
    if sufijo == ".csv":
        return LectorCSV(ruta)
    if sufijo == ".xlsx":
        return LectorXLSX(ruta)
    raise ErrorArchivo(f"No es un archivo tabular: {sufijo}")
