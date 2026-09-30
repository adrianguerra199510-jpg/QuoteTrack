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
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.executescript(SCHEMA)
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
