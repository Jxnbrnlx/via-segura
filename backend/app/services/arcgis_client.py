"""Cliente del servicio ArcGIS REST de la Secretaría Distrital de Movilidad (SIMUR).

Servicio: .../Accidentalidad/AccidentalidadAnalisis/FeatureServer
Verificado en los metadatos (16-11-2026): MaxRecordCount = 2000; cada capa/tabla acepta JSON,
geoJSON y PBF; soporta paginación (resultOffset/resultRecordCount), orderBy, estadísticas y
valores distintos; todas las relaciones con la capa 2 (ACCIDENTE) usan el campo FORMULARIO.

Decisiones:
- Las consultas usan POST (formulario) para no chocar con el límite de largo de URL cuando se
  piden muchos FORMULARIO a la vez.
- `outFields` siempre es una lista explícita. Se rechazan "*" y los campos con datos personales
  (PLACA, FECHA_NACIMIENTO, CODIGO_ACCIDENTADO): ni siquiera se solicitan al servidor.
- ArcGIS suele responder los errores con HTTP 200 y un cuerpo {"error": {...}}: se detecta.
- Reintentos con espera creciente (exponencial con tope) ante caídas de red, tiempos de espera,
  HTTP 429/5xx y errores ArcGIS transitorios.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterator, Sequence

import httpx

log = logging.getLogger("via_segura.arcgis")

CAPA_MUERTO, CAPA_LESIONADO, CAPA_ACCIDENTE = 0, 1, 2
TABLA_ACTOR_VIAL, TABLA_CAUSA, TABLA_VEHICULO, TABLA_VIA = 3, 4, 5, 6

# Campos con datos personales que NUNCA se solicitan.
CAMPOS_PROHIBIDOS = frozenset({"PLACA", "FECHA_NACIMIENTO", "CODIGO_ACCIDENTADO"})

# Campos que solicita la sincronización (lista explícita; verificados en los metadatos).
CAMPOS_ACCIDENTE = (
    "OBJECTID", "FORMULARIO", "CODIGO_ACCIDENTE", "FECHA_OCURRENCIA_ACC", "HORA_OCURRENCIA_ACC",
    "ANO_OCURRENCIA_ACC", "MES_OCURRENCIA_ACC", "DIA_OCURRENCIA_ACC", "DIRECCION", "GRAVEDAD",
    "CLASE_ACC", "LOCALIDAD", "MUNICIPIO", "LATITUD", "LONGITUD", "CIV", "PK_CALZADA", "BARRIO",
    "MVINOMBRE",
)
CAMPOS_ACTOR_VIAL = (
    "FORMULARIO", "CODIGO_VICTIMA", "CODIGO_VEHICULO", "CONDICION", "CONDICION_A", "ESTADO",
    "MUERTE_POSTERIOR", "GENERO", "EDAD", "CODIGO",
)
CAMPOS_VEHICULO = ("FORMULARIO", "CODIGO_VEHICULO", "CLASE", "SERVICIO", "MODALIDAD")
CAMPOS_CAUSA = ("FORMULARIO", "CODIGO_ACCIDENTE", "CODIGO_VEHICULO", "CODIGO_CAUSA", "NOMBRE", "TIPO_CAUSA")

_HTTP_REINTENTABLE = {429, 500, 502, 503, 504}
_ARCGIS_REINTENTABLE = {429, 500, 502, 503, 504}


class ErrorArcGIS(Exception):
    """Error al consultar el servicio. `mensaje` es legible y no contiene secretos."""

    def __init__(self, mensaje: str, *, codigo: int | None = None, detalles: Sequence[str] = (),
                 reintentable: bool = False):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo
        self.detalles = list(detalles)
        self.reintentable = reintentable


class ServicioNoDisponible(ErrorArcGIS):
    """El servicio no respondió (red, tiempo de espera, 5xx) tras agotar los reintentos."""


def validar_campos(campos: Sequence[str]) -> list[str]:
    """Exige una lista explícita de campos y rechaza los campos con datos personales."""
    if isinstance(campos, str):
        raise ValueError("outFields debe ser una lista explícita de campos, no un texto.")
    lista = [c.strip() for c in campos if c and c.strip()]
    if not lista or "*" in lista:
        raise ValueError("outFields debe ser una lista explícita de campos (no se permite '*').")
    prohibidos = sorted({c.upper() for c in lista} & CAMPOS_PROHIBIDOS)
    if prohibidos:
        raise ValueError(f"Campos con datos personales no permitidos: {', '.join(prohibidos)}")
    return lista


def sql_lista_texto(valores: Sequence[str]) -> str:
    """Lista SQL de textos con comillas escapadas: ('A1', 'B''2')."""
    return "(" + ", ".join("'" + str(v).replace("'", "''") + "'" for v in valores) + ")"


class ClienteArcGIS:
    def __init__(
        self,
        base_url: str,
        *,
        pagina: int = 2000,
        timeout_s: float = 60,
        reintentos: int = 4,
        espera_base_s: float = 1.5,
        espera_max_s: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        dormir: Callable[[float], None] = time.sleep,
    ):
        if not 1 <= pagina <= 2000:
            raise ValueError("El tamaño de página debe estar entre 1 y 2000 (MaxRecordCount del servicio).")
        self.base_url = base_url.rstrip("/")
        self.pagina = pagina
        self.reintentos = max(0, reintentos)
        self.espera_base_s = espera_base_s
        self.espera_max_s = espera_max_s
        self._dormir = dormir
        self._http = httpx.Client(
            timeout=httpx.Timeout(timeout_s),
            transport=transport,
            follow_redirects=True,
            headers={"User-Agent": "VIA-SEGURA/0.2 (aplicacion academica)", "Accept": "application/json"},
        )
        self.peticiones = 0  # contador para el registro de la importación

    # ------------------------------------------------------------------ ciclo de vida
    @classmethod
    def desde_configuracion(cls, **extra) -> "ClienteArcGIS":
        from ..config import get_settings  # importación diferida: este módulo no exige .env

        cfg = get_settings()
        opciones = {"pagina": cfg.arcgis_pagina, "timeout_s": cfg.arcgis_timeout_s, "reintentos": cfg.arcgis_reintentos}
        opciones.update(extra)
        return cls(cfg.arcgis_base_url, **opciones)

    def cerrar(self) -> None:
        self._http.close()

    def __enter__(self) -> "ClienteArcGIS":
        return self

    def __exit__(self, *_exc) -> None:
        self.cerrar()

    # ------------------------------------------------------------------ transporte
    def _espera(self, intento: int) -> float:
        return min(self.espera_max_s, self.espera_base_s * (2 ** intento))

    def _peticion(self, metodo: str, url: str, datos: dict[str, str]) -> dict:
        ultimo_error: ErrorArcGIS | None = None
        for intento in range(self.reintentos + 1):
            self.peticiones += 1
            try:
                if metodo == "GET":
                    respuesta = self._http.get(url, params=datos)
                else:
                    respuesta = self._http.post(url, data=datos)
            except httpx.TimeoutException:
                ultimo_error = ServicioNoDisponible(
                    "El servicio ArcGIS no respondió dentro del tiempo de espera.", reintentable=True)
            except httpx.TransportError as exc:
                ultimo_error = ServicioNoDisponible(
                    f"No fue posible conectarse al servicio ArcGIS ({type(exc).__name__}).", reintentable=True)
            else:
                ultimo_error = self._interpretar(respuesta)
                if ultimo_error is None:
                    return respuesta.json()

            if not ultimo_error.reintentable or intento >= self.reintentos:
                break
            espera = self._espera(intento)
            log.warning("ArcGIS: %s Reintento %d de %d en %.1f s.", ultimo_error.mensaje, intento + 1,
                        self.reintentos, espera)
            self._dormir(espera)

        assert ultimo_error is not None
        if ultimo_error.reintentable:
            raise ServicioNoDisponible(
                f"{ultimo_error.mensaje} Se agotaron {self.reintentos} reintentos.",
                codigo=ultimo_error.codigo, detalles=ultimo_error.detalles)
        raise ultimo_error

    @staticmethod
    def _interpretar(respuesta: httpx.Response) -> ErrorArcGIS | None:
        """None si la respuesta es un JSON válido sin error; si no, el error correspondiente."""
        if respuesta.status_code in _HTTP_REINTENTABLE:
            return ServicioNoDisponible(f"El servicio ArcGIS respondió HTTP {respuesta.status_code}.",
                                        codigo=respuesta.status_code, reintentable=True)
        if respuesta.status_code >= 400:
            return ErrorArcGIS(f"El servicio ArcGIS respondió HTTP {respuesta.status_code}.",
                               codigo=respuesta.status_code)
        try:
            cuerpo = respuesta.json()
        except ValueError:
            # Página HTML de mantenimiento o respuesta cortada: se trata como caída temporal.
            return ServicioNoDisponible("El servicio ArcGIS devolvió una respuesta que no es JSON.",
                                        reintentable=True)
        if not isinstance(cuerpo, dict):
            return ErrorArcGIS("El servicio ArcGIS devolvió un JSON con estructura inesperada.")
        if "error" in cuerpo:
            error = cuerpo.get("error") or {}
            codigo = error.get("code")
            detalles = [str(d) for d in (error.get("details") or [])][:5]
            mensaje = f"ArcGIS informó un error ({codigo}): {error.get('message') or 'sin mensaje'}."
            return ErrorArcGIS(mensaje, codigo=codigo, detalles=detalles,
                               reintentable=codigo in _ARCGIS_REINTENTABLE)
        return None

    def _url(self, capa: int | None, accion: str | None = None) -> str:
        partes = [self.base_url]
        if capa is not None:
            partes.append(str(int(capa)))
        if accion:
            partes.append(accion)
        return "/".join(partes)

    # ------------------------------------------------------------------ metadatos
    def metadatos_servicio(self) -> dict:
        return self._peticion("GET", self._url(None), {"f": "json"})

    def metadatos(self, capa: int) -> dict:
        return self._peticion("GET", self._url(capa), {"f": "json"})

    def campos_de(self, capa: int) -> dict[str, str]:
        """Nombre de campo -> tipo esri, según los metadatos de la capa."""
        return {c["name"]: c.get("type", "") for c in self.metadatos(capa).get("fields", [])}

    # ------------------------------------------------------------------ consultas
    def _consultar(self, capa: int, parametros: dict[str, object]) -> dict:
        datos = {"f": "json"}
        for k, v in parametros.items():
            if v is None:
                continue
            datos[k] = v if isinstance(v, str) else json.dumps(v) if isinstance(v, (list, dict)) else str(v)
        return self._peticion("POST", self._url(capa, "query"), datos)

    def contar(self, capa: int, where: str = "1=1") -> int:
        cuerpo = self._consultar(capa, {"where": where, "returnCountOnly": "true"})
        if "count" not in cuerpo:
            raise ErrorArcGIS("La respuesta de conteo no contiene 'count'.")
        return int(cuerpo["count"])

    def consultar(
        self,
        capa: int,
        where: str,
        campos: Sequence[str],
        *,
        desplazamiento: int = 0,
        cantidad: int | None = None,
        orden: str = "OBJECTID ASC",
        geometria: bool = False,
        sr_salida: int | None = None,
    ) -> tuple[list[dict], bool]:
        """Una página. Devuelve (registros, excedio_limite). Con geometría, cada registro trae
        además la clave '_geometria' = {'x': lon, 'y': lat}."""
        lista = validar_campos(campos)
        cuerpo = self._consultar(capa, {
            "where": where,
            "outFields": ",".join(lista),
            "orderByFields": orden,
            "resultOffset": desplazamiento,
            "resultRecordCount": cantidad or self.pagina,
            "returnGeometry": "true" if geometria else "false",
            "outSR": sr_salida,
        })
        if "features" not in cuerpo:
            raise ErrorArcGIS("La respuesta de la consulta no contiene 'features'.")
        registros = []
        for f in cuerpo["features"]:
            atributos = dict(f.get("attributes") or {})
            for prohibido in CAMPOS_PROHIBIDOS:  # defensa adicional: si llegara, se descarta
                atributos.pop(prohibido, None)
            if geometria and f.get("geometry"):
                atributos["_geometria"] = {"x": f["geometry"].get("x"), "y": f["geometry"].get("y")}
            registros.append(atributos)
        return registros, bool(cuerpo.get("exceededTransferLimit"))

    def iterar_paginas(
        self,
        capa: int,
        where: str,
        campos: Sequence[str],
        *,
        geometria: bool = False,
        orden: str = "OBJECTID ASC",
        inicio: int = 0,
    ) -> Iterator[list[dict]]:
        """Recorre todas las páginas ordenando por OBJECTID (orden estable para paginar)."""
        desplazamiento = inicio
        while True:
            registros, excedido = self.consultar(capa, where, campos, desplazamiento=desplazamiento,
                                                 orden=orden, geometria=geometria)
            if not registros:
                return
            yield registros
            desplazamiento += len(registros)
            if not excedido and len(registros) < self.pagina:
                return

    def consultar_todo(self, capa: int, where: str, campos: Sequence[str]) -> list[dict]:
        resultado: list[dict] = []
        for pagina in self.iterar_paginas(capa, where, campos):
            resultado.extend(pagina)
        return resultado

    def estadisticas(
        self,
        capa: int,
        estadisticas: list[dict],
        *,
        where: str = "1=1",
        agrupar_por: Sequence[str] = (),
        having: str | None = None,
        orden: str | None = None,
    ) -> list[dict]:
        for e in estadisticas:
            if str(e.get("onStatisticField", "")).upper() in CAMPOS_PROHIBIDOS:
                raise ValueError("No se calculan estadísticas sobre campos con datos personales.")
        if {c.upper() for c in agrupar_por} & CAMPOS_PROHIBIDOS:
            raise ValueError("No se agrupa por campos con datos personales.")
        cuerpo = self._consultar(capa, {
            "where": where,
            "outStatistics": estadisticas,
            "groupByFieldsForStatistics": ",".join(agrupar_por) if agrupar_por else None,
            "having": having,
            "orderByFields": orden,
            "returnGeometry": "false",
        })
        if "features" not in cuerpo:
            raise ErrorArcGIS("La respuesta de estadísticas no contiene 'features'.")
        return [dict(f.get("attributes") or {}) for f in cuerpo["features"]]

    def conteo_por_valor(self, capa: int, campo: str, where: str = "1=1") -> dict[object, int]:
        """Valores distintos con su conteo (estadística agrupada; más fiable que returnDistinctValues,
        que en este servicio no siempre deduplicó al probarlo con LOCALIDAD)."""
        filas = self.estadisticas(
            capa,
            [{"statisticType": "count", "onStatisticField": "OBJECTID", "outStatisticFieldName": "n"}],
            where=where, agrupar_por=[campo],
        )
        resultado: dict[object, int] = {}
        for fila in filas:
            n = next((v for k, v in fila.items() if k.lower() == "n"), 0)
            valor = next((v for k, v in fila.items() if k.upper() == campo.upper()), None)
            resultado[valor] = int(n or 0)
        return resultado

    def valor_extremo(self, capa: int, campo: str, *, maximo: bool = True, where: str = "1=1") -> object:
        """Valor máximo (o mínimo) de un campo, ordenando y pidiendo un solo registro."""
        filtro = f"({where}) AND {campo} IS NOT NULL"
        registros, _ = self.consultar(capa, filtro, [campo], cantidad=1,
                                      orden=f"{campo} {'DESC' if maximo else 'ASC'}")
        return registros[0].get(campo) if registros else None
