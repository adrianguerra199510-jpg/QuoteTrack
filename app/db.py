"""
Capa de acceso a datos para QuoteTrack.
Usa SQLite (archivo local quotetrack.db) para clientes, cotizaciones y facturas.
"""
import sqlite3
from pathlib import Path
from datetime import date

DB_PATH = Path(__file__).resolve().parent.parent / "quotetrack.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    identificacion TEXT,
    contacto TEXT
);

CREATE TABLE IF NOT EXISTS cotizaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    fecha TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'borrador',  -- borrador, enviada, aprobada, rechazada
    subtotal REAL NOT NULL DEFAULT 0,
    itbms REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL DEFAULT 0,
    notas TEXT
);

CREATE TABLE IF NOT EXISTS cotizacion_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cotizacion_id INTEGER NOT NULL REFERENCES cotizaciones(id) ON DELETE CASCADE,
    descripcion TEXT NOT NULL,
    cantidad REAL NOT NULL DEFAULT 1,
    precio_unitario REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS facturas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    cotizacion_id INTEGER REFERENCES cotizaciones(id),
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    fecha TEXT NOT NULL,
    estado_pago TEXT NOT NULL DEFAULT 'pendiente',  -- pendiente, pagada, vencida
    total REAL NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_facturas_cotizacion
    ON facturas(cotizacion_id) WHERE cotizacion_id IS NOT NULL;
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.executescript(SCHEMA)
    # Migración: bases creadas antes de existir la fecha de pago
    columnas = [c["name"] for c in conn.execute("PRAGMA table_info(facturas)")]
    if "fecha_pago" not in columnas:
        conn.execute("ALTER TABLE facturas ADD COLUMN fecha_pago TEXT")
    conn.commit()
    conn.close()


def next_numero(prefijo: str, tabla: str, conn: sqlite3.Connection) -> str:
    """Genera un número consecutivo tipo COT-2026-0001 / FAC-2026-0001."""
    anio = date.today().year
    cur = conn.execute(
        f"SELECT COUNT(*) AS n FROM {tabla} WHERE numero LIKE ?", (f"{prefijo}-{anio}-%",)
    )
    n = cur.fetchone()["n"] + 1
    return f"{prefijo}-{anio}-{n:04d}"


ITBMS_RATE = 0.07  # ITBMS Panamá 7%


def calcular_totales(items) -> tuple[float, float, float]:
    """Devuelve (subtotal, itbms, total) para una lista de (descripcion, cantidad, precio)."""
    subtotal = round(sum(cant * precio for _desc, cant, precio in items), 2)
    itbms = round(subtotal * ITBMS_RATE, 2)
    return subtotal, itbms, round(subtotal + itbms, 2)


def obtener_items(cotizacion_id: int, conn: sqlite3.Connection) -> list[tuple[str, float, float]]:
    filas = conn.execute(
        "SELECT descripcion, cantidad, precio_unitario FROM cotizacion_items "
        "WHERE cotizacion_id = ? ORDER BY id",
        (cotizacion_id,),
    ).fetchall()
    return [(f["descripcion"], f["cantidad"], f["precio_unitario"]) for f in filas]


def guardar_items(cotizacion_id: int, items, conn: sqlite3.Connection) -> tuple[float, float, float]:
    """Reemplaza las líneas de la cotización y actualiza subtotal/ITBMS/total."""
    items = list(items)
    conn.execute("DELETE FROM cotizacion_items WHERE cotizacion_id = ?", (cotizacion_id,))
    conn.executemany(
        "INSERT INTO cotizacion_items (cotizacion_id, descripcion, cantidad, precio_unitario) "
        "VALUES (?, ?, ?, ?)",
        [(cotizacion_id, d, c, p) for d, c, p in items],
    )
    subtotal, itbms, total = calcular_totales(items)
    conn.execute(
        "UPDATE cotizaciones SET subtotal = ?, itbms = ?, total = ? WHERE id = ?",
        (subtotal, itbms, total, cotizacion_id),
    )
    conn.commit()
    return subtotal, itbms, total


TRANSICIONES_COTIZACION = {
    "borrador": ["enviada"],
    "enviada": ["aprobada", "rechazada"],
    "aprobada": [],
    "rechazada": [],
}


def cambiar_estado_cotizacion(cotizacion_id: int, nuevo: str, conn: sqlite3.Connection) -> None:
    """Valida la transición de estado y la aplica. Lanza ValueError si no es válida."""
    fila = conn.execute(
        "SELECT estado, (SELECT COUNT(*) FROM cotizacion_items WHERE cotizacion_id = ?) AS n_items "
        "FROM cotizaciones WHERE id = ?",
        (cotizacion_id, cotizacion_id),
    ).fetchone()
    if fila is None:
        raise ValueError("La cotización no existe.")
    if nuevo not in TRANSICIONES_COTIZACION.get(fila["estado"], []):
        raise ValueError(f"No se puede pasar de '{fila['estado']}' a '{nuevo}'.")
    if nuevo == "enviada" and fila["n_items"] == 0:
        raise ValueError("Agrega al menos una línea antes de enviar la cotización.")
    conn.execute("UPDATE cotizaciones SET estado = ? WHERE id = ?", (nuevo, cotizacion_id))
    conn.commit()


def generar_factura(cotizacion_id: int, conn: sqlite3.Connection) -> str:
    """Crea la factura de una cotización aprobada y devuelve su número.
    Lanza ValueError si la cotización no está aprobada o ya tiene factura."""
    cot = conn.execute("SELECT * FROM cotizaciones WHERE id = ?", (cotizacion_id,)).fetchone()
    if cot is None:
        raise ValueError("La cotización no existe.")
    if cot["estado"] != "aprobada":
        raise ValueError("Solo se puede facturar una cotización aprobada.")
    existente = conn.execute(
        "SELECT numero FROM facturas WHERE cotizacion_id = ?", (cotizacion_id,)
    ).fetchone()
    if existente:
        raise ValueError(f"Esta cotización ya tiene la factura {existente['numero']}.")
    numero = next_numero("FAC", "facturas", conn)
    conn.execute(
        "INSERT INTO facturas (numero, cotizacion_id, cliente_id, fecha, estado_pago, total) "
        "VALUES (?, ?, ?, ?, 'pendiente', ?)",
        (numero, cotizacion_id, cot["cliente_id"], date.today().isoformat(), cot["total"]),
    )
    conn.commit()
    return numero


def marcar_factura_pagada(factura_id: int, fecha_pago: str, conn: sqlite3.Connection) -> None:
    fila = conn.execute("SELECT estado_pago FROM facturas WHERE id = ?", (factura_id,)).fetchone()
    if fila is None:
        raise ValueError("La factura no existe.")
    if fila["estado_pago"] == "pagada":
        raise ValueError("La factura ya está pagada.")
    conn.execute(
        "UPDATE facturas SET estado_pago = 'pagada', fecha_pago = ? WHERE id = ?",
        (fecha_pago, factura_id),
    )
    conn.commit()


def marcar_factura_vencida(factura_id: int, conn: sqlite3.Connection) -> None:
    fila = conn.execute("SELECT estado_pago FROM facturas WHERE id = ?", (factura_id,)).fetchone()
    if fila is None:
        raise ValueError("La factura no existe.")
    if fila["estado_pago"] != "pendiente":
        raise ValueError("Solo una factura pendiente puede marcarse como vencida.")
    conn.execute("UPDATE facturas SET estado_pago = 'vencida' WHERE id = ?", (factura_id,))
    conn.commit()
