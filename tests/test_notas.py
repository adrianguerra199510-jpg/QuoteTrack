import sqlite3

from app import db


def aprobar(conn, cot_id=1):
    db.cambiar_estado_cotizacion(cot_id, "enviada", conn)
    db.cambiar_estado_cotizacion(cot_id, "aprobada", conn)


def test_notas_vacias_por_defecto(conn):
    assert db.obtener_notas(1, conn) == ""


def test_guardar_y_leer_notas_multilinea(conn):
    texto = "Línea 1\n\n  Línea 3 con sangría"
    db.guardar_notas(1, texto, conn)
    assert db.obtener_notas(1, conn) == texto


def test_migracion_base_antigua(tmp_path, monkeypatch):
    """Una base creada con el esquema anterior (notas NULL, facturas sin notas) se migra sin perder datos."""
    ruta = tmp_path / "vieja.db"
    monkeypatch.setattr(db, "DB_PATH", ruta)
    old = sqlite3.connect(ruta)
    old.executescript("""
        CREATE TABLE clientes (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL,
                               identificacion TEXT, contacto TEXT);
        CREATE TABLE cotizaciones (id INTEGER PRIMARY KEY AUTOINCREMENT, numero TEXT UNIQUE NOT NULL,
            cliente_id INTEGER NOT NULL, fecha TEXT NOT NULL, estado TEXT NOT NULL DEFAULT 'borrador',
            subtotal REAL NOT NULL DEFAULT 0, itbms REAL NOT NULL DEFAULT 0, total REAL NOT NULL DEFAULT 0,
            notas TEXT);
        CREATE TABLE cotizacion_items (id INTEGER PRIMARY KEY AUTOINCREMENT, cotizacion_id INTEGER NOT NULL,
            descripcion TEXT NOT NULL, cantidad REAL NOT NULL DEFAULT 1, precio_unitario REAL NOT NULL DEFAULT 0);
        CREATE TABLE facturas (id INTEGER PRIMARY KEY AUTOINCREMENT, numero TEXT UNIQUE NOT NULL,
            cotizacion_id INTEGER, cliente_id INTEGER NOT NULL, fecha TEXT NOT NULL,
            estado_pago TEXT NOT NULL DEFAULT 'pendiente', total REAL NOT NULL DEFAULT 0);
        INSERT INTO clientes (nombre) VALUES ('Vieja SA');
        INSERT INTO cotizaciones (numero, cliente_id, fecha, total) VALUES ('COT-2025-0001', 1, '2025-05-01', 10);
        INSERT INTO facturas (numero, cotizacion_id, cliente_id, fecha, total) VALUES ('FAC-2025-0001', 1, 1, '2025-05-02', 10);
    """)
    old.commit()
    old.close()

    db.init_db()
    db.init_db()  # idempotente
    c = db.get_connection()
    assert db.obtener_notas(1, c) == ""
    assert c.execute("SELECT notas FROM facturas").fetchone()["notas"] == ""
    assert c.execute("SELECT total FROM cotizaciones").fetchone()["total"] == 10


def test_factura_copia_notas(conn):
    db.guardar_notas(1, "Validez 15 días\nPago 50%/50%", conn)
    aprobar(conn)
    db.generar_factura(1, conn)
    assert conn.execute("SELECT notas FROM facturas").fetchone()["notas"] == "Validez 15 días\nPago 50%/50%"


def test_plantilla_por_defecto_y_editable(conn):
    assert db.obtener_plantilla_notas(conn) == db.PLANTILLA_NOTAS_INICIAL
    db.guardar_plantilla_notas("Mi plantilla\ncon dos líneas", conn)
    assert db.obtener_plantilla_notas(conn) == "Mi plantilla\ncon dos líneas"
    db.guardar_plantilla_notas("Otra", conn)  # sobrescribe
    assert db.obtener_plantilla_notas(conn) == "Otra"
