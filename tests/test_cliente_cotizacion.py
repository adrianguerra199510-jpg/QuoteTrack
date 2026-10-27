import pytest
from PySide6.QtWidgets import QMessageBox

from app import db, ui_items, ui_main
from tests.test_menu_contextual import tab  # noqa: F401  (fixture: pestaña de cotizaciones con la cotización 1)


@pytest.fixture
def dos_clientes(conn):
    cid = db.guardar_cliente({"nombre": "BETA SA"}, conn)
    return cid


def test_cambiar_cliente_solo_en_borrador(conn, dos_clientes):
    db.cambiar_cliente_cotizacion(1, dos_clientes, conn)
    assert conn.execute("SELECT cliente_id FROM cotizaciones WHERE id = 1").fetchone()[0] == dos_clientes
    db.cambiar_estado_cotizacion(1, "enviada", conn)
    with pytest.raises(ValueError):
        db.cambiar_cliente_cotizacion(1, 1, conn)
    with pytest.raises(ValueError):
        db.cambiar_cliente_cotizacion(999, 1, conn)


def test_boton_y_menu_cambian_cliente(tab, conn, dos_clientes, monkeypatch):
    monkeypatch.setattr(ui_main.CotizacionesTab, "_elegir_cliente", staticmethod(lambda p, cl, a: dos_clientes))
    assert tab.btn_cliente.isEnabled()
    assert any(a.text() == "Cambiar cliente…" and a.isEnabled() for a in tab.construir_menu().actions())
    tab.cambiar_cliente()
    assert tab.tabla.item(0, 1).text() == "BETA SA"
    db.cambiar_estado_cotizacion(1, "enviada", conn)
    tab.refrescar()
    assert not tab.btn_cliente.isEnabled()
    assert not [a for a in tab.construir_menu().actions() if a.text() == "Cambiar cliente…"][0].isEnabled()


def test_filtrar_por_cliente(tab, conn, dos_clientes):
    db.crear_cotizacion(dos_clientes, conn)
    tab.refrescar()
    assert tab.tabla.rowCount() == 2
    tab.filtro.cliente.setCurrentIndex(tab.filtro.cliente.findData(dos_clientes))
    assert tab.tabla.rowCount() == 1 and tab.tabla.item(0, 1).text() == "BETA SA"
    tab.filtro.cliente.setCurrentIndex(0)
    assert tab.tabla.rowCount() == 2


def test_editor_cambia_cliente(conn, dos_clientes, qapp):
    d = ui_items.ItemsDialog(1, "COT-2026-0001", editable=True)
    assert d.cliente_combo.isEnabled()
    d.cliente_combo.setCurrentIndex(d.cliente_combo.findData(dos_clientes))
    assert d._guardar_en_db()
    assert conn.execute("SELECT cliente_id FROM cotizaciones WHERE id = 1").fetchone()[0] == dos_clientes
    assert not ui_items.ItemsDialog(1, "COT-2026-0001", editable=False).cliente_combo.isEnabled()
