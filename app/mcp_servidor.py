"""Servidor MCP (Model Context Protocol) de QuoteTrack: deja a Claude consultar —y, si se permite, crear— clientes,
cotizaciones y facturas de la base de datos de la aplicación.

Habla JSON-RPC por entrada/salida estándar (un mensaje JSON por línea), sin dependencias externas ni Qt:

    QuoteTrackMCP.exe [--db RUTA] [--escritura] [--sin-latido]
    python -m app.mcp_servidor [--db RUTA] [--escritura] [--sin-latido]

Mientras corre, escribe un latido en `mcp_estado\\` (junto a la base de datos) para que la aplicación muestre el
indicador «MCP conectado»; `--sin-latido` lo desactiva.

Por defecto es de SOLO LECTURA. Con `--escritura` (o QUOTETRACK_MCP_ESCRITURA=1) se habilitan también las
herramientas que crean clientes y cotizaciones, cambian su estado, generan facturas y las marcan como pagadas.
Nunca borra nada. La base de datos es la de la aplicación (%APPDATA%\\QuoteTrack\\quotetrack.db en el ejecutable)
o la que se indique con --db / QUOTETRACK_DB."""
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

from app import calculo, db, documento, mcp_estado, pdf, texto_rico
from app.calculo import Cargo, Linea

VERSION = "1.0"
PROTOCOLO = "2024-11-05"
INSTRUCCIONES = (
    "QuoteTrack: cotizaciones y facturas de un ingeniero estructural en Panamá (moneda B/., ITBMS 7% o exento). "
    "Identifica cotizaciones y facturas por su número (COT-2026-0001, FAC-2026-0001). Empieza con "
    "`estadisticas` o `listar_cotizaciones`. Los montos están en balboas (B/.).")


class ErrorHerramienta(Exception):
    """Error que se devuelve a Claude como resultado de la herramienta (no rompe el protocolo)."""


# ----------------------------------------------------------------------------- utilidades
def _dinero(v) -> float:
    return round(float(v or 0), 2)


def _conexion():
    if not Path(db.DB_PATH).exists():
        raise ErrorHerramienta(
            f"No se encontró la base de datos en {db.DB_PATH}. Abre QuoteTrack al menos una vez, o indica la ruta "
            "con --db o con la variable QUOTETRACK_DB.")
    return db.get_connection()


def _id_cotizacion(conn, numero: str) -> int:
    f = conn.execute("SELECT id FROM cotizaciones WHERE numero = ?", ((numero or "").strip(),)).fetchone()
    if f is None:
        raise ErrorHerramienta(f"No existe la cotización «{numero}».")
    return f["id"]


def _fila_factura(conn, numero: str):
    f = conn.execute("SELECT * FROM facturas WHERE numero = ?", ((numero or "").strip(),)).fetchone()
    if f is None:
        raise ErrorHerramienta(f"No existe la factura «{numero}».")
    return f


def _cliente(conn, texto) -> int:
    """Id de un cliente por nombre (exacto sin distinguir mayúsculas, o parte única del nombre) o por id."""
    texto = str(texto or "").strip()
    if not texto:
        raise ErrorHerramienta("Indica el cliente.")
    if texto.isdigit():
        f = conn.execute("SELECT id FROM clientes WHERE id = ?", (int(texto),)).fetchone()
        if f:
            return f["id"]
    exacto = conn.execute("SELECT id FROM clientes WHERE lower(nombre) = lower(?)", (texto,)).fetchall()
    if len(exacto) == 1:
        return exacto[0]["id"]
    parecidos = conn.execute("SELECT id, nombre FROM clientes WHERE nombre LIKE ? ORDER BY nombre",
                             (f"%{texto}%",)).fetchall()
    if len(parecidos) == 1:
        return parecidos[0]["id"]
    if not parecidos:
        raise ErrorHerramienta(f"No existe un cliente que se parezca a «{texto}». Créalo con crear_cliente.")
    raise ErrorHerramienta("Hay varios clientes que coinciden: " + "; ".join(p["nombre"] for p in parecidos)
                           + ". Usa el nombre completo.")


def _empresa(conn, texto):
    texto = str(texto or "").strip()
    if not texto:
        return None
    for e in db.listar_empresas(conn):
        if e["nombre"].lower() == texto.lower() or str(e["id"]) == texto:
            return e["id"]
    raise ErrorHerramienta(f"No existe la empresa «{texto}». Empresas: "
                           + ", ".join(e["nombre"] for e in db.listar_empresas(conn)))


def _plano(titulo, descripcion) -> str:
    return texto_rico.a_texto_plano(texto_rico.con_titulo(titulo, descripcion))


def _numero(args, clave, por_defecto=None, minimo=None):
    v = args.get(clave, por_defecto)
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise ErrorHerramienta(f"«{clave}» debe ser un número.")
    if minimo is not None and v < minimo:
        raise ErrorHerramienta(f"«{clave}» no puede ser menor que {minimo:g}.")
    return v


# ----------------------------------------------------------------------------- herramientas de lectura
def estadisticas(args):
    conn = _conexion()
    try:
        cot = conn.execute("SELECT estado, COUNT(*) AS n, COALESCE(SUM(total), 0) AS t FROM cotizaciones "
                           "GROUP BY estado").fetchall()
        fac = conn.execute("SELECT estado_pago AS estado, COUNT(*) AS n, COALESCE(SUM(total), 0) AS t FROM facturas "
                           "GROUP BY estado_pago").fetchall()
        top = conn.execute(
            "SELECT cl.nombre AS cliente, COUNT(*) AS cotizaciones, COALESCE(SUM(c.total), 0) AS total "
            "FROM cotizaciones c JOIN clientes cl ON cl.id = c.cliente_id GROUP BY cl.id ORDER BY total DESC LIMIT 5"
        ).fetchall()
        return {
            "cotizaciones_por_estado": {f["estado"]: {"cantidad": f["n"], "total": _dinero(f["t"])} for f in cot},
            "facturas_por_estado": {f["estado"]: {"cantidad": f["n"], "total": _dinero(f["t"])} for f in fac},
            "por_cobrar": _dinero(sum(f["t"] for f in fac if f["estado"] in ("pendiente", "vencida"))),
            "cobrado": _dinero(sum(f["t"] for f in fac if f["estado"] == "pagada")),
            "clientes": conn.execute("SELECT COUNT(*) FROM clientes").fetchone()[0],
            "mejores_clientes": [{"cliente": f["cliente"], "cotizaciones": f["cotizaciones"], "total": _dinero(f["total"])}
                                 for f in top],
        }
    finally:
        conn.close()


def listar_clientes(args):
    conn = _conexion()
    try:
        buscar = str(args.get("buscar") or "").strip()
        filas = conn.execute(
            "SELECT cl.id, cl.nombre, cl.identificacion, cl.contacto, "
            "(SELECT COUNT(*) FROM cotizaciones c WHERE c.cliente_id = cl.id) AS cotizaciones "
            "FROM clientes cl WHERE cl.nombre LIKE ? OR cl.identificacion LIKE ? ORDER BY cl.nombre",
            (f"%{buscar}%", f"%{buscar}%")).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def listar_cotizaciones(args):
    conn = _conexion()
    try:
        cond, params = [], []
        if args.get("cliente"):
            cond.append("cl.nombre LIKE ?")
            params.append(f"%{args['cliente']}%")
        if args.get("estado"):
            cond.append("c.estado = ?")
            params.append(args["estado"])
        if args.get("buscar"):
            cond.append("(c.numero LIKE ? OR c.proyecto LIKE ? OR cl.nombre LIKE ?)")
            params += [f"%{args['buscar']}%"] * 3
        limite = int(_numero(args, "limite", 50, 1))
        filas = conn.execute(
            "SELECT c.numero, cl.nombre AS cliente, c.proyecto, e.nombre AS empresa, c.fecha, c.estado, c.total "
            "FROM cotizaciones c JOIN clientes cl ON cl.id = c.cliente_id LEFT JOIN empresas e ON e.id = c.empresa_id "
            + ("WHERE " + " AND ".join(cond) if cond else "") + " ORDER BY c.id DESC LIMIT ?", (*params, limite)).fetchall()
        return [{**dict(f), "total": _dinero(f["total"])} for f in filas]
    finally:
        conn.close()


def obtener_cotizacion(args):
    conn = _conexion()
    try:
        cid = _id_cotizacion(conn, args.get("numero"))
        cot = conn.execute(
            "SELECT c.*, cl.nombre AS cliente, cl.identificacion, cl.contacto, e.nombre AS empresa "
            "FROM cotizaciones c JOIN clientes cl ON cl.id = c.cliente_id LEFT JOIN empresas e ON e.id = c.empresa_id "
            "WHERE c.id = ?", (cid,)).fetchone()
        lineas, t = db.calcular_cotizacion(cid, conn)
        cods, imps = calculo.codigos(lineas), calculo.importes(lineas)
        items = []
        for i, l in enumerate(lineas):
            fila = {"codigo": cods[i], "tipo": "grupo" if l.es_grupo else "item", "titulo": l.titulo,
                    "descripcion": texto_rico.a_texto_plano(l.descripcion), "importe": _dinero(imps[i])}
            if not l.es_grupo:
                fila.update({"unidad": l.unidad, "cantidad": l.cantidad, "precio_unitario": _dinero(l.precio_mostrado),
                             "modalidad": l.modalidad, "aplica_itbms": l.aplica_itbms})
            items.append(fila)
        cargos = [{"concepto": c.concepto, "tipo": c.tipo, "valor": c.valor, "monto": _dinero(m),
                   "se_aplica_sobre": calculo.nombre_base(c), "diluido_en_items": c in [d for d, _m in t.diluidos]}
                  for c, m in t.cargos + t.diluidos]
        return {
            "numero": cot["numero"], "estado": cot["estado"], "fecha": cot["fecha"], "cliente": cot["cliente"],
            "identificacion": cot["identificacion"], "contacto": cot["contacto"], "empresa": cot["empresa"],
            "proyecto": cot["proyecto"], "items": items, "costos_adicionales": cargos,
            "totales": {"subtotal": _dinero(t.subtotal), "costos_adicionales": _dinero(t.cargos_total),
                        "itbms": _dinero(t.itbms), "total": _dinero(t.total)},
            "notas": cot["notas"], "facturacion": db.resumen_facturacion(cid, conn),
            "facturas": [f["numero"] for f in conn.execute(
                "SELECT numero FROM facturas WHERE cotizacion_id = ? ORDER BY id", (cid,))],
        }
    finally:
        conn.close()


def resumen_cotizacion(args):
    conn = _conexion()
    try:
        cid = _id_cotizacion(conn, args.get("numero"))
        lineas, _t = db.calcular_cotizacion(cid, conn)
        filas = calculo.resumen(lineas, db.obtener_cargos(cid, conn), db.tasa_de_cotizacion(cid, conn),
                                db.obtener_config_apu(cid, conn))
        total = next((m for _e, m, s in filas if s == "total"), 0) or 0
        return [{"concepto": e, "monto": None if m is None else _dinero(m),
                 "porcentaje_del_total": None if m is None or not total else round(m / total * 100, 1), "tipo": s}
                for e, m, s in filas]
    finally:
        conn.close()


def listar_facturas(args):
    conn = _conexion()
    try:
        cond, params = [], []
        if args.get("cliente"):
            cond.append("cl.nombre LIKE ?")
            params.append(f"%{args['cliente']}%")
        if args.get("estado"):
            cond.append("f.estado_pago = ?")
            params.append(args["estado"])
        if args.get("desde"):
            cond.append("f.fecha >= ?")
            params.append(args["desde"])
        if args.get("hasta"):
            cond.append("f.fecha <= ?")
            params.append(args["hasta"])
        limite = int(_numero(args, "limite", 50, 1))
        filas = conn.execute(
            "SELECT f.numero, cl.nombre AS cliente, e.nombre AS empresa, f.fecha, f.estado_pago AS estado, "
            "f.fecha_pago, f.total, f.concepto, c.numero AS cotizacion "
            "FROM facturas f JOIN clientes cl ON cl.id = f.cliente_id LEFT JOIN empresas e ON e.id = f.empresa_id "
            "LEFT JOIN cotizaciones c ON c.id = f.cotizacion_id "
            + ("WHERE " + " AND ".join(cond) if cond else "") + " ORDER BY f.id DESC LIMIT ?", (*params, limite)).fetchall()
        return [{**dict(f), "total": _dinero(f["total"])} for f in filas]
    finally:
        conn.close()


def obtener_factura(args):
    conn = _conexion()
    try:
        f = _fila_factura(conn, args.get("numero"))
        cl = conn.execute("SELECT nombre, identificacion, contacto FROM clientes WHERE id = ?", (f["cliente_id"],)).fetchone()
        cot = conn.execute("SELECT numero FROM cotizaciones WHERE id = ?", (f["cotizacion_id"],)).fetchone()
        return {"numero": f["numero"], "fecha": f["fecha"], "estado": f["estado_pago"], "fecha_pago": f["fecha_pago"],
                "total": _dinero(f["total"]), "concepto": f["concepto"], "porcentaje_de_la_cotizacion": f["porcentaje"],
                "cotizacion": cot["numero"] if cot else None, "cliente": dict(cl), "notas": f["notas"],
                "titulo_notas": f["titulo_notas"]}
    finally:
        conn.close()


def exportar_pdf(args):
    """Genera el PDF de una cotización o factura (por su número) y devuelve la ruta del archivo."""
    numero = str(args.get("numero") or "").strip()
    carpeta = Path(args.get("carpeta") or Path(tempfile.gettempdir()) / "QuoteTrack_exportados")
    carpeta.mkdir(parents=True, exist_ok=True)
    conn = _conexion()
    try:
        if numero.upper().startswith("FAC"):
            fid = _fila_factura(conn, numero)["id"]
            ruta = carpeta / f"{numero}.pdf"
            pdf.exportar_factura(fid, str(ruta))
        else:
            ruta = carpeta / f"{numero}.pdf"
            pdf.exportar_cotizacion(_id_cotizacion(conn, numero), str(ruta))
    finally:
        conn.close()
    return {"archivo": str(ruta), "bytes": ruta.stat().st_size}


# ----------------------------------------------------------------------------- herramientas de escritura
def crear_cliente(args):
    conn = _conexion()
    try:
        nombre = str(args.get("nombre") or "").strip()
        try:
            cid = db.guardar_cliente({"nombre": nombre, "identificacion": args.get("identificacion", ""),
                                      "contacto": args.get("contacto", "")}, conn)
        except ValueError as e:
            raise ErrorHerramienta(str(e))
        return {"id": cid, "nombre": nombre}
    finally:
        conn.close()


def crear_cotizacion(args):
    conn = _conexion()
    try:
        cliente_id = _cliente(conn, args.get("cliente"))
        empresa_id = _empresa(conn, args.get("empresa"))
        if not args.get("lineas"):
            raise ErrorHerramienta("Indica al menos una línea en «lineas».")
        lineas = []
        for n, l in enumerate(args["lineas"], 1):
            if not str(l.get("descripcion") or l.get("titulo") or "").strip():
                raise ErrorHerramienta(f"La línea {n} necesita «descripcion» o «titulo».")
            lineas.append(Linea("item", 0, str(l.get("descripcion") or ""), _numero(l, "cantidad", 1, 0) or 0,
                                _numero(l, "precio", 0, 0), bool(l.get("aplica_itbms", True)), str(l.get("unidad") or ""),
                                titulo=str(l.get("titulo") or "")))
        cargos = []
        for c in args.get("cargos") or []:
            tipo = c.get("tipo", "porcentaje")
            if tipo not in calculo.TIPOS_CARGO:
                raise ErrorHerramienta("El tipo de un costo adicional es «porcentaje» o «monto».")
            base = ",".join(k for k in str(c.get("base") or "").replace(" ", "").split(",") if k)
            if any(k not in calculo.CATEGORIAS_BASE for k in base.split(",") if k):
                raise ErrorHerramienta("«base» admite: " + ", ".join(calculo.CATEGORIAS_BASE))
            cargos.append(Cargo(str(c.get("concepto") or ""), tipo, _numero(c, "valor", 0, 0),
                                bool(c.get("aplica_itbms", True)), base, bool(c.get("diluir", False))))
        cid, numero = db.crear_cotizacion(cliente_id, conn, empresa_id)
        db.guardar_cotizacion(cid, lineas, cargos, conn)
        if args.get("notas"):
            db.guardar_notas(cid, str(args["notas"]), conn)
        if args.get("proyecto"):
            db.guardar_proyecto(cid, str(args["proyecto"]), conn)
        t = db.totales_cotizacion(cid, conn)
        return {"numero": numero, "estado": "borrador", "total": _dinero(t.total), "itbms": _dinero(t.itbms)}
    finally:
        conn.close()


def cambiar_estado_cotizacion(args):
    conn = _conexion()
    try:
        cid = _id_cotizacion(conn, args.get("numero"))
        try:
            db.cambiar_estado_cotizacion(cid, str(args.get("estado") or ""), conn)
        except ValueError as e:
            raise ErrorHerramienta(str(e))
        return {"numero": args["numero"], "estado": conn.execute(
            "SELECT estado FROM cotizaciones WHERE id = ?", (cid,)).fetchone()["estado"]}
    finally:
        conn.close()


def generar_factura(args):
    conn = _conexion()
    try:
        cid = _id_cotizacion(conn, args.get("cotizacion"))
        try:
            numero = db.generar_factura(cid, conn, porcentaje=_numero(args, "porcentaje"), monto=_numero(args, "monto"),
                                        concepto=args.get("concepto"))
        except ValueError as e:
            raise ErrorHerramienta(str(e))
        f = _fila_factura(conn, numero)
        return {"numero": numero, "total": _dinero(f["total"]), "concepto": f["concepto"],
                "saldo_por_facturar": db.resumen_facturacion(cid, conn)["saldo"]}
    finally:
        conn.close()


def marcar_factura_pagada(args):
    conn = _conexion()
    try:
        f = _fila_factura(conn, args.get("numero"))
        fecha = str(args.get("fecha_pago") or date.today().isoformat())
        try:
            date.fromisoformat(fecha)
        except ValueError:
            raise ErrorHerramienta("La fecha de pago debe ser AAAA-MM-DD.")
        try:
            db.marcar_factura_pagada(f["id"], fecha, conn)
        except ValueError as e:
            raise ErrorHerramienta(str(e))
        return {"numero": f["numero"], "estado": "pagada", "fecha_pago": fecha}
    finally:
        conn.close()


# ----------------------------------------------------------------------------- catálogo de herramientas
def _esquema(propiedades=None, requeridos=()):
    return {"type": "object", "properties": propiedades or {}, "required": list(requeridos)}


_TXT = {"type": "string"}
_LINEA = _esquema({
    "titulo": {"type": "string", "description": "Título corto del ítem (sale en negrita)."},
    "descripcion": {"type": "string", "description": "Descripción del ítem."},
    "cantidad": {"type": "number"}, "precio": {"type": "number", "description": "Precio unitario en B/."},
    "unidad": _TXT, "aplica_itbms": {"type": "boolean"}})
_CARGO = _esquema({
    "concepto": {"type": "string", "description": "Administración, Utilidad, Imprevistos…"},
    "tipo": {"type": "string", "enum": ["porcentaje", "monto"]}, "valor": {"type": "number"},
    "base": {"type": "string", "description": "Categorías sobre las que actúa, separadas por coma: " + ", ".join(
        calculo.CATEGORIAS_BASE) + ". Vacío = todo el subtotal."},
    "diluir": {"type": "boolean", "description": "Reparte el costo en el precio de los ítems."},
    "aplica_itbms": {"type": "boolean"}}, ["concepto", "valor"])

HERRAMIENTAS = {
    "estadisticas": (estadisticas, False, "Resumen general: cotizaciones y facturas por estado, lo por cobrar y lo cobrado, "
                     "y los mejores clientes.", _esquema()),
    "listar_clientes": (listar_clientes, False, "Lista los clientes (con su cantidad de cotizaciones). Filtra por nombre o RUC.",
                        _esquema({"buscar": _TXT})),
    "listar_cotizaciones": (listar_cotizaciones, False, "Lista cotizaciones, las más recientes primero.", _esquema({
        "cliente": {"type": "string", "description": "Parte del nombre del cliente."},
        "estado": {"type": "string", "enum": ["borrador", "enviada", "aprobada", "rechazada"]},
        "buscar": {"type": "string", "description": "Texto en el número, proyecto o cliente."},
        "limite": {"type": "integer", "description": "Máximo de filas (50 por defecto)."}})),
    "obtener_cotizacion": (obtener_cotizacion, False, "Detalle completo de una cotización: ítems, costos adicionales, "
                           "totales, notas y facturación.", _esquema({"numero": _TXT}, ["numero"])),
    "resumen_cotizacion": (resumen_cotizacion, False, "Desglose de costos de una cotización: costos directos por categoría "
                           "(materiales, mano de obra…), servicios, margen de los análisis, costos adicionales (administración, "
                           "utilidad…), ITBMS y total, con su porcentaje.", _esquema({"numero": _TXT}, ["numero"])),
    "listar_facturas": (listar_facturas, False, "Lista facturas, las más recientes primero.", _esquema({
        "cliente": _TXT, "estado": {"type": "string", "enum": ["pendiente", "pagada", "vencida"]},
        "desde": {"type": "string", "description": "Fecha mínima AAAA-MM-DD."},
        "hasta": {"type": "string", "description": "Fecha máxima AAAA-MM-DD."}, "limite": {"type": "integer"}})),
    "obtener_factura": (obtener_factura, False, "Detalle de una factura: cliente, estado de pago, concepto y notas.",
                        _esquema({"numero": _TXT}, ["numero"])),
    "exportar_pdf": (exportar_pdf, False, "Genera el PDF de una cotización o factura (por su número) y devuelve la ruta "
                     "del archivo en el equipo.", _esquema({"numero": _TXT, "carpeta": {
                         "type": "string", "description": "Carpeta de destino (por defecto, la temporal)."}}, ["numero"])),
    "crear_cliente": (crear_cliente, True, "Crea un cliente.", _esquema({
        "nombre": _TXT, "identificacion": {"type": "string", "description": "RUC o cédula."}, "contacto": _TXT}, ["nombre"])),
    "crear_cotizacion": (crear_cotizacion, True, "Crea una cotización en borrador con sus líneas y costos adicionales. "
                         "El ITBMS sale de la empresa.", _esquema({
                             "cliente": {"type": "string", "description": "Nombre del cliente (debe existir)."},
                             "empresa": {"type": "string", "description": "Empresa que cotiza (la predeterminada si se omite)."},
                             "proyecto": _TXT, "notas": _TXT, "lineas": {"type": "array", "items": _LINEA},
                             "cargos": {"type": "array", "items": _CARGO}}, ["cliente", "lineas"])),
    "cambiar_estado_cotizacion": (cambiar_estado_cotizacion, True, "Cambia el estado de una cotización "
                                  "(borrador → enviada → aprobada o rechazada).", _esquema({
                                      "numero": _TXT, "estado": {"type": "string", "enum": [
                                          "borrador", "enviada", "aprobada", "rechazada"]}}, ["numero", "estado"])),
    "generar_factura": (generar_factura, True, "Genera una factura de una cotización aprobada. Sin porcentaje ni monto "
                        "factura todo el saldo; con porcentaje o monto es un abono (facturas por etapas).", _esquema({
                            "cotizacion": _TXT, "porcentaje": {"type": "number", "description": "% del total de la cotización."},
                            "monto": {"type": "number"}, "concepto": _TXT}, ["cotizacion"])),
    "marcar_factura_pagada": (marcar_factura_pagada, True, "Marca una factura como pagada (lleva el sello PAGADO).",
                              _esquema({"numero": _TXT, "fecha_pago": {"type": "string", "description": "AAAA-MM-DD (hoy por defecto)."}},
                                       ["numero"])),
}


# ----------------------------------------------------------------------------- protocolo MCP
class Servidor:
    def __init__(self, escritura: bool = False, latido: "mcp_estado.Latido | None" = None):
        self.escritura = escritura
        self.latido = latido            # si existe, la aplicación ve que el MCP está conectado y su actividad

    def _herramientas(self):
        return {n: h for n, h in HERRAMIENTAS.items() if self.escritura or not h[1]}

    def listar(self):
        return [{"name": n, "description": (d if not escribe else d + " (modifica datos)"), "inputSchema": e,
                 "annotations": {"readOnlyHint": not escribe, "destructiveHint": False}}
                for n, (_f, escribe, d, e) in self._herramientas().items()]

    def llamar(self, nombre: str, argumentos: dict) -> dict:
        try:
            if nombre in HERRAMIENTAS and nombre not in self._herramientas():
                raise ErrorHerramienta("Esta herramienta modifica datos y el servidor está en modo de solo lectura. "
                                       "Inícialo con --escritura para permitirla.")
            if nombre not in HERRAMIENTAS:
                raise ErrorHerramienta(f"Herramienta desconocida: {nombre}")
            funcion = HERRAMIENTAS[nombre][0]
            resultado = funcion(argumentos or {})
            texto = json.dumps(resultado, ensure_ascii=False, indent=2, default=str)
            if self.latido:
                self.latido.registrar(nombre, HERRAMIENTAS[nombre][1])   # la app refresca sus listas si modificó datos
            return {"content": [{"type": "text", "text": texto}], "isError": False}
        except ErrorHerramienta as e:
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}
        except Exception as e:                       # un fallo inesperado no debe tumbar el servidor
            print(f"error en {nombre}: {e!r}", file=sys.stderr)
            return {"content": [{"type": "text", "text": f"Error inesperado: {e}"}], "isError": True}

    def atender(self, msg: dict):
        """Procesa un mensaje JSON-RPC; devuelve la respuesta, o None si era una notificación."""
        metodo, id_ = msg.get("method"), msg.get("id")
        params = msg.get("params") or {}
        if id_ is None:                              # notificación (p. ej. notifications/initialized)
            return None
        if metodo == "initialize":
            resultado = {"protocolVersion": params.get("protocolVersion") or PROTOCOLO,
                         "capabilities": {"tools": {}},
                         "serverInfo": {"name": "quotetrack", "version": VERSION},
                         "instructions": INSTRUCCIONES + ("" if self.escritura else " Modo de solo lectura.")}
        elif metodo == "ping":
            resultado = {}
        elif metodo == "tools/list":
            resultado = {"tools": self.listar()}
        elif metodo == "tools/call":
            resultado = self.llamar(params.get("name", ""), params.get("arguments") or {})
        elif metodo in ("resources/list", "prompts/list"):
            resultado = {"resources" if metodo.startswith("res") else "prompts": []}
        else:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32601, "message": f"Método no soportado: {metodo}"}}
        return {"jsonrpc": "2.0", "id": id_, "result": resultado}

    def servir(self, entrada=None, salida=None):
        entrada, salida = entrada or sys.stdin, salida or sys.stdout
        for linea in entrada:
            linea = linea.strip()
            if not linea:
                continue
            try:
                msg = json.loads(linea)
            except json.JSONDecodeError:
                salida.write(json.dumps({"jsonrpc": "2.0", "id": None,
                                         "error": {"code": -32700, "message": "JSON no válido"}}) + "\n")
                salida.flush()
                continue
            respuestas = [self.atender(m) for m in msg] if isinstance(msg, list) else [self.atender(msg)]
            respuestas = [r for r in respuestas if r is not None]
            if respuestas:
                salida.write(json.dumps(respuestas if isinstance(msg, list) else respuestas[0], ensure_ascii=False) + "\n")
                salida.flush()


def _asegurar_flujos() -> None:
    """Un ejecutable sin consola (el MCP se compila así para no abrir ventanas) puede arrancar con stdin/stdout/stderr
    en None. Si Claude Desktop pasa tuberías se enlazan a los descriptores 0, 1 y 2; si no hay ninguna (p. ej. doble
    clic en el .exe) se usan flujos vacíos y el servidor termina enseguida, sin ventana ni procesos colgados."""
    for fd, nombre, modo in ((0, "stdin", "r"), (1, "stdout", "w"), (2, "stderr", "w")):
        if getattr(sys, nombre) is None:
            try:
                setattr(sys, nombre, open(fd, modo, encoding="utf-8", closefd=False))
            except OSError:
                setattr(sys, nombre, open(os.devnull, modo, encoding="utf-8"))


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _asegurar_flujos()
    for flujo in (sys.stdin, sys.stdout, sys.stderr):     # en Windows la consola usa cp1252: se fuerza UTF-8
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace" if flujo is sys.stderr else "strict")
        except (AttributeError, ValueError):
            pass
    if "--ayuda" in argv or "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    ruta = os.environ.get("QUOTETRACK_DB")
    if "--db" in argv:
        i = argv.index("--db")
        ruta = argv[i + 1] if i + 1 < len(argv) else ruta
    if ruta:
        db.DB_PATH = Path(ruta)
    escritura = "--escritura" in argv or os.environ.get("QUOTETRACK_MCP_ESCRITURA") == "1"
    if Path(db.DB_PATH).exists():
        db.init_db()                                  # deja el esquema al día (idempotente)
    print(f"QuoteTrack MCP {VERSION} · base de datos: {db.DB_PATH} · "
          f"{'lectura y escritura' if escritura else 'solo lectura'}", file=sys.stderr)
    latido = None if "--sin-latido" in argv else mcp_estado.Latido(db.DB_PATH, escritura)
    if latido:
        latido.iniciar()
    try:
        Servidor(escritura, latido).servir()
    finally:
        if latido:
            latido.detener()                          # al cerrarse el MCP, el indicador de la app se apaga
    return 0


if __name__ == "__main__":
    sys.exit(main())
