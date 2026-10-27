import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QMessageBox

from app import db, ui_main
from app.calculo import Apu, ConfigApu, Cargo, Indirecto, Insumo, Linea, OBRA


def acciones(menu):
    """{texto: acción} del menú (sin separadores)."""
    return {a.text(): a for a in menu.actions() if not a.isSeparator()}


def disparar(menu, texto):
    acciones(menu)[texto].trigger()


@pytest.fixture
def tab(conn, qapp):
    ventana = ui_main.MainWindow()
    t = ventana.cotizaciones_tab
    t._ventana = ventana                      # mantiene viva la ventana (si no, Qt borra la pestaña)
    t.refrescar()
    t.tabla.setCurrentCell(0, 0)
    return t


def preparar_aprobada(conn):
    db.cambiar_estado_cotizacion(1, "enviada", conn)
    db.cambiar_estado_cotizacion(1, "aprobada", conn)


# ----------------------------------------------------------------- base de datos
def test_duplicar_cotizacion_copia_todo(conn):
    apu = Apu(1.0, [Insumo("material", "Bloque", "uni", 10, 1, 2.0)])
    cfg = ConfigApu(0.10, 0.2, 0.3, 0.4, [Indirecto("Patio", 1, 2, 500.0)])
    db.guardar_cotizacion(1, [Linea("grupo", 0, "G"), Linea("item", 1, "Muro", 3, 0.0, False, "m²", OBRA, apu)],
                          [Cargo("Admin", "porcentaje", 10)], conn, cfg=cfg)
    db.guardar_notas(1, "Mis notas", conn)
    db.guardar_proyecto(1, "Casa", conn)
    db.cambiar_estado_cotizacion(1, "enviada", conn)
    nuevo, numero = db.duplicar_cotizacion(1, conn)
    assert numero == "COT-2026-0002" and nuevo != 1
    fila = conn.execute("SELECT * FROM cotizaciones WHERE id = ?", (nuevo,)).fetchone()
    assert (fila["estado"], fila["cliente_id"], fila["proyecto"], fila["notas"]) == ("borrador", 1, "Casa", "Mis notas")
    assert db.obtener_lineas(nuevo, conn) == db.obtener_lineas(1, conn)
    assert db.obtener_cargos(nuevo, conn) == db.obtener_cargos(1, conn)
    assert db.obtener_config_apu(nuevo, conn) == db.obtener_config_apu(1, conn)
    assert db.totales_cotizacion(nuevo, conn) == db.totales_cotizacion(1, conn)
    # independiente de la original
    db.guardar_cotizacion(nuevo, [Linea("item", 0, "Otra cosa", 1, 5.0)], [], conn)
    assert len(db.obtener_lineas(1, conn)) == 2


def test_duplicar_inexistente(conn):
    with pytest.raises(ValueError):
        db.duplicar_cotizacion(999, conn)


def test_eliminar_cotizacion_borra_sus_datos(conn):
    apu = Apu(1.0, [Insumo("material", "Bloque", "uni", 10, 1, 2.0)])
    db.guardar_cotizacion(1, [Linea("item", 0, "Muro", 3, 0.0, True, "m²", OBRA, apu)], [Cargo("Admin", "monto", 5)], conn,
                          cfg=ConfigApu(0.1, 0.1, 0.1, 0.1, [Indirecto("Patio", 1, 1, 100.0)]))
    nueva, _ = db.crear_cotizacion(1, conn)
    assert db.eliminar_cotizacion(1, conn) == "COT-2026-0001"
    assert conn.execute("SELECT COUNT(*) AS n FROM cotizaciones").fetchone()["n"] == 1
    for tabla in ("cotizacion_items", "apu_insumos", "cotizacion_cargos", "cotizacion_indirectos"):
        assert conn.execute(f"SELECT COUNT(*) AS n FROM {tabla}").fetchone()["n"] == 0, tabla
    assert conn.execute("SELECT id FROM cotizaciones").fetchone()["id"] == nueva


def test_no_se_elimina_una_cotizacion_con_factura(conn):
    preparar_aprobada(conn)
    db.generar_factura(1, conn)
    with pytest.raises(ValueError, match="FAC-2026-0001"):
        db.eliminar_cotizacion(1, conn)
    assert conn.execute("SELECT COUNT(*) AS n FROM cotizaciones").fetchone()["n"] == 1
    with pytest.raises(ValueError):
        db.eliminar_cotizacion(999, conn)


# ----------------------------------------------------------------- menú del clic derecho
def test_menu_de_un_borrador(tab):
    m = tab.construir_menu()
    a = acciones(m)
    assert list(a) == ["Abrir / Editar", "Vista previa", "Resumen de costos", "Cambiar cliente…", "Cambiar estado a", "Generar factura", "Exportar PDF",
                       "Exportar Word", "Duplicar cotización", "Eliminar cotización…"]
    assert not a["Generar factura"].isEnabled() and a["Cambiar estado a"].isEnabled()
    assert [x.text() for x in a["Cambiar estado a"].menu().actions()] == ["Enviada"]


def test_menu_segun_el_estado(tab, conn):
    preparar_aprobada(conn)
    tab.refrescar()
    tab.tabla.setCurrentCell(0, 0)
    a = acciones(tab.construir_menu())
    assert a["Ver detalle"] and a["Generar factura"].isEnabled()
    assert not a["Cambiar estado a"].isEnabled()                    # aprobada: sin más transiciones


def test_menu_enviada_ofrece_aprobar_o_rechazar(tab, conn):
    db.cambiar_estado_cotizacion(1, "enviada", conn)
    tab.refrescar()
    tab.tabla.setCurrentCell(0, 0)
    sub = acciones(tab.construir_menu())["Cambiar estado a"].menu()
    assert [x.text() for x in sub.actions()] == ["Aprobada", "Rechazada"]


def test_clic_derecho_selecciona_la_fila_y_abre_el_menu(tab, conn, monkeypatch):
    db.crear_cotizacion(1, conn)
    tab.refrescar()
    abiertos = []
    monkeypatch.setattr(tab, "_mostrar_menu", lambda menu, punto: abiertos.append((menu, punto)))
    tab.tabla.setCurrentCell(0, 0)
    y = tab.tabla.rowViewportPosition(1) + 5
    tab._menu_contextual(QPoint(10, y))
    assert tab.tabla.currentRow() == 1 and len(abiertos) == 1 and "Duplicar cotización" in acciones(abiertos[0][0])
    tab._menu_contextual(QPoint(10, 5000))                          # fuera de las filas: no abre nada
    assert len(abiertos) == 1
    assert tab.tabla.contextMenuPolicy().name == "CustomContextMenu"


def test_menu_cambiar_estado(tab, conn):
    sub = acciones(tab.construir_menu())["Cambiar estado a"].menu()
    sub.actions()[0].trigger()                                      # «Enviada» sin ítems... el de conftest tiene un ítem
    assert conn.execute("SELECT estado FROM cotizaciones WHERE id = 1").fetchone()["estado"] == "enviada"
    assert tab.tabla.item(0, ui_main.COT_ESTADO).text() == "enviada"


def test_menu_cambiar_estado_con_error_avisa(tab, conn, monkeypatch):
    avisos = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: avisos.append(a[2])))
    db.guardar_cotizacion(1, [], [], conn)                          # sin líneas: no se puede enviar
    sub = acciones(tab.construir_menu())["Cambiar estado a"].menu()
    sub.actions()[0].trigger()
    assert avisos and "al menos una línea" in avisos[0]


def test_menu_duplicar(tab, conn):
    disparar(tab.construir_menu(), "Duplicar cotización")
    assert tab.tabla.rowCount() == 2
    assert tab.tabla.item(tab.tabla.currentRow(), 0).text() == "COT-2026-0002"        # la copia queda seleccionada
    assert tab.tabla.item(tab.tabla.currentRow(), ui_main.COT_ESTADO).text() == "borrador"


def test_menu_eliminar_con_confirmacion(tab, conn, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.No))
    disparar(tab.construir_menu(), "Eliminar cotización…")
    assert tab.tabla.rowCount() == 1                                # cancelar no elimina
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.Yes))
    disparar(tab.construir_menu(), "Eliminar cotización…")
    assert tab.tabla.rowCount() == 0 and conn.execute("SELECT COUNT(*) AS n FROM cotizaciones").fetchone()["n"] == 0


def test_menu_eliminar_con_factura_avisa(tab, conn, monkeypatch):
    preparar_aprobada(conn)
    db.generar_factura(1, conn)
    tab.refrescar()
    tab.tabla.setCurrentCell(0, 0)
    avisos = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: avisos.append(a[2])))
    disparar(tab.construir_menu(), "Eliminar cotización…")
    assert avisos and "FAC-2026-0001" in avisos[0] and tab.tabla.rowCount() == 1


def test_menu_generar_factura(tab, conn, monkeypatch):
    preparar_aprobada(conn)
    tab.refrescar()
    tab.tabla.setCurrentCell(0, 0)
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: None))
    monkeypatch.setattr(ui_main.CotizacionesTab, "_pedir_factura",
                        staticmethod(lambda p, n, r: {"monto": r["saldo"], "concepto": None}))
    disparar(tab.construir_menu(), "Generar factura")
    assert conn.execute("SELECT numero FROM facturas").fetchone()["numero"] == "FAC-2026-0001"


def test_menu_abre_editor_vista_previa_y_exporta(tab, monkeypatch):
    llamadas = []
    for nombre in ("editar_items", "vista_previa", "exportar_pdf", "exportar_word"):
        monkeypatch.setattr(tab, nombre, lambda n=nombre: llamadas.append(n))
    m = tab.construir_menu()
    for texto in ("Abrir / Editar", "Vista previa", "Exportar PDF", "Exportar Word"):
        disparar(m, texto)
    assert llamadas == ["editar_items", "vista_previa", "exportar_pdf", "exportar_word"]


# ----------------------------------------------------------------- facturas
def test_menu_de_facturas(conn, qapp, monkeypatch):
    preparar_aprobada(conn)
    db.generar_factura(1, conn)
    ventana = ui_main.MainWindow()
    f = ventana.facturas_tab
    f._ventana = ventana
    f.refrescar()
    f.tabla.setCurrentCell(0, 0)
    a = acciones(f.construir_menu())
    assert list(a) == ["Vista previa", "Marcar como pagada…", "Marcar como vencida", "Editar notas", "Exportar PDF",
                       "Exportar Word", "Eliminar factura…"]
    assert a["Marcar como pagada…"].isEnabled() and a["Marcar como vencida"].isEnabled()
    a["Marcar como vencida"].trigger()
    assert f.tabla.item(0, ui_main.FAC_ESTADO).text() == "vencida"
    a2 = acciones(f.construir_menu())
    assert a2["Marcar como pagada…"].isEnabled() and not a2["Marcar como vencida"].isEnabled()
    db.marcar_factura_pagada(1, "2026-02-01", conn)
    f.refrescar()
    f.tabla.setCurrentCell(0, 0)
    a3 = acciones(f.construir_menu())
    assert not a3["Marcar como pagada…"].isEnabled() and not a3["Marcar como vencida"].isEnabled()
