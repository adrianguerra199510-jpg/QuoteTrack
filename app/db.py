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
