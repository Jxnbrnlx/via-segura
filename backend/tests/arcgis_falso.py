"""Servidor ArcGIS SIMULADO para pruebas (sin red). Todos los datos son SINTÉTICOS de prueba.

Imita lo verificado del servicio real: errores con HTTP 200 + {"error": ...}, paginación con
resultOffset/resultRecordCount y exceededTransferLimit, outFields que limita los atributos
devueltos, fechas en milisegundos como medianoche UTC y relaciones por FORMULARIO.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from urllib.parse import parse_qsl

import httpx

CAMPOS_CAPA = {
    2: ["OBJECTID", "FORMULARIO", "CODIGO_ACCIDENTE", "FECHA_OCURRENCIA_ACC", "HORA_OCURRENCIA_ACC",
        "ANO_OCURRENCIA_ACC", "MES_OCURRENCIA_ACC", "DIA_OCURRENCIA_ACC", "DIRECCION", "GRAVEDAD", "CLASE_ACC",
        "LOCALIDAD", "MUNICIPIO", "FECHA_HORA_ACC", "LATITUD", "LONGITUD", "CIV", "PK_CALZADA", "BARRIO",
        "MVINOMBRE", "DISTANCIA_VIA"],
    3: ["OBJECTID", "FORMULARIO", "CODIGO_ACCIDENTADO", "FECHA_OCURRENCIA", "CODIGO_VICTIMA", "CODIGO_VEHICULO",
        "CONDICION", "ESTADO", "MUERTE_POSTERIOR", "FECHA_POSTERIOR_MUERTE", "GENERO", "FECHA_NACIMIENTO", "EDAD",
        "CODIGO", "CONDICION_A"],
    4: ["OBJECTID", "FORMULARIO", "CODIGO_ACCIDENTE", "CODIGO_VEHICULO", "CODIGO_CAUSA", "NOMBRE", "TIPO",
        "DESCRIPCION2", "TIPO_CAUSA", "CODIGO", "CODIGO_AC_VH"],
    5: ["OBJECTID", "FORMULARIO", "PLACA", "CODIGO_VEHICULO", "COD_CLASE", "CLASE", "SERVICIO", "MODALIDAD",
        "ENFUGA", "CODIGO"],
}

_DIAS = ("LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO")
_MESES = ("ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE",
          "NOVIEMBRE", "DICIEMBRE")


def ms(fecha: date) -> int:
    """Fecha local -> milisegundos de la medianoche UTC (como publica el servicio real)."""
    return int(datetime(fecha.year, fecha.month, fecha.day, tzinfo=timezone.utc).timestamp() * 1000)


def accidente(oid: int, codigo: int, fecha: date, *, localidad="KENNEDY", gravedad="CON HERIDOS",
              clase="CHOQUE", lat=4.63, lon=-74.15, hora="14:30:00", formulario=None) -> dict:
    return {
        "OBJECTID": oid, "FORMULARIO": formulario or f"PR{codigo:07d}", "CODIGO_ACCIDENTE": float(codigo),
        "FECHA_OCURRENCIA_ACC": ms(fecha), "HORA_OCURRENCIA_ACC": hora, "ANO_OCURRENCIA_ACC": float(fecha.year),
        "MES_OCURRENCIA_ACC": _MESES[fecha.month - 1], "DIA_OCURRENCIA_ACC": _DIAS[fecha.weekday()],
        "DIRECCION": "KR 1 - CL 1 (PRUEBA)", "GRAVEDAD": gravedad, "CLASE_ACC": clase, "LOCALIDAD": localidad,
        "MUNICIPIO": "BOGOTA DC", "FECHA_HORA_ACC": ms(fecha), "LATITUD": lat, "LONGITUD": lon, "CIV": 1000 + oid,
        "PK_CALZADA": 2000 + oid, "BARRIO": "BARRIO DE PRUEBA", "MVINOMBRE": "VIA DE PRUEBA", "DISTANCIA_VIA": 1.0,
    }


def actor(formulario: str, codigo: int, victima: int, vehiculo: int | None, *, estado="HERIDO",
          condicion="CONDUCTOR", genero="MASCULINO", edad=30.0) -> dict:
    return {
        "FORMULARIO": formulario, "CODIGO_ACCIDENTADO": f"PERSONA-SECRETA-{codigo}-{victima}",
        "FECHA_OCURRENCIA": 0, "CODIGO_VICTIMA": float(victima),
        "CODIGO_VEHICULO": None if vehiculo is None else float(vehiculo), "CONDICION": condicion,
        "ESTADO": estado, "MUERTE_POSTERIOR": "N", "FECHA_POSTERIOR_MUERTE": None, "GENERO": genero,
        "FECHA_NACIMIENTO": 0, "EDAD": edad, "CODIGO": f"{codigo}-{vehiculo or 0}", "CONDICION_A": condicion,
    }


def vehiculo(formulario: str, codigo: int, numero: int, clase="AUTOMOVIL") -> dict:
    return {"FORMULARIO": formulario, "PLACA": f"PLACA{numero}SECRETA", "CODIGO_VEHICULO": float(numero),
            "COD_CLASE": "1", "CLASE": clase, "SERVICIO": "PARTICULAR", "MODALIDAD": None, "ENFUGA": "N",
            "CODIGO": f"{codigo}-{numero}"}


def causa(formulario: str, codigo: int, numero: int, codigo_causa="102") -> dict:
    return {"FORMULARIO": formulario, "CODIGO_ACCIDENTE": float(codigo), "CODIGO_VEHICULO": float(numero),
            "CODIGO_CAUSA": codigo_causa, "NOMBRE": "CAUSA DE PRUEBA", "TIPO": "CG", "DESCRIPCION2": None,
            "TIPO_CAUSA": None, "CODIGO": f"{codigo}-{numero}-{codigo_causa}", "CODIGO_AC_VH": f"{codigo}-{numero}"}


def conjunto_basico(n: int = 10, inicio: date = date(2025, 3, 1)) -> dict[int, list[dict]]:
    """n siniestros sintéticos, cada uno con 2 personas, 1 vehículo y 1 causa (repetida a propósito)."""
    from datetime import timedelta

    capas: dict[int, list[dict]] = {2: [], 3: [], 4: [], 5: []}
    for i in range(n):
        codigo = 9_000_000 + i
        f = f"PR{codigo:07d}"
        capas[2].append(accidente(i + 1, codigo, inicio + timedelta(days=i * 3)))
        capas[3].append(actor(f, codigo, 0, 1))
        capas[3].append(actor(f, codigo, 1, None, condicion="PEATON", estado="HERIDO", genero="FEMENINO", edad=2021.0))
        capas[5].append(vehiculo(f, codigo, 1))
        capas[4].append(causa(f, codigo, 1))
        capas[4].append(causa(f, codigo, 1))  # duplicado idéntico, como en VM_ACC_CAUSA
    return capas


class ServidorArcGISFalso:
    def __init__(self, capas: dict[int, list[dict]], *, max_registros: int = 2000,
                 campos: dict[int, list[str]] | None = None, devolver_todo: bool = False):
        self.capas = capas
        self.max_registros = max_registros
        self.campos = campos or CAMPOS_CAPA
        self.devolver_todo = devolver_todo  # simula un servidor que ignora outFields
        self.peticiones: list[tuple[str, str, dict]] = []
        self.fallas: list = []  # cola: cada elemento es None o una función request -> Response (o que lanza)
        self.falla_permanente = None

    def transporte(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._manejar)

    # ---------------------------------------------------------------- utilidades de prueba
    def consultas(self, capa: int | None = None) -> list[dict]:
        return [p for _m, ruta, p in self.peticiones
                if ruta.endswith("/query") and (capa is None or ruta.split("/")[-2] == str(capa))]

    # ---------------------------------------------------------------- despacho
    def _manejar(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        if request.method == "POST":
            params.update(dict(parse_qsl(request.content.decode("utf-8"))))
        self.peticiones.append((request.method, request.url.path, params))
        if self.falla_permanente is not None:
            return self.falla_permanente(request)
        if self.fallas:
            falla = self.fallas.pop(0)
            if falla is not None:
                return falla(request)
        partes = request.url.path.rstrip("/").split("/")
        if partes[-1] == "query":
            return self._query(int(partes[-2]), params)
        if partes[-1].isdigit():
            capa = int(partes[-1])
            return httpx.Response(200, json={
                "id": capa, "name": f"CAPA {capa}", "maxRecordCount": 2000,
                "fields": [{"name": c, "type": "esriFieldTypeString"} for c in self.campos.get(capa, [])]})
        return httpx.Response(200, json={"layers": [{"id": i, "name": f"CAPA {i}"} for i in (0, 1, 2)],
                                         "tables": [{"id": i, "name": f"TABLA {i}"} for i in (3, 4, 5, 6)]})

    def _query(self, capa: int, p: dict) -> httpx.Response:
        try:
            filas = [r for r in self.capas.get(capa, []) if self._cumple(r, p.get("where", "1=1"))]
        except ValueError as exc:
            return httpx.Response(200, json={"error": {"code": 400, "message": "Invalid query",
                                                       "details": [str(exc)]}})
        if p.get("returnCountOnly") == "true":
            return httpx.Response(200, json={"count": len(filas)})
        orden = (p.get("orderByFields") or "OBJECTID ASC").split()
        campo_orden, descendente = orden[0], len(orden) > 1 and orden[1].upper() == "DESC"
        filas.sort(key=lambda r: (r.get(campo_orden) is None, r.get(campo_orden) or 0), reverse=descendente)
        desplazamiento = int(p.get("resultOffset", 0))
        cantidad = min(int(p.get("resultRecordCount", self.max_registros)), self.max_registros)
        pagina = filas[desplazamiento:desplazamiento + cantidad]
        campos = [c.strip() for c in p.get("outFields", "OBJECTID").split(",")]
        features = [{"attributes": dict(r) if self.devolver_todo else {c: r.get(c) for c in campos if c in r}}
                    for r in pagina]
        cuerpo: dict = {"features": features}
        if desplazamiento + cantidad < len(filas):
            cuerpo["exceededTransferLimit"] = True
        return httpx.Response(200, json=cuerpo)

    def _cumple(self, r: dict, where: str) -> bool:
        where = where.strip()
        if where == "1=1":
            return True
        m = re.fullmatch(r"\((.*)\) AND (\w+) IS NOT NULL", where)
        if m:
            return self._cumple(r, m.group(1)) and r.get(m.group(2)) is not None
        m = re.fullmatch(r"FECHA_OCURRENCIA_ACC >= DATE '(\d{4})-(\d{2})-(\d{2})'", where)
        if m:
            limite = ms(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
            return r.get("FECHA_OCURRENCIA_ACC") is not None and r["FECHA_OCURRENCIA_ACC"] >= limite
        m = re.fullmatch(r"FORMULARIO IN \((.*)\)", where, flags=re.S)
        if m:
            valores = {v.replace("''", "'") for v in re.findall(r"'((?:[^']|'')*)'", m.group(1))}
            return r.get("FORMULARIO") in valores
        raise ValueError(f"where no soportado por el simulador: {where}")


# Fallas reutilizables ---------------------------------------------------------------------

def falla_conexion(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("conexión rechazada (simulada)", request=request)


def falla_http(codigo: int):
    return lambda request: httpx.Response(codigo, text="error simulado")


def falla_json_200(codigo: int = 400, mensaje: str = "Unable to complete operation."):
    return lambda request: httpx.Response(200, json={"error": {"code": codigo, "message": mensaje,
                                                               "details": ["detalle simulado"]}})
