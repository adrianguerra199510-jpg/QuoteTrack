import importlib.util
import sqlite3
from pathlib import Path

import pytest

from app import calculo, db
from app.calculo import Apu, Concepto, ConfigApu, Indirecto, Insumo, Linea, OBRA, SERVICIO


def cargar_script(nombre):
    spec = importlib.util.spec_from_file_location(
        nombre, Path(__file__).resolve().parent.parent / "scripts" / f"{nombre}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def apu_simple():
    return Apu(1.0, [
        Insumo("material", "Bloque de 6", "uni", 12.5, 1, 1.2),                 # 15.00
        Insumo("mano_obra", "Calificado", "día", 0.1, 1, 90.0),                 # 9.00
        Insumo("auxiliar", "Herramienta menor", "%", 1, 0.05, 0, "mano_obra"),   # 5 % de 9.00 = 0.45
        Insumo("subcontrato", "Transporte", "viaje", 1, 0.02, 100.0),           # 2.00
    ])


def test_costos_por_categoria_y_filas_de_porcentaje():
    costos = calculo.costos_apu(apu_simple())
    assert costos == pytest.approx({"material": 15.0, "mano_obra": 9.0, "auxiliar": 0.45, "subcontrato": 2.0})
    assert calculo.costo_unitario(apu_simple()) == pytest.approx(26.45)
    herramienta = apu_simple().insumos[2]
    assert calculo.costo_insumo(apu_simple(), herramienta) == pytest.approx(0.45)


def test_precio_unitario_aplica_coeficientes_por_categoria():
    cfg = ConfigApu(coef_material=0.15, coef_mano_obra=0.20, coef_auxiliar=0.10, coef_subcontrato=0.0)
    esperado = 15 * 1.15 + 9 * 1.20 + 0.45 * 1.10 + 2 * 1.0
    assert calculo.precio_unitario(apu_simple(), cfg) == pytest.approx(esperado, abs=0.01)


def test_indirectos_no_se_aplican_a_materiales():
    cfg = ConfigApu(0.10, 0.10, 0.10, 0.10)
    con = calculo.precio_unitario(apu_simple(), cfg, coef_indirectos=0.20)
    esperado = 15 * 1.10 + (9 + 0.45 + 2) * 1.30
    assert con == pytest.approx(esperado, abs=0.01)


def test_rendimiento_base_divide_el_costo():
    apu = apu_simple()
    apu.base = 2.0                      # el análisis produce 2 unidades
    assert calculo.costo_unitario(apu) == pytest.approx(26.45 / 2)
    assert calculo.precio_unitario(apu, ConfigApu(0, 0, 0, 0)) == round(26.45 / 2, 2)


def test_item_de_obra_toma_su_precio_del_apu_y_servicio_conserva_el_suyo():
    obra = Linea("item", 0, "Muro", 10, 0.0, modalidad=OBRA, apu=apu_simple())
    servicio = Linea("item", 0, "Diseño", 1, 500.0)
    t = calculo.calcular([obra, servicio], tasa=0.07, cfg=ConfigApu(0, 0, 0, 0))
    assert obra.precio == 26.45 and servicio.precio == 500.0
    assert t.subtotal == round(264.5 + 500, 2)
    assert t.costo_directo == 264.5


def test_coeficiente_de_indirectos_es_indirectos_sobre_costo_directo():
    cfg = ConfigApu(0, 0, 0, 0, [Indirecto("Patio", 1, 2, 500), Indirecto("Grúa", 2, 8, 60)])   # 1000 + 960
    obra = Linea("item", 0, "Muro", 10, 0.0, modalidad=OBRA, apu=apu_simple())
    directo, coef = calculo.coeficiente_indirectos([obra], cfg)
    assert directo == pytest.approx(264.5) and coef == pytest.approx(1960 / 264.5)
    assert calculo.coeficiente_indirectos([], cfg) == (0, 0.0)      # sin costo directo no hay coeficiente


def test_desglose_suma_el_precio_de_venta():
    cfg = ConfigApu(0.15, 0.15, 0.15, 0.15)
    filas = calculo.desglose_apu(apu_simple(), cfg, 0.1)
    assert sum(f[3] for f in filas) == pytest.approx(calculo.precio_unitario(apu_simple(), cfg, 0.1), abs=0.01)
    assert [f[0] for f in filas] == list(calculo.CATEGORIAS)


def test_reproduce_la_hoja_valla_mariano_rivera(conn):
    """Totales de la hoja de cálculo original: subtotal 65,159.29 (±0.01 por redondeo), ITBMS 4,561.15, total 69,720.45."""
    ejemplo = cargar_script("ejemplo_valla")
    numero = ejemplo.crear_ejemplo(conn)
    cot_id = conn.execute("SELECT id FROM cotizaciones WHERE numero = ?", (numero,)).fetchone()["id"]
    t = db.totales_cotizacion(cot_id, conn)
    assert t.costo_directo == 49303.73
    assert t.coef_indirectos == pytest.approx(0.1715894, abs=1e-6)
    assert [l.precio for l in db.obtener_lineas(cot_id, conn)] == [48556.56, 16602.74]
    assert t.subtotal == 65159.30 and t.itbms == 4561.15 and t.total == 69720.45
    assert [c.descripcion[:30] for c in db.listar_conceptos(conn)] == [
        "Fabricación e instalación de e", "Fabricación e instalación de p"]
    assert ejemplo.crear_ejemplo(conn) is None                      # no duplica


def test_apu_se_guarda_y_se_lee(conn):
    cfg = ConfigApu(0.15, 0.12, 0.10, 0.05, [Indirecto("Patio", 1, 2, 500.0)])
    lineas = [Linea("item", 0, "Muro", 10, 0.0, True, "m²", OBRA, apu_simple()),
              Linea("item", 0, "Plano", 1, 300.0, False, "uni")]
    t = db.guardar_cotizacion(1, lineas, [], conn, cfg=cfg)
    leidas = db.obtener_lineas(1, conn)
    assert [(l.modalidad, l.unidad) for l in leidas] == [(OBRA, "m²"), (SERVICIO, "uni")]
    assert leidas[0].apu.insumos == apu_simple().insumos and leidas[1].apu is None
    cfg2 = db.obtener_config_apu(1, conn)
    assert (cfg2.coef_material, cfg2.coef_mano_obra, cfg2.coef_auxiliar, cfg2.coef_subcontrato) == \
        pytest.approx((0.15, 0.12, 0.10, 0.05))
    assert cfg2.indirectos == [Indirecto("Patio", 1, 2, 500.0)]
    assert db.totales_cotizacion(1, conn).total == t.total          # el recálculo coincide con lo guardado
    # guardar sin cfg conserva los coeficientes e indirectos existentes
    db.guardar_cotizacion(1, leidas, [], conn)
    assert db.obtener_config_apu(1, conn).indirectos == [Indirecto("Patio", 1, 2, 500.0)]


def test_cambiar_a_servicio_descarta_el_analisis(conn):
    db.guardar_cotizacion(1, [Linea("item", 0, "Muro", 1, 0.0, modalidad=OBRA, apu=apu_simple())], [], conn)
    l = db.obtener_lineas(1, conn)[0]
    l.modalidad, l.apu = SERVICIO, None
    db.guardar_cotizacion(1, [l], [], conn)
    assert conn.execute("SELECT COUNT(*) AS n FROM apu_insumos").fetchone()["n"] == 0
    assert db.obtener_lineas(1, conn)[0].precio == l.precio


def test_coeficientes_por_defecto_y_cotizacion_conserva_los_suyos(conn):
    assert db.coef_apu_defecto(conn).coef_material == 0.15
    db.guardar_coef_apu_defecto({"material": 20, "mano_obra": 18}, conn)
    nueva, _ = db.crear_cotizacion(1, conn)
    db.guardar_coef_apu_defecto({"material": 5}, conn)             # cambia después de crearla
    cfg = db.obtener_config_apu(nueva, conn)
    assert cfg.coef_material == pytest.approx(0.20) and cfg.coef_mano_obra == pytest.approx(0.18)
    assert db.coef_apu_defecto(conn).coef_material == pytest.approx(0.05)


def test_migracion_desde_el_esquema_anterior(tmp_path, monkeypatch):
    """Base del esquema previo (sin unidad, modalidad ni APU): todo sigue como servicio y con los mismos totales."""
    ruta = tmp_path / "v2.db"
    monkeypatch.setattr(db, "DB_PATH", ruta)
    old = sqlite3.connect(ruta)
    old.executescript("""
        CREATE TABLE clientes (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, identificacion TEXT, contacto TEXT);
        CREATE TABLE empresas (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, subtitulo TEXT NOT NULL DEFAULT '',
            correo TEXT NOT NULL DEFAULT '', telefono TEXT NOT NULL DEFAULT '', direccion TEXT NOT NULL DEFAULT '',
            ruc TEXT NOT NULL DEFAULT '', itbms_tasa REAL NOT NULL DEFAULT 7, logo BLOB, predeterminada INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE cotizaciones (id INTEGER PRIMARY KEY AUTOINCREMENT, numero TEXT UNIQUE NOT NULL, cliente_id INTEGER NOT NULL,
            fecha TEXT NOT NULL, estado TEXT NOT NULL DEFAULT 'borrador', subtotal REAL NOT NULL DEFAULT 0,
            itbms REAL NOT NULL DEFAULT 0, total REAL NOT NULL DEFAULT 0, notas TEXT NOT NULL DEFAULT '',
            proyecto TEXT NOT NULL DEFAULT '', empresa_id INTEGER, cargos REAL NOT NULL DEFAULT 0, itbms_tasa REAL);
        CREATE TABLE cotizacion_items (id INTEGER PRIMARY KEY AUTOINCREMENT, cotizacion_id INTEGER NOT NULL,
            descripcion TEXT NOT NULL, cantidad REAL NOT NULL DEFAULT 1, precio_unitario REAL NOT NULL DEFAULT 0,
            tipo TEXT NOT NULL DEFAULT 'item', nivel INTEGER NOT NULL DEFAULT 0, aplica_itbms INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE cotizacion_cargos (id INTEGER PRIMARY KEY AUTOINCREMENT, cotizacion_id INTEGER NOT NULL,
            concepto TEXT NOT NULL, tipo TEXT NOT NULL DEFAULT 'porcentaje', valor REAL NOT NULL DEFAULT 0,
            aplica_itbms INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE facturas (id INTEGER PRIMARY KEY AUTOINCREMENT, numero TEXT UNIQUE NOT NULL, cotizacion_id INTEGER,
            cliente_id INTEGER NOT NULL, fecha TEXT NOT NULL, estado_pago TEXT NOT NULL DEFAULT 'pendiente',
            total REAL NOT NULL DEFAULT 0, fecha_pago TEXT, notas TEXT NOT NULL DEFAULT '', empresa_id INTEGER);
        CREATE TABLE configuracion (clave TEXT PRIMARY KEY, valor TEXT NOT NULL);
        INSERT INTO clientes (nombre) VALUES ('C');
        INSERT INTO empresas (nombre, predeterminada) VALUES ('E', 1);
        INSERT INTO cotizaciones (numero, cliente_id, fecha, subtotal, itbms, total, empresa_id, itbms_tasa)
            VALUES ('COT-2026-0001', 1, '2026-01-01', 200, 14, 214, 1, 0.07);
        INSERT INTO cotizacion_items (cotizacion_id, descripcion, cantidad, precio_unitario) VALUES (1, 'Algo', 2, 100);
    """)
    old.commit()
    old.close()
    db.init_db()
    db.init_db()
    c = db.get_connection()
    l = db.obtener_lineas(1, c)[0]
    assert (l.modalidad, l.unidad, l.apu, l.precio) == (SERVICIO, "", None, 100.0)
    assert db.totales_cotizacion(1, c).total == 214
    assert db.obtener_config_apu(1, c).coef_material == 0.15
    c.close()


# ----------------------------------------------------------------- biblioteca
def concepto_obra():
    return Concepto(None, "Muro de bloque de 6", "m²", OBRA, 0.0, "Albañilería", apu_simple())


def test_guardar_leer_y_listar_conceptos(conn):
    cid = db.guardar_concepto(concepto_obra(), conn)
    sid = db.guardar_concepto(Concepto(None, "Diseño estructural", "m²", SERVICIO, 12.5, "Servicios"), conn)
    c = db.obtener_concepto(cid, conn)
    assert (c.descripcion, c.unidad, c.modalidad, c.categoria) == ("Muro de bloque de 6", "m²", OBRA, "Albañilería")
    assert c.apu.insumos == apu_simple().insumos and c.precio == 0
    s = db.obtener_concepto(sid, conn)
    assert s.apu is None and s.precio == 12.5
    assert [x.descripcion for x in db.listar_conceptos(conn)] == ["Muro de bloque de 6", "Diseño estructural"]
    assert [x.id for x in db.listar_conceptos(conn, "muro")] == [cid]
    assert [x.id for x in db.listar_conceptos(conn, "servicios")] == [sid]        # busca también por categoría
    assert [x.id for x in db.listar_conceptos(conn, modalidad=SERVICIO)] == [sid]


def test_actualizar_concepto_reemplaza_el_analisis(conn):
    cid = db.guardar_concepto(concepto_obra(), conn)
    c = db.obtener_concepto(cid, conn)
    c.apu.insumos = c.apu.insumos[:1]
    c.descripcion = "Muro de bloque de 6 (editado)"
    db.guardar_concepto(c, conn)
    nuevo = db.obtener_concepto(cid, conn)
    assert len(nuevo.apu.insumos) == 1 and nuevo.descripcion.endswith("(editado)")
    assert conn.execute("SELECT COUNT(*) AS n FROM concepto_insumos").fetchone()["n"] == 1
    c.modalidad, c.precio = SERVICIO, 80.0                                       # pasa a servicio: sin análisis
    db.guardar_concepto(c, conn)
    assert db.obtener_concepto(cid, conn).apu is None
    assert conn.execute("SELECT COUNT(*) AS n FROM concepto_insumos").fetchone()["n"] == 0


def test_validaciones_del_concepto(conn):
    with pytest.raises(ValueError):
        db.guardar_concepto(Concepto(None, "  ", "m²"), conn)
    with pytest.raises(ValueError):
        db.guardar_concepto(Concepto(None, "X", modalidad="otra"), conn)
    with pytest.raises(ValueError):
        db.guardar_concepto(Concepto(None, "X", modalidad=OBRA, apu=Apu(0.0)), conn)


def test_duplicar_y_eliminar_concepto(conn):
    cid = db.guardar_concepto(concepto_obra(), conn)
    copia = db.duplicar_concepto(cid, conn)
    assert db.obtener_concepto(copia, conn).descripcion == "Muro de bloque de 6 (copia)"
    assert db.obtener_concepto(copia, conn).apu.insumos == apu_simple().insumos
    db.eliminar_concepto(cid, conn)
    assert db.obtener_concepto(cid, conn) is None
    assert db.obtener_concepto(copia, conn) is not None                            # la copia sigue
    assert conn.execute("SELECT COUNT(*) AS n FROM concepto_insumos").fetchone()["n"] == len(apu_simple().insumos)


def test_buscar_concepto_por_descripcion_y_unidad(conn):
    cid = db.guardar_concepto(concepto_obra(), conn)
    assert db.buscar_concepto("Muro de bloque de 6", "m²", conn).id == cid
    assert db.buscar_concepto("Muro de bloque de 6", "m³", conn) is None


def test_precio_referencial_usa_los_coeficientes_por_defecto(conn):
    obra = db.obtener_concepto(db.guardar_concepto(concepto_obra(), conn), conn)
    db.guardar_coef_apu_defecto({c: 0 for c in calculo.CATEGORIAS}, conn)
    assert db.precio_referencial(obra, conn) == 26.45
    db.guardar_coef_apu_defecto({c: 10 for c in calculo.CATEGORIAS}, conn)
    assert db.precio_referencial(obra, conn) == pytest.approx(26.45 * 1.10, abs=0.01)
    assert db.precio_referencial(Concepto(None, "S", modalidad=SERVICIO, precio=99.0), conn) == 99.0


def test_linea_desde_concepto_es_una_copia_independiente(conn):
    c = db.obtener_concepto(db.guardar_concepto(concepto_obra(), conn), conn)
    l = db.linea_desde_concepto(c, 3.0, nivel=1)
    assert (l.nivel, l.cantidad, l.modalidad, l.unidad) == (1, 3.0, OBRA, "m²")
    l.apu.insumos[0].precio = 999
    assert db.obtener_concepto(c.id, conn).apu.insumos[0].precio == 1.2           # la biblioteca no cambia
    s = db.linea_desde_concepto(Concepto(None, "Diseño", "m²", SERVICIO, 12.5))
    assert s.modalidad == SERVICIO and s.apu is None and s.precio == 12.5


def test_concepto_desde_linea(conn):
    l = Linea("item", 1, "Muro", 4, 0.0, True, "m²", OBRA, apu_simple())
    c = db.concepto_desde_linea(l, "Albañilería")
    assert (c.descripcion, c.unidad, c.modalidad, c.categoria, c.precio) == ("Muro", "m²", OBRA, "Albañilería", 0.0)
    c.apu.insumos.clear()
    assert len(l.apu.insumos) == 4                                                 # copia profunda
    s = db.concepto_desde_linea(Linea("item", 0, "Plano", 1, 300.0, unidad="uni"))
    assert s.modalidad == SERVICIO and s.precio == 300.0 and s.apu is None
