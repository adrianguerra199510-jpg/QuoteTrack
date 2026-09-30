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
    notas TEXT NOT NULL DEFAULT ''
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

CREATE TABLE IF NOT EXISTS configuracion (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
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
    # Migración: notas / términos y condiciones (vacío por defecto en registros existentes)
    if "notas" not in columnas:
        conn.execute("ALTER TABLE facturas ADD COLUMN notas TEXT NOT NULL DEFAULT ''")
    conn.execute("UPDATE cotizaciones SET notas = '' WHERE notas IS NULL")
    if "proyecto" not in [c["name"] for c in conn.execute("PRAGMA table_info(cotizaciones)")]:
        conn.execute("ALTER TABLE cotizaciones ADD COLUMN proyecto TEXT NOT NULL DEFAULT ''")
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


def calcular_totales(items, tasa: float = ITBMS_RATE) -> tuple[float, float, float]:
    """Devuelve (subtotal, itbms, total) para una lista de (descripcion, cantidad, precio)."""
    subtotal = round(sum(cant * precio for _desc, cant, precio in items), 2)
    itbms = round(subtotal * tasa, 2)
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
    subtotal, itbms, total = calcular_totales(items, obtener_tasa_itbms(conn))
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
        "INSERT INTO facturas (numero, cotizacion_id, cliente_id, fecha, estado_pago, total, notas) "
        "VALUES (?, ?, ?, ?, 'pendiente', ?, ?)",
        (numero, cotizacion_id, cot["cliente_id"], date.today().isoformat(), cot["total"],
         cot["notas"] or ""),
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


PLANTILLA_NOTAS_INICIAL = """ALCANCE
• Diseño estructural integral: modelo y análisis, memoria de cálculo y planos estructurales, conforme al REP-2021 y ACI 318-19.
• El precio corresponde a las áreas de construcción indicadas en el alcance.

EXCLUSIONES
• Estudio geotécnico y recomendaciones de cimentación.
• Cimentación profunda (pilotes), que se cotiza por separado si aplica.
• Planos de taller.
• Inspección en obra y supervisión.
• Diseño de instalaciones (eléctrico, mecánico, sanitario) y fachadas especiales.

REVISIONES
• Se incluye un máximo de dos (2) rondas de revisión por entregable. Las revisiones adicionales o cambios de alcance se cobran por hora o mediante adenda.

FORMA DE PAGO
• 30% al inicio del proyecto.
• 40% a la entrega de planos.
• 30% a la aprobación final.

VALIDEZ DE LA OFERTA
• Esta cotización tiene una validez de 30 días calendario a partir de la fecha de emisión.

OBSERVACIONES
• Si la estructura o cimentación de alguna torre difiere de la torre tipo, el precio de esa torre se reajustará."""

# Valores por defecto de la configuración (clave -> valor)
CONFIG_DEFECTOS = {
    "mostrar_estado_pdf": "0",
    "itbms_tasa": "7",
    "empresa_nombre": "INTEGRO SA",
    "empresa_subtitulo": "INGENIERIA ESTRUCTURAL",
    "empresa_correo": "",
}


def obtener_config(clave: str, conn: sqlite3.Connection, defecto: str = "") -> str:
    fila = conn.execute("SELECT valor FROM configuracion WHERE clave = ?", (clave,)).fetchone()
    return fila["valor"] if fila else defecto


def guardar_config(clave: str, valor: str, conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO configuracion (clave, valor) VALUES (?, ?) "
        "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
        (clave, valor),
    )
    conn.commit()


def obtener_plantilla_notas(conn: sqlite3.Connection) -> str:
    return obtener_config("plantilla_notas", conn, PLANTILLA_NOTAS_INICIAL)


def guardar_plantilla_notas(texto: str, conn: sqlite3.Connection) -> None:
    guardar_config("plantilla_notas", texto, conn)


def obtener_notas(cotizacion_id: int, conn: sqlite3.Connection) -> str:
    fila = conn.execute("SELECT notas FROM cotizaciones WHERE id = ?", (cotizacion_id,)).fetchone()
    return (fila["notas"] or "") if fila else ""


def guardar_notas(cotizacion_id: int, notas: str, conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE cotizaciones SET notas = ? WHERE id = ?", (notas, cotizacion_id))
    conn.commit()


def restaurar_plantilla_notas(conn: sqlite3.Connection) -> str:
    conn.execute("DELETE FROM configuracion WHERE clave = 'plantilla_notas'")
    conn.commit()
    return PLANTILLA_NOTAS_INICIAL


def obtener_opcion(clave: str, conn: sqlite3.Connection) -> str:
    return obtener_config(clave, conn, CONFIG_DEFECTOS[clave])


def mostrar_estado_pdf(conn: sqlite3.Connection) -> bool:
    return obtener_opcion("mostrar_estado_pdf", conn) == "1"


def obtener_tasa_itbms(conn: sqlite3.Connection) -> float:
    """Tasa de ITBMS como fracción (0.07). 0 = exento."""
    try:
        return max(0.0, float(obtener_opcion("itbms_tasa", conn).replace(",", "."))) / 100
    except ValueError:
        return ITBMS_RATE


def obtener_proyecto(cotizacion_id: int, conn: sqlite3.Connection) -> str:
    fila = conn.execute("SELECT proyecto FROM cotizaciones WHERE id = ?", (cotizacion_id,)).fetchone()
    return (fila["proyecto"] or "") if fila else ""


def guardar_proyecto(cotizacion_id: int, proyecto: str, conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE cotizaciones SET proyecto = ? WHERE id = ?", (proyecto, cotizacion_id))
    conn.commit()


def obtener_notas_factura(factura_id: int, conn: sqlite3.Connection) -> str:
    fila = conn.execute("SELECT notas FROM facturas WHERE id = ?", (factura_id,)).fetchone()
    return (fila["notas"] or "") if fila else ""


def guardar_notas_factura(factura_id: int, notas: str, conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE facturas SET notas = ? WHERE id = ?", (notas, factura_id))
    conn.commit()
