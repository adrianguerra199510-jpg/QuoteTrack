import sqlite3

import pytest
from PySide6.QtWidgets import QInputDialog, QMessageBox

from app import base_cgr, db, ui_biblioteca, ui_items
from app.calculo import Apu, Concepto, Insumo, Linea, OBRA, SERVICIO


def apu():
    return Apu(1.0, [Insumo("material", "Bloque", "uni", 12.5, 1, 1.2), Insumo("mano_obra", "Oficial", "día", 0.1, 1, 90.0)])


def concepto(nombre="Muro", biblioteca=None, **kw):
    return Concepto(None, nombre, "m²", OBRA, 0.0, kw.get("categoria", "Albañilería"), apu(), biblioteca_id=biblioteca)


# ----------------------------------------------------------------- base de datos
def test_biblioteca_inicial_y_conceptos_nuevos_van_a_ella(conn):
    bibliotecas = db.listar_bibliotecas(conn)
    assert [b["nombre"] for b in bibliotecas] == ["Mi biblioteca"] and bibliotecas[0]["n"] == 0
    cid = db.guardar_concepto(concepto(), conn)
    assert db.obtener_concepto(cid, conn).biblioteca_id == db.biblioteca_por_defecto(conn) == bibliotecas[0]["id"]
    assert db.listar_bibliotecas(conn)[0]["n"] == 1


def test_crear_y_renombrar_con_validaciones(conn):
    nueva = db.crear_biblioteca("Obras civiles", conn)
    assert [b["nombre"] for b in db.listar_bibliotecas(conn)] == ["Mi biblioteca", "Obras civiles"]
    with pytest.raises(ValueError):
        db.crear_biblioteca("  ", conn)
    with pytest.raises(ValueError):
        db.crear_biblioteca("obras CIVILES", conn)                  # no distingue mayúsculas
    db.renombrar_biblioteca(nueva, "Obras civiles 2026", conn)
    assert db.listar_bibliotecas(conn)[1]["nombre"] == "Obras civiles 2026"
    db.renombrar_biblioteca(nueva, "Obras civiles 2026", conn)      # el mismo nombre no es conflicto
    with pytest.raises(ValueError):
        db.renombrar_biblioteca(nueva, "Mi biblioteca", conn)


def test_conceptos_se_listan_por_biblioteca(conn):
    a, b = db.biblioteca_por_defecto(conn), db.crear_biblioteca("Otra", conn)
    db.guardar_concepto(concepto("En A"), conn)
    db.guardar_concepto(concepto("En B", biblioteca=b), conn)
    assert [c.descripcion for c in db.listar_conceptos(conn, biblioteca_id=a)] == ["En A"]
    assert [c.descripcion for c in db.listar_conceptos(conn, biblioteca_id=b)] == ["En B"]
    assert {c.descripcion for c in db.listar_conceptos(conn)} == {"En A", "En B"}
    assert db.disciplinas_conceptos(conn, a) == ["Albañilería"]
    # la búsqueda de duplicados es por biblioteca
    assert db.buscar_concepto("En B", "m²", conn, a) is None and db.buscar_concepto("En B", "m²", conn, b)


def test_duplicar_biblioteca_copia_conceptos_y_analisis(conn):
    a = db.biblioteca_por_defecto(conn)
    db.guardar_concepto(concepto("Muro"), conn)
    db.guardar_concepto(Concepto(None, "Diseño", "m²", SERVICIO, 15.0, "Servicios"), conn)
    copia = db.duplicar_biblioteca(a, conn)
    nombres = [b["nombre"] for b in db.listar_bibliotecas(conn)]
    assert nombres == ["Mi biblioteca", "Mi biblioteca (copia)"]
    copiados = db.listar_conceptos(conn, biblioteca_id=copia)
    assert sorted(c.descripcion for c in copiados) == ["Diseño", "Muro"]
    muro = next(c for c in copiados if c.descripcion == "Muro")
    assert muro.apu.insumos == apu().insumos and muro.id != db.listar_conceptos(conn, biblioteca_id=a)[0].id
    # la copia es independiente
    muro.apu.insumos.clear()
    db.guardar_concepto(muro, conn)
    assert len(db.listar_conceptos(conn, "Muro", biblioteca_id=a)[0].apu.insumos) == 2
    assert db.duplicar_biblioteca(a, conn) and "Mi biblioteca (copia 2)" in [
        b["nombre"] for b in db.listar_bibliotecas(conn)]
    with pytest.raises(ValueError):
        db.duplicar_biblioteca(999, conn)


def test_duplicar_la_base_de_la_contraloria_conserva_el_orden(conn):
    base_cgr.importar(conn)
    cgr = db.listar_bibliotecas(conn)[1]["id"]
    copia = db.duplicar_biblioteca(cgr, conn, "Mi copia de costos")
    originales = db.listar_conceptos(conn, biblioteca_id=cgr)
    copiados = db.listar_conceptos(conn, biblioteca_id=copia)
    assert len(copiados) == 1169
    assert [c.descripcion for c in copiados[:5]] == [c.descripcion for c in originales[:5]]
    assert all(c.fuente == "" and c.codigo == "" for c in copiados)       # la copia ya no se sincroniza con la fuente
    assert conn.execute("SELECT COUNT(*) AS n FROM concepto_insumos").fetchone()["n"] == 2 * conn.execute(
        "SELECT COUNT(*) AS n FROM concepto_insumos WHERE concepto_id IN (SELECT id FROM conceptos WHERE biblioteca_id = ?)",
        (cgr,)).fetchone()["n"]


def test_eliminar_biblioteca(conn):
    a = db.biblioteca_por_defecto(conn)
    with pytest.raises(ValueError):
        db.eliminar_biblioteca(a, conn)                              # debe quedar al menos una
    b = db.crear_biblioteca("Temporal", conn)
    db.guardar_concepto(concepto("En B", biblioteca=b), conn)
    db.guardar_concepto(concepto("En A"), conn)
    assert db.eliminar_biblioteca(b, conn) == 1
    assert [x["nombre"] for x in db.listar_bibliotecas(conn)] == ["Mi biblioteca"]
    assert [c.descripcion for c in db.listar_conceptos(conn)] == ["En A"]
    assert conn.execute("SELECT COUNT(*) AS n FROM concepto_insumos").fetchone()["n"] == 2   # solo los de «En A»


def test_eliminar_biblioteca_no_cambia_las_cotizaciones(conn):
    b = db.crear_biblioteca("Temporal", conn)
    c = db.obtener_concepto(db.guardar_concepto(concepto("Muro", biblioteca=b), conn), conn)
    db.guardar_cotizacion(1, [db.linea_desde_concepto(c, 4.0)], [], conn)
    total = db.totales_cotizacion(1, conn).total
    db.eliminar_biblioteca(b, conn)
    assert db.totales_cotizacion(1, conn).total == total and len(db.obtener_lineas(1, conn)[0].apu.insumos) == 2


def test_copiar_conceptos_a_otra_biblioteca(conn):
    otra = db.crear_biblioteca("Destino", conn)
    ids = [db.guardar_concepto(concepto(n), conn) for n in ("Uno", "Dos")]
    assert db.copiar_conceptos(ids, otra, conn) == 2
    assert sorted(c.descripcion for c in db.listar_conceptos(conn, biblioteca_id=otra)) == ["Dos", "Uno"]
    assert len(db.listar_conceptos(conn, biblioteca_id=db.biblioteca_por_defecto(conn))) == 2     # el origen sigue igual
    assert db.listar_conceptos(conn, biblioteca_id=otra)[0].apu.insumos == apu().insumos


def test_migracion_de_conceptos_existentes_a_bibliotecas(tmp_path, monkeypatch):
    """Una base con conceptos creados a mano y otros importados (sin bibliotecas) los reparte sin perder nada."""
    ruta = tmp_path / "v3.db"
    monkeypatch.setattr(db, "DB_PATH", ruta)
    db.init_db()
    c = db.get_connection()
    c.execute("DROP TABLE concepto_insumos")
    c.execute("DROP TABLE conceptos")
    c.execute("DROP TABLE bibliotecas")
    c.executescript("""
        CREATE TABLE conceptos (id INTEGER PRIMARY KEY AUTOINCREMENT, descripcion TEXT NOT NULL, unidad TEXT NOT NULL DEFAULT '',
            modalidad TEXT NOT NULL DEFAULT 'servicio', precio REAL NOT NULL DEFAULT 0, categoria TEXT NOT NULL DEFAULT '',
            apu_base REAL NOT NULL DEFAULT 1, codigo TEXT NOT NULL DEFAULT '', fuente TEXT NOT NULL DEFAULT '');
        CREATE TABLE concepto_insumos (id INTEGER PRIMARY KEY AUTOINCREMENT, concepto_id INTEGER NOT NULL REFERENCES conceptos(id)
            ON DELETE CASCADE, categoria TEXT NOT NULL, descripcion TEXT NOT NULL DEFAULT '', unidad TEXT NOT NULL DEFAULT '',
            rendimiento REAL NOT NULL DEFAULT 1, coeficiente REAL NOT NULL DEFAULT 1, precio REAL NOT NULL DEFAULT 0,
            ref_categoria TEXT NOT NULL DEFAULT '');
        INSERT INTO conceptos (descripcion, unidad, modalidad, precio) VALUES ('Mío', 'm²', 'servicio', 5);
        INSERT INTO conceptos (descripcion, unidad, modalidad, codigo, fuente) VALUES ('Importado 81', 'm²', 'obra', '81', 'Fuente X');
        INSERT INTO conceptos (descripcion, unidad, modalidad, codigo, fuente) VALUES ('Importado 46', 'm²', 'obra', '46', 'Fuente X');
        INSERT INTO concepto_insumos (concepto_id, categoria, descripcion, precio) VALUES (2, 'material', 'X', 3);
    """)
    c.commit()
    c.close()
    db.init_db()
    db.init_db()                                                    # idempotente
    c = db.get_connection()
    assert [(b["nombre"], b["n"]) for b in db.listar_bibliotecas(c)] == [("Mi biblioteca", 1), ("Fuente X", 2)]
    fuente = db.listar_bibliotecas(c)[1]["id"]
    assert [x.descripcion for x in db.listar_conceptos(c, biblioteca_id=fuente)] == ["Importado 46", "Importado 81"]  # por página
    assert db.obtener_concepto(2, c).apu.insumos[0].precio == 3
    c.close()


# ----------------------------------------------------------------- interfaz
@pytest.fixture
def tab(conn, qapp):
    return ui_biblioteca.BibliotecaTab()


def entradas(monkeypatch, texto=None, item=None):
    """Simula QInputDialog.getText / getItem."""
    if texto is not None:
        monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: (texto, texto != "")))
    if item is not None:
        monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: (item, True)))


def test_ui_crear_renombrar_duplicar_y_eliminar_biblioteca(tab, conn, monkeypatch):
    assert tab.bib_combo.count() == 1 and not tab.btn_bib_eliminar.isEnabled()      # la última no se elimina
    entradas(monkeypatch, "Obras civiles")
    tab.nueva_biblioteca()
    assert tab.bib_combo.count() == 2 and tab._nombre_actual() == "Obras civiles" and tab.btn_bib_eliminar.isEnabled()
    entradas(monkeypatch, "Obras civiles 2026")
    tab.renombrar_biblioteca()
    assert tab._nombre_actual() == "Obras civiles 2026"
    tab.duplicar_biblioteca()
    assert tab.bib_combo.count() == 3 and tab._nombre_actual() == "Obras civiles 2026 (copia)"
    avisos = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: avisos.append(a[2])))
    entradas(monkeypatch, "Mi biblioteca")                           # nombre repetido: avisa y no cambia
    tab.renombrar_biblioteca()
    assert avisos and "Ya existe" in avisos[0] and tab._nombre_actual() == "Obras civiles 2026 (copia)"
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.No))
    tab.eliminar_biblioteca()
    assert tab.bib_combo.count() == 3                                # cancelar no elimina
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.Yes))
    tab.eliminar_biblioteca()
    assert tab.bib_combo.count() == 2 and tab._nombre_actual() != "Obras civiles 2026 (copia)"


def test_ui_nueva_biblioteca_cancelada_o_sin_nombre(tab, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False)))
    tab.nueva_biblioteca()
    assert tab.bib_combo.count() == 1
    avisos = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: avisos.append(a[2])))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("   ", True)))
    tab.nueva_biblioteca()
    assert avisos and tab.bib_combo.count() == 1


class FalsoConcepto:
    def __init__(self, concepto=None, parent=None):
        self._c = concepto or Concepto()

    def exec(self):
        return 1

    def concepto(self):
        c = self._c
        return Concepto(c.id, c.descripcion or "Nuevo", "uni", SERVICIO, 42.0, "Varios", None, biblioteca_id=c.biblioteca_id)


def test_ui_los_conceptos_nuevos_van_a_la_biblioteca_elegida(tab, conn, monkeypatch):
    monkeypatch.setattr(ui_biblioteca, "ConceptoDialog", FalsoConcepto)
    entradas(monkeypatch, "Segunda")
    tab.nueva_biblioteca()                                           # queda seleccionada la nueva
    tab.nuevo()
    assert tab.tabla.rowCount() == 1 and "(1)" in tab.bib_combo.currentText()
    tab.bib_combo.setCurrentIndex(0)
    assert tab.tabla.rowCount() == 0 and "vacía" in tab.lbl_total.text()
    assert [b["n"] for b in db.listar_bibliotecas(conn)] == [0, 1]


def test_ui_copiar_conceptos_a_otra_biblioteca(tab, conn, monkeypatch):
    db.guardar_concepto(concepto("Uno"), conn)
    db.guardar_concepto(concepto("Dos"), conn)
    db.crear_biblioteca("Destino", conn)
    tab.refrescar()
    avisos = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: avisos.append(a[2])))
    tab.tabla.selectAll()
    assert tab.btn_copiar.isEnabled()
    entradas(monkeypatch, item="Destino")
    tab.copiar_a_otra()
    assert "2 concepto(s)" in avisos[0]
    assert [b["n"] for b in db.listar_bibliotecas(conn)] == [2, 2]
    tab.bib_combo.setCurrentIndex(1)
    assert tab.tabla.rowCount() == 2


def test_ui_eliminar_varios_conceptos(tab, conn, monkeypatch):
    for n in ("Uno", "Dos", "Tres"):
        db.guardar_concepto(concepto(n), conn)
    tab.refrescar()
    tab.tabla.selectRow(0)
    tab.tabla.selectAll()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.Yes))
    tab.eliminar()
    assert tab.tabla.rowCount() == 0 and db.listar_bibliotecas(conn)[0]["n"] == 0


def test_ui_selector_filtra_por_biblioteca(conn, qapp):
    otra = db.crear_biblioteca("Otra", conn)
    db.guardar_concepto(concepto("En la primera"), conn)
    db.guardar_concepto(concepto("En la otra", biblioteca=otra), conn)
    sel = ui_biblioteca.SelectorConceptosDialog()
    assert sel.biblioteca.count() == 3 and sel.tabla.rowCount() == 2
    sel.biblioteca.setCurrentIndex(sel.biblioteca.findData(otra))
    assert sel.tabla.rowCount() == 1 and sel.tabla.item(0, 1).text() == "En la otra"


def test_guardar_desde_la_cotizacion_pregunta_la_biblioteca_si_hay_varias(conn, qapp, monkeypatch):
    destino = db.crear_biblioteca("Destino", conn)
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: None))
    d = ui_items.ItemsDialog(1, "COT-2026-0001", True)
    d.lineas[:] = [Linea("item", 0, "Muro nuevo", 1, 0.0, True, "m²", OBRA, apu())]
    d._render_lineas(0)
    d.tabla.setCurrentCell(0, ui_items.COL_DESC)
    entradas(monkeypatch, item="Destino")
    d.guardar_en_biblioteca()
    assert [(c.descripcion, c.biblioteca_id) for c in db.listar_conceptos(conn)] == [("Muro nuevo", destino)]
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("", False)))   # cancelar
    d.lineas[0].descripcion = "Otro"
    d.guardar_en_biblioteca()
    assert len(db.listar_conceptos(conn)) == 1
