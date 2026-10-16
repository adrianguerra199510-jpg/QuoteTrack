import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from app import db, ui_items
from app.calculo import Cargo, Linea
from app.ui_items import COL_CANT, COL_COD, COL_DESC, COL_IMPORTE, COL_ITBMS, COL_PRECIO, CARGO_ITBMS, CARGO_VALOR

NUM = "COT-2026-0001"


@pytest.fixture
def dlg(conn, qapp):
    db.guardar_cotizacion(1, [], [], conn)
    d = ui_items.ItemsDialog(1, NUM, editable=True)
    d.lineas.clear()
    d._render_lineas()
    return d


def escribir(d, fila, col, texto):
    d.tabla.item(fila, col).setText(texto)


def armar_obra(d):
    """01 Albañilería (01.1 muro 6: 10×20, 01.2 muro 4: 5×10) y 02 Limpieza independiente (1×100)."""
    d.agregar_grupo()
    escribir(d, 0, COL_DESC, "Albañilería")
    d.tabla.setCurrentCell(0, COL_DESC)
    d.agregar_subitem()
    escribir(d, 1, COL_DESC, "Muro de bloque de 6")
    escribir(d, 1, COL_CANT, "10")
    escribir(d, 1, COL_PRECIO, "20")
    d.tabla.setCurrentCell(0, COL_DESC)
    d.agregar_subitem()
    escribir(d, 2, COL_DESC, "Muro de bloque de 4")
    escribir(d, 2, COL_CANT, "5")
    escribir(d, 2, COL_PRECIO, "10")
    d.agregar_item()
    escribir(d, 3, COL_DESC, "Limpieza final")
    escribir(d, 3, COL_PRECIO, "100")


def test_grupos_y_subitems_con_codigos_e_importes(dlg):
    armar_obra(dlg)
    assert [dlg.tabla.item(i, COL_COD).text() for i in range(4)] == ["01", "01.1", "01.2", "02"]
    assert [dlg.tabla.item(i, COL_IMPORTE).text() for i in range(4)] == \
        ["B/. 250.00", "B/. 200.00", "B/. 50.00", "B/. 100.00"]
    assert [l.nivel for l in dlg.lineas] == [0, 1, 1, 0]


def test_subitem_sin_grupo_seleccionado_avisa(dlg, monkeypatch):
    avisos = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: avisos.append(a[2])))
    dlg.agregar_item()                         # ítem independiente, no es un grupo
    dlg.tabla.setCurrentCell(0, COL_DESC)
    dlg.agregar_subitem()
    assert avisos and len(dlg.lineas) == 1


def test_subitem_se_agrega_al_final_de_su_grupo(dlg):
    armar_obra(dlg)
    dlg.tabla.setCurrentCell(1, COL_DESC)       # un sub-ítem del grupo 01 también sirve
    dlg.agregar_subitem()
    assert [l.nivel for l in dlg.lineas] == [0, 1, 1, 1, 0]
    assert dlg.lineas[4].descripcion == "Limpieza final"


def test_itbms_individual_por_linea(dlg):
    armar_obra(dlg)
    sin = dlg.lbl_totales.text()
    assert "ITBMS (7%) sobre B/. 350.00: B/. 24.50" in sin
    dlg.tabla.item(2, COL_ITBMS).setCheckState(Qt.Unchecked)   # el muro de 4" queda exento
    assert dlg.lineas[2].aplica_itbms is False and dlg.lineas[1].aplica_itbms is True
    assert "ITBMS (7%) sobre B/. 300.00: B/. 21.00" in dlg.lbl_totales.text()
    assert dlg.tabla.item(0, COL_ITBMS).checkState() == Qt.PartiallyChecked   # el grupo queda mixto


def test_itbms_del_grupo_afecta_a_todos_sus_subitems(dlg):
    armar_obra(dlg)
    dlg.tabla.item(0, COL_ITBMS).setCheckState(Qt.Unchecked)
    assert [l.aplica_itbms for l in dlg.lineas[1:3]] == [False, False]
    assert dlg.lineas[3].aplica_itbms is True                  # el ítem independiente no cambia
    assert "sobre B/. 100.00: B/. 7.00" in dlg.lbl_totales.text()


def test_menu_itbms_todos_o_ninguno(dlg):
    armar_obra(dlg)
    dlg._itbms_todos(False)
    assert "ITBMS (7%) sobre B/. 0.00: B/. 0.00" in dlg.lbl_totales.text()
    dlg._itbms_todos(True)
    assert "sobre B/. 350.00" in dlg.lbl_totales.text()


def test_costos_adicionales(dlg):
    armar_obra(dlg)
    dlg.agregar_cargo("Administración")
    dlg.tabla_cargos.item(0, CARGO_VALOR).setText("10")
    dlg.agregar_cargo("Utilidad")
    dlg.tabla_cargos.item(1, CARGO_VALOR).setText("5")
    dlg.tabla_cargos.item(1, CARGO_ITBMS).setCheckState(Qt.Unchecked)
    t = dlg.lbl_totales.text()
    assert "Administración (10%): B/. 35.00" in t and "Utilidad (5%): B/. 17.50" in t
    assert "sobre B/. 385.00" in t                              # 350 + 35 (la utilidad no lleva ITBMS)
    combo = dlg.tabla_cargos.cellWidget(1, 1)
    combo.setCurrentIndex(1)                                   # Utilidad pasa a monto fijo de 5.00
    assert "Utilidad: B/. 5.00" in dlg.lbl_totales.text()
    dlg.tabla_cargos.setCurrentCell(0, 0)
    dlg.quitar_cargo()
    assert [c.concepto for c in dlg.cargos] == ["Utilidad"]


def test_mover_grupos_y_subitems(dlg):
    armar_obra(dlg)
    dlg.agregar_grupo()
    escribir(dlg, 4, COL_DESC, "Pintura")
    dlg.tabla.setCurrentCell(1, COL_DESC)
    dlg.mover(1)                                              # sub-ítem baja dentro de su grupo
    assert [l.descripcion for l in dlg.lineas[:3]] == ["Albañilería", "Muro de bloque de 4", "Muro de bloque de 6"]
    dlg.mover(1)                                              # ya es el último de su grupo: no sale
    assert dlg.lineas[2].descripcion == "Muro de bloque de 6"
    dlg.tabla.setCurrentCell(0, COL_DESC)
    dlg.mover(1)                                              # el grupo se lleva a sus hijos
    assert [l.descripcion for l in dlg.lineas] == [
        "Limpieza final", "Albañilería", "Muro de bloque de 4", "Muro de bloque de 6", "Pintura"]
    assert dlg.tabla.currentRow() == 1
    dlg.mover(-1)
    assert dlg.lineas[0].descripcion == "Albañilería"


def test_quitar_grupo_con_hijos_pide_confirmacion(dlg, monkeypatch):
    armar_obra(dlg)
    dlg.tabla.setCurrentCell(0, COL_DESC)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.No))
    dlg.quitar()
    assert len(dlg.lineas) == 4
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.Yes))
    dlg.quitar()
    assert [l.descripcion for l in dlg.lineas] == ["Limpieza final"]


def test_guardar_persiste_todo(dlg, conn):
    armar_obra(dlg)
    dlg.tabla.item(2, COL_ITBMS).setCheckState(Qt.Unchecked)
    dlg.agregar_cargo("Administración")
    dlg.tabla_cargos.item(0, CARGO_VALOR).setText("10")
    dlg.proyecto_edit.setText("Casa Modelo")
    dlg.notas_edit.setPlainText("Nota")
    dlg.guardar()
    lineas = db.obtener_lineas(1, conn)
    assert [(l.tipo, l.nivel, l.descripcion, l.aplica_itbms) for l in lineas] == [
        ("grupo", 0, "Albañilería", True), ("item", 1, "Muro de bloque de 6", True),
        ("item", 1, "Muro de bloque de 4", False), ("item", 0, "Limpieza final", True)]
    assert db.obtener_cargos(1, conn) == [Cargo("Administración", "porcentaje", 10.0, True)]
    t = db.totales_cotizacion(1, conn)
    assert (t.subtotal, t.cargos_total, t.itbms, t.total) == (350.0, 35.0, 23.45, 408.45)
    assert db.obtener_proyecto(1, conn) == "Casa Modelo" and db.obtener_notas(1, conn) == "Nota"
    reabierto = ui_items.ItemsDialog(1, NUM, editable=True)
    assert [l.descripcion for l in reabierto.lineas] == [l.descripcion for l in lineas]
    assert "sobre B/. 335.00" in reabierto.lbl_totales.text()   # 300 gravados + 35 de administración


def test_numero_invalido_bloquea_el_guardado(dlg, conn, monkeypatch):
    armar_obra(dlg)
    avisos = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: avisos.append(a[2])))
    escribir(dlg, 1, COL_PRECIO, "abc")
    dlg.guardar()
    assert avisos and "01.1" in avisos[0]
    assert db.obtener_lineas(1, conn) == []
    escribir(dlg, 1, COL_PRECIO, "20")                        # corregido: ya guarda
    dlg.guardar()
    assert len(db.obtener_lineas(1, conn)) == 4


def test_item_sin_descripcion_y_filas_vacias(dlg, conn, monkeypatch):
    dlg.agregar_item()
    dlg.agregar_grupo()
    dlg.guardar()                                             # todo vacío: se descartan sin error
    assert db.obtener_lineas(1, conn) == []
    dlg2 = ui_items.ItemsDialog(1, NUM, editable=True)
    dlg2.lineas[:] = [Linea("item", 0, "", 1, 50.0)]
    dlg2._render_lineas()
    avisos = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: avisos.append(a[2])))
    dlg2.guardar()
    assert avisos and "descripción" in avisos[0]


def test_descripcion_multilinea_y_formato_de_precio(dlg, conn):
    dlg.agregar_item()
    escribir(dlg, 0, COL_DESC, "Línea uno\nLínea dos")
    escribir(dlg, 0, COL_PRECIO, "23,551.60")
    assert dlg.tabla.item(0, COL_PRECIO).text() == "23,551.60"
    assert dlg.tabla.item(0, COL_IMPORTE).text() == "B/. 23,551.60"
    dlg.guardar()
    assert db.obtener_lineas(1, conn)[0].descripcion == "Línea uno\nLínea dos"


def test_empresa_exenta_oculta_las_columnas_de_itbms(conn, qapp):
    exenta = db.guardar_empresa({"nombre": "Exenta", "itbms_tasa": 0}, conn)
    db.cambiar_empresa_cotizacion(1, exenta, conn)
    d = ui_items.ItemsDialog(1, NUM, editable=True)
    assert d.tabla.isColumnHidden(COL_ITBMS) and d.tabla_cargos.isColumnHidden(CARGO_ITBMS)
    assert "ITBMS (exento)" in d.lbl_totales.text()
    d.empresa_combo.setCurrentIndex(d.empresa_combo.findData(db.listar_empresas(conn)[0]["id"]))  # vuelve a una con 7%
    assert not d.tabla.isColumnHidden(COL_ITBMS) and "ITBMS (7%)" in d.lbl_totales.text()


def test_cambiar_empresa_desde_el_editor(conn, qapp):
    b = db.guardar_empresa({"nombre": "Empresa B", "itbms_tasa": 0}, conn)
    d = ui_items.ItemsDialog(1, NUM, editable=True)
    d.empresa_combo.setCurrentIndex(d.empresa_combo.findData(b))
    d.guardar()
    assert db.empresa_de_cotizacion(1, conn)["nombre"] == "Empresa B"
    assert db.totales_cotizacion(1, conn).itbms == 0


def test_solo_lectura_no_modifica(conn, qapp):
    db.guardar_cotizacion(1, [Linea("grupo", 0, "G"), Linea("item", 1, "x", 1, 10.0)], [Cargo("Admin", "monto", 5)], conn)
    d = ui_items.ItemsDialog(1, NUM, editable=False)
    d.tabla.item(1, COL_ITBMS).setCheckState(Qt.Unchecked)      # intento de cambio: se revierte
    assert d.lineas[1].aplica_itbms is True
    assert not d.btn_grupo.isEnabled() and not d.btn_cargo.isEnabled() and d.notas_edit.isReadOnly()
    assert not d.empresa_combo.isEnabled()
