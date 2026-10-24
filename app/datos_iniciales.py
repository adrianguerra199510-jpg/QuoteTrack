"""Empresas, clientes, cotizaciones y factura de arranque (assets/datos_iniciales.json), cargados una sola vez
la primera vez que se abre la aplicación para no tener que volver a crearlos. Es idempotente: lo que ya existe
(misma empresa, mismo cliente, mismo número de cotización o factura) se respeta."""
import json
from datetime import date

from app import db
from app.calculo import Linea
from app.recursos import ruta_recurso

ARCHIVO = "assets/datos_iniciales.json"
CLAVE = "datos_iniciales_cargados"


def cargar() -> dict:
    return json.loads(ruta_recurso(ARCHIVO).read_text(encoding="utf-8"))


def _empresa(datos: dict, conn) -> int:
    fila = conn.execute("SELECT * FROM empresas WHERE nombre = ?", (datos["nombre"],)).fetchone()
    logo = ruta_recurso(datos["logo"]).read_bytes() if datos.get("logo") else None
    if fila is None:
        return db.guardar_empresa({**datos, "logo": logo}, conn)
    # la empresa ya existe (p. ej. la creada por defecto): solo se completan los datos que le faltan
    nuevos = {c: fila[c] or datos.get(c) or ("" if c != "logo" else None) for c in db.CAMPOS_EMPRESA if c != "logo"}
    nuevos["logo"] = fila["logo"] or logo
    nuevos["itbms_tasa"] = fila["itbms_tasa"]
    db.guardar_empresa(nuevos, conn, fila["id"])
    return fila["id"]


def _cliente(datos: dict, conn) -> int:
    fila = conn.execute("SELECT id FROM clientes WHERE nombre = ?", (datos["nombre"],)).fetchone()
    return fila["id"] if fila else db.guardar_cliente(datos, conn)


def _linea(d: dict) -> Linea:
    return Linea(d["tipo"], d["nivel"], d["descripcion"], d.get("cantidad", 1.0), d.get("precio", 0.0),
                 d.get("aplica_itbms", True), d.get("unidad", ""))


def precargar(conn) -> int:
    """Carga los datos de arranque la primera vez. Devuelve cuántas cotizaciones y facturas creó."""
    if db.obtener_config(CLAVE, conn):
        return 0
    datos = cargar()
    empresas = {e["nombre"]: _empresa(e, conn) for e in datos["empresas"]}
    clientes = {c["nombre"]: _cliente(c, conn) for c in datos["clientes"]}
    creados, nuevas = 0, set()
    for c in datos["cotizaciones"]:
        if conn.execute("SELECT 1 FROM cotizaciones WHERE numero = ?", (c["numero"],)).fetchone():
            continue
        cot_id, _ = db.crear_cotizacion(clientes[c["cliente"]], conn, empresas[c["empresa"]])
        conn.execute("UPDATE cotizaciones SET numero = ?, fecha = ?, estado = ?, proyecto = ? WHERE id = ?",
                     (c["numero"], c["fecha"], c["estado"], c["proyecto"], cot_id))
        conn.commit()
        db.guardar_cotizacion(cot_id, [_linea(l) for l in c["lineas"]], [], conn, tasa=c["tasa"] / 100)
        db.guardar_notas(cot_id, c["notas"], conn)
        if c.get("titulo_notas"):
            db.guardar_titulo_notas("cotizaciones", cot_id, c["titulo_notas"], conn)
        nuevas.add(c["numero"])
        creados += 1
    for f in datos["facturas"]:
        if f["cotizacion"] not in nuevas or conn.execute("SELECT 1 FROM facturas WHERE numero = ?", (f["numero"],)).fetchone():
            continue          # solo se factura una cotización creada aquí, nunca una que ya tenía el usuario
        cot = conn.execute("SELECT id FROM cotizaciones WHERE numero = ?", (f["cotizacion"],)).fetchone()
        if cot is None or conn.execute("SELECT 1 FROM facturas WHERE cotizacion_id = ?", (cot["id"],)).fetchone():
            continue
        antes = conn.execute("SELECT estado FROM cotizaciones WHERE id = ?", (cot["id"],)).fetchone()["estado"]
        conn.execute("UPDATE cotizaciones SET estado = 'aprobada' WHERE id = ?", (cot["id"],))
        numero = db.generar_factura(cot["id"], conn)
        conn.execute("UPDATE cotizaciones SET estado = ? WHERE id = ?", (antes, cot["id"]))
        conn.execute("UPDATE facturas SET numero = ?, fecha = ?, notas = ?, titulo_notas = ? WHERE numero = ?",
                     (f["numero"], f["fecha"], f["notas"], f.get("titulo_notas", ""), numero))
        conn.commit()
        creados += 1
    db.guardar_config(CLAVE, "1", conn)
    return creados
