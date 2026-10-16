import pytest
from PySide6.QtWidgets import QMessageBox

from app import db, ui_main


def test_crear_editar_y_eliminar_cliente_db(conn):
    cid = db.guardar_cliente({"nombre": " Beta SA ", "identificacion": "1-2-3", "contacto": "a@b.com"}, conn)
    fila = conn.execute("SELECT * FROM clientes WHERE id = ?", (cid,)).fetchone()
    assert (fila["nombre"], fila["identificacion"], fila["contacto"]) == ("Beta SA", "1-2-3", "a@b.com")
    db.guardar_cliente({"nombre": "Beta SRL", "identificacion": "", "contacto": "x"}, conn, cid)
    assert conn.execute("SELECT nombre, contacto FROM clientes WHERE id = ?", (cid,)).fetchone()["nombre"] == "Beta SRL"
    db.eliminar_cliente(cid, conn)
    assert conn.execute("SELECT COUNT(*) AS n FROM clientes WHERE id = ?", (cid,)).fetchone()["n"] == 0


def test_validaciones_cliente(conn):
    with pytest.raises(ValueError):
        db.guardar_cliente({"nombre": "  "}, conn)
    with pytest.raises(ValueError):
        db.eliminar_cliente(1, conn)          # ACME tiene la cotización COT-2026-0001


def test_ui_seleccionar_edita_y_guarda(conn, qapp, monkeypatch):
    tab = ui_main.ClientesTab()
    assert tab.tabla.rowCount() == 1 and not tab.btn_guardar.isEnabled() and not tab.btn_eliminar.isEnabled()
    tab.tabla.setCurrentCell(0, 1)
    assert tab.nombre_edit.text() == "ACME" and tab.id_edit.text() == "8-123-456"
    assert tab.btn_guardar.isEnabled() and tab.btn_eliminar.isEnabled()
    tab.nombre_edit.setText("ACME Panamá")
    tab.contacto_edit.setText("507-555")
    tab.guardar_cambios()
    fila = conn.execute("SELECT nombre, contacto FROM clientes WHERE id = 1").fetchone()
    assert (fila["nombre"], fila["contacto"]) == ("ACME Panamá", "507-555")
    assert tab.tabla.item(0, 1).text() == "ACME Panamá" and tab.tabla.item(0, 3).text() == "507-555"


def test_ui_agregar_limpia_el_formulario(conn, qapp):
    tab = ui_main.ClientesTab()
    tab.nombre_edit.setText("Nuevo cliente")
    tab.agregar_cliente()
    assert tab.tabla.rowCount() == 2 and tab.nombre_edit.text() == ""
    assert [tab.tabla.item(i, 1).text() for i in range(2)] == ["ACME", "Nuevo cliente"]


def test_ui_eliminar_cliente_con_y_sin_documentos(conn, qapp, monkeypatch):
    nuevo = db.guardar_cliente({"nombre": "Sin documentos"}, conn)
    tab = ui_main.ClientesTab()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.Yes))
    avisos = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: avisos.append(a[2])))
    tab.tabla.setCurrentCell(0, 1)                    # ACME: tiene cotización
    tab.eliminar_cliente()
    assert avisos and "cotización" in avisos[0] and tab.tabla.rowCount() == 2
    fila = next(i for i in range(2) if tab.tabla.item(i, 1).data(0x0100) == nuevo)
    tab.tabla.setCurrentCell(fila, 1)
    tab.eliminar_cliente()
    assert tab.tabla.rowCount() == 1 and tab.nombre_edit.text() == ""


def test_ui_nombre_vacio_avisa(conn, qapp, monkeypatch):
    avisos = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: avisos.append(a[2])))
    tab = ui_main.ClientesTab()
    tab.agregar_cliente()
    assert avisos and "obligatorio" in avisos[0]
