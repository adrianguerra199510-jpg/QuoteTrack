import sqlite3

from app import db
from app.calculo import Cargo, Linea


def obra():
    return [
        Linea("grupo", 0, "Albañilería"),
        Linea("item", 1, "Muro de 6", 10, 20.0),
        Linea("item", 1, "Muro de 4", 5, 10.0, False),
        Linea("item", 0, "Limpieza", 1, 100.0),
    ]


def test_guardar_y_leer_grupos_subitems_y_cargos(conn):
    cargos = [Cargo("Administración", "porcentaje", 10), Cargo("Utilidad", "monto", 40.0, False)]
    t = db.guardar_cotizacion(1, obra(), cargos, conn)
    assert db.obtener_lineas(1, conn) == obra()
    assert db.obtener_cargos(1, conn) == cargos
    fila = conn.execute("SELECT subtotal, cargos, itbms, total, itbms_tasa FROM cotizaciones WHERE id = 1").fetchone()
    assert tuple(fila) == (t.subtotal, t.cargos_total, t.itbms, t.total, 0.07)
    assert t.subtotal == 350.0 and t.cargos_total == 75.0
    assert db.totales_cotizacion(1, conn).total == t.total


def test_guardar_reemplaza_lo_anterior(conn):
    db.guardar_cotizacion(1, obra(), [Cargo("X", "monto", 1)], conn)
    db.guardar_cotizacion(1, [Linea("item", 0, "Solo uno", 1, 10.0)], [], conn)
    assert len(db.obtener_lineas(1, conn)) == 1 and db.obtener_cargos(1, conn) == []


def test_obtener_items_omite_grupos(conn):
    db.guardar_cotizacion(1, obra(), [], conn)
    assert [d for d, _c, _p in db.obtener_items(1, conn)] == ["Muro de 6", "Muro de 4", "Limpieza"]


def test_guardar_items_legacy_conserva_cargos(conn):
    db.guardar_cotizacion(1, obra(), [Cargo("Administración", "porcentaje", 10)], conn)
    sub, itbms, total = db.guardar_items(1, [("x", 1, 100.0)], conn)
    assert sub == 100.0 and itbms == 7.7 and total == 117.7  # 10% de administración, ambos gravados


def test_la_factura_copia_el_total_con_cargos(conn):
    db.guardar_cotizacion(1, obra(), [Cargo("Administración", "porcentaje", 10)], conn)
    total = conn.execute("SELECT total FROM cotizaciones WHERE id = 1").fetchone()["total"]
    db.cambiar_estado_cotizacion(1, "enviada", conn)
    db.cambiar_estado_cotizacion(1, "aprobada", conn)
    db.generar_factura(1, conn)
    assert conn.execute("SELECT total FROM facturas").fetchone()["total"] == total


def test_migracion_cotizaciones_anteriores(tmp_path, monkeypatch):
    """Una base con el esquema previo (sin grupos, sin empresas, sin costos) conserva sus totales."""
    ruta = tmp_path / "v1.db"
    monkeypatch.setattr(db, "DB_PATH", ruta)
    old = sqlite3.connect(ruta)
    old.executescript("""
        CREATE TABLE clientes (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, identificacion TEXT, contacto TEXT);
        CREATE TABLE cotizaciones (id INTEGER PRIMARY KEY AUTOINCREMENT, numero TEXT UNIQUE NOT NULL,
            cliente_id INTEGER NOT NULL, fecha TEXT NOT NULL, estado TEXT NOT NULL DEFAULT 'borrador',
            subtotal REAL NOT NULL DEFAULT 0, itbms REAL NOT NULL DEFAULT 0, total REAL NOT NULL DEFAULT 0,
            notas TEXT NOT NULL DEFAULT '', proyecto TEXT NOT NULL DEFAULT '');
        CREATE TABLE cotizacion_items (id INTEGER PRIMARY KEY AUTOINCREMENT, cotizacion_id INTEGER NOT NULL,
            descripcion TEXT NOT NULL, cantidad REAL NOT NULL DEFAULT 1, precio_unitario REAL NOT NULL DEFAULT 0);
        CREATE TABLE facturas (id INTEGER PRIMARY KEY AUTOINCREMENT, numero TEXT UNIQUE NOT NULL, cotizacion_id INTEGER,
            cliente_id INTEGER NOT NULL, fecha TEXT NOT NULL, estado_pago TEXT NOT NULL DEFAULT 'pendiente',
            total REAL NOT NULL DEFAULT 0, fecha_pago TEXT, notas TEXT NOT NULL DEFAULT '');
        CREATE TABLE configuracion (clave TEXT PRIMARY KEY, valor TEXT NOT NULL);
        INSERT INTO configuracion VALUES ('empresa_nombre', 'MI EMPRESA SA'), ('empresa_subtitulo', 'ARQUITECTURA'),
                                         ('empresa_correo', 'a@b.com'), ('itbms_tasa', '0');
        INSERT INTO clientes (nombre) VALUES ('Cliente');
        INSERT INTO cotizaciones (numero, cliente_id, fecha, subtotal, itbms, total)
            VALUES ('COT-2025-0001', 1, '2025-01-01', 100, 7, 107), ('COT-2025-0002', 1, '2025-01-02', 100, 0, 100);
        INSERT INTO cotizacion_items (cotizacion_id, descripcion, cantidad, precio_unitario) VALUES (1, 'Algo', 2, 50);
        INSERT INTO facturas (numero, cotizacion_id, cliente_id, fecha, total) VALUES ('FAC-2025-0001', 1, 1, '2025-01-03', 107);
    """)
    old.commit()
    old.close()

    db.init_db()
    c = db.get_connection()
    empresas = db.listar_empresas(c)
    assert len(empresas) == 1 and empresas[0]["nombre"] == "MI EMPRESA SA" and empresas[0]["predeterminada"] == 1
    assert empresas[0]["itbms_tasa"] == 0 and empresas[0]["correo"] == "a@b.com"
    assert c.execute("SELECT COUNT(*) AS n FROM cotizaciones WHERE empresa_id = ?", (empresas[0]["id"],)).fetchone()["n"] == 2
    assert c.execute("SELECT empresa_id FROM facturas").fetchone()["empresa_id"] == empresas[0]["id"]
    lineas = db.obtener_lineas(1, c)
    assert lineas == [Linea("item", 0, "Algo", 2, 50.0, True)]
    assert db.tasa_de_cotizacion(1, c) == 0.07      # deducida de lo ya guardado
    assert db.tasa_de_cotizacion(2, c) == 0.0
    assert db.totales_cotizacion(1, c).total == 107
    assert c.execute("SELECT total FROM cotizaciones WHERE id = 1").fetchone()["total"] == 107  # sin cambios
    db.init_db()  # idempotente
    assert len(db.listar_empresas(db.get_connection())) == 1
    c.close()
