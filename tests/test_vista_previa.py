from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from app import db, pdf, ui_items, ui_main, ui_vista_previa
from app.calculo import Linea
from app.ui_vista_previa import VistaPreviaDialog, ZOOMS


@pytest.fixture
def abierta(monkeypatch):
    """Evita que los diálogos modales (exec) bloqueen las pruebas y guarda los que se abren."""
    abiertas = []
    monkeypatch.setattr(VistaPreviaDialog, "exec", lambda self: abiertas.append(self) or 0)
    return abiertas


def test_muestra_las_paginas_del_pdf(conn, qapp):
    db.guardar_notas(1, "\n".join(f"• Condición {i}" for i in range(120)), conn)
    d = VistaPreviaDialog(lambda ruta: pdf.exportar_cotizacion(1, ruta))
    assert d.error is None and d.doc.pageCount() >= 2 and len(d.paginas) == d.doc.pageCount()
    assert d.lbl_pagina.text() == f"Página 1 de {len(d.paginas)}"
    pm = d.paginas[0].pixmap()
    assert not pm.isNull() and d.paginas[0].width() == round(612 * 96 / 72)      # carta a 100 %
    d.done(0)


def test_zoom_y_ajustar_al_ancho(conn, qapp):
    d = VistaPreviaDialog(lambda ruta: pdf.exportar_cotizacion(1, ruta))
    d.show()
    ancho = d.paginas[0].width()
    d.btn_mas.click()
    assert d.zoom == 125 and d.paginas[0].width() > ancho and d.lbl_zoom.text() == "125 %"
    d.btn_menos.click()
    d.btn_menos.click()
    assert d.zoom == 80 and d.paginas[0].width() < ancho
    for _ in range(10):
        d.btn_menos.click()
    assert d.zoom == ZOOMS[0] and not d.btn_menos.isEnabled()
    for _ in range(10):
        d.btn_mas.click()
    assert d.zoom == ZOOMS[-1] and not d.btn_mas.isEnabled()
    d.ajustar_al_ancho()
    assert ZOOMS[0] <= d.zoom <= ZOOMS[-1]
    d.done(0)


def test_indicador_de_pagina_sigue_el_desplazamiento(conn, qapp):
    db.guardar_notas(1, "\n".join(f"• Condición {i}" for i in range(120)), conn)
    d = VistaPreviaDialog(lambda ruta: pdf.exportar_cotizacion(1, ruta))
    d.show()
    qapp.processEvents()
    assert d.lbl_pagina.text().startswith("Página 1 de")
    d.scroll.verticalScrollBar().setValue(d.scroll.verticalScrollBar().maximum())
    assert d.lbl_pagina.text() == f"Página {len(d.paginas)} de {len(d.paginas)}"
    d.done(0)


def test_error_al_generar_se_muestra_sin_romper(conn, qapp):
    def falla(ruta):
        raise ValueError("La cotización no existe.")
    d = VistaPreviaDialog(falla)
    assert d.error == "La cotización no existe." and d.paginas == [] and not d.btn_mas.isEnabled()
    d.done(0)


def test_botones_de_exportar_llaman_a_sus_acciones(conn, qapp):
    llamadas = []
    d = VistaPreviaDialog(lambda ruta: pdf.exportar_cotizacion(1, ruta), al_exportar_pdf=lambda: llamadas.append("pdf"),
                          al_exportar_word=lambda: llamadas.append("word"))
    d.btn_pdf.click()
    d.btn_word.click()
    assert llamadas == ["pdf", "word"]
    sin = VistaPreviaDialog(lambda ruta: pdf.exportar_cotizacion(1, ruta))
    assert sin.btn_pdf.isHidden() and sin.btn_word.isHidden()
    d.done(0)
    sin.done(0)


def test_no_queda_ningun_archivo_temporal_abierto(conn, qapp):
    """El PDF se lee a memoria y la carpeta temporal se borra al generarlo (en Windows un archivo abierto no se borra)."""
    rutas = []

    def generar(ruta):
        rutas.append(Path(ruta))
        pdf.exportar_cotizacion(1, ruta)

    d = VistaPreviaDialog(generar)
    assert d.error is None and d.doc.pageCount() >= 1
    assert not rutas[0].exists() and not rutas[0].parent.exists()      # ya se borró, con el diálogo aún abierto
    d.done(0)


def test_vista_previa_muestra_lo_mismo_que_el_pdf_exportado(conn, qapp, tmp_path):
    db.guardar_cotizacion(1, [Linea("item", 0, "Servicio especial", 3, 250.0, True, "m²")], [], conn)
    d = VistaPreviaDialog(lambda ruta: pdf.exportar_cotizacion(1, ruta))
    pdf.exportar_cotizacion(1, str(tmp_path / "x.pdf"))
    assert d.pdf_bytes[:5] == b"%PDF-" and abs(len(d.pdf_bytes) - (tmp_path / "x.pdf").stat().st_size) < 200
    d.done(0)


# ----------------------------------------------------------------- integración en la interfaz
def test_boton_en_cotizaciones_y_facturas(conn, qapp, abierta):
    w = ui_main.MainWindow()
    c = w.cotizaciones_tab
    c.refrescar()
    assert not c.btn_vista.isEnabled() or c.tabla.currentRow() >= 0
    c.tabla.setCurrentCell(0, 0)
    assert c.btn_vista.isEnabled()
    c.vista_previa()
    assert len(abierta) == 1 and abierta[0].windowTitle() == "Vista previa — COT-2026-0001" and abierta[0].error is None
    abierta[0].done(0)
    db.cambiar_estado_cotizacion(1, "enviada", conn)
    db.cambiar_estado_cotizacion(1, "aprobada", conn)
    db.generar_factura(1, conn)
    f = w.facturas_tab
    f.refrescar()
    f.tabla.setCurrentCell(0, 0)
    f.vista_previa()
    assert len(abierta) == 2 and abierta[1].windowTitle() == "Vista previa — FAC-2026-0001" and abierta[1].error is None
    abierta[1].done(0)


def test_vista_previa_sin_seleccion_avisa(conn, qapp, abierta, monkeypatch):
    avisos = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: avisos.append(a[2])))
    w = ui_main.MainWindow()
    w.facturas_tab.vista_previa()
    assert avisos and not abierta


def test_editor_guarda_antes_de_mostrar_la_vista_previa(conn, qapp, abierta):
    d = ui_items.ItemsDialog(1, "COT-2026-0001", editable=True)
    d.lineas[:] = [Linea("item", 0, "Concepto nuevo en pantalla", 2, 40.0, True, "uni")]
    d._render_lineas(0)
    d.notas_edit.setPlainText("Nota de la vista previa")
    d.btn_vista.click()
    assert [l.descripcion for l in db.obtener_lineas(1, conn)] == ["Concepto nuevo en pantalla"]     # ya guardado
    assert db.obtener_notas(1, conn) == "Nota de la vista previa"
    assert len(abierta) == 1 and abierta[0].error is None and d.isVisible() is False and d.result() == 0   # el editor sigue abierto
    abierta[0].done(0)


def test_editor_con_datos_invalidos_no_abre_la_vista_previa(conn, qapp, abierta, monkeypatch):
    avisos = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: avisos.append(a[2])))
    d = ui_items.ItemsDialog(1, "COT-2026-0001", editable=True)
    d.lineas[:] = [Linea("item", 0, "", 1, 50.0)]          # falta la descripción
    d._render_lineas(0)
    d.btn_vista.click()
    assert avisos and not abierta


def test_editor_de_solo_lectura_muestra_la_vista_previa_sin_guardar(conn, qapp, abierta):
    d = ui_items.ItemsDialog(1, "COT-2026-0001", editable=False)
    assert d.btn_vista.text() == "Vista previa"
    d.btn_vista.click()
    assert len(abierta) == 1
    abierta[0].done(0)


def test_ayudante_vista_previa_con_botones_de_exportar(conn, qapp, abierta, monkeypatch):
    exportados = []
    monkeypatch.setattr("app.ui_comun.exportar_pdf", lambda *a, **k: exportados.append(("pdf", a[2], a[3])))
    monkeypatch.setattr("app.ui_comun.exportar_word", lambda *a, **k: exportados.append(("word", a[2], a[3])))
    ui_vista_previa.vista_previa(None, "cotizacion", 1, "COT-2026-0001")
    dlg = abierta[0]
    dlg.btn_pdf.click()
    dlg.btn_word.click()
    assert exportados == [("pdf", 1, "COT-2026-0001"), ("word", 1, "COT-2026-0001")]
    dlg.done(0)
