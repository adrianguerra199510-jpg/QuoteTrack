import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from app import calculo, db, ui_apu, ui_biblioteca, ui_items, ui_main
from app.calculo import Apu, Concepto, ConfigApu, Indirecto, Insumo, Linea, OBRA, SERVICIO
from app.ui_items import COL_CANT, COL_DESC, COL_PRECIO, COL_TIPO, COL_UD, COL_IMPORTE

NUM = "COT-2026-0001"


def cfg0():
    return ConfigApu(0, 0, 0, 0)


@pytest.fixture
def dlg(conn, qapp):
    db.guardar_cotizacion(1, [], [], conn)
    d = ui_items.ItemsDialog(1, NUM, editable=True)
    d.lineas.clear()
    d._render_lineas()
    return d


def combo_tipo(d, fila):
    return d.tabla.cellWidget(fila, COL_TIPO).combo


def poner_obra(d, fila):
    combo = combo_tipo(d, fila)
    combo.setCurrentIndex(combo.findData(OBRA))


# ----------------------------------------------------------------- editor de APU
def test_editor_agrega_edita_y_calcula(qapp):
    apu = Apu()
    ed = ui_apu.ApuEditor(apu, cfg0())
    ed.agregar("mano_obra")
    ed.tablas["mano_obra"].item(0, ui_apu.DESC).setText("Calificado")
    ed.tablas["mano_obra"].item(0, ui_apu.REND).setText("26")
    ed.tablas["mano_obra"].item(0, ui_apu.COEF).setText("5")
    ed.tablas["mano_obra"].item(0, ui_apu.PRECIO).setText("89.87")
    assert apu.insumos[0] == Insumo("mano_obra", "Calificado", "", 26.0, 5.0, 89.87)
    assert ed.tablas["mano_obra"].item(0, ui_apu.COSTE).text() == "11,683.10"       # 26 × 5 × 89.87
    assert "B/. 11,683.10" in ed.tabs.tabText(1)
    assert ed.precio_venta == 11683.10 and "11,683.10" in ed.resumen.text()
    ed.quitar("mano_obra")
    assert apu.insumos == [] and ed.precio_venta == 0


def test_editor_fila_porcentaje_de_otra_categoria(qapp):
    apu = Apu(1.0, [Insumo("mano_obra", "Oficial", "día", 10, 1, 100.0)])
    ed = ui_apu.ApuEditor(apu, cfg0())
    ed.agregar("auxiliar", ref="mano_obra")
    herramienta = apu.insumos[1]
    assert herramienta.descripcion == "Herramienta menor" and herramienta.coeficiente == 0.05
    t = ed.tablas["auxiliar"]
    assert not (t.item(0, ui_apu.PRECIO).flags() & Qt.ItemIsEditable)               # precio calculado
    assert t.item(0, ui_apu.PRECIO).text() == "1,000.00" and t.item(0, ui_apu.COSTE).text() == "50.00"
    ed.tablas["mano_obra"].item(0, ui_apu.PRECIO).setText("200")                    # sube la mano de obra
    assert t.item(0, ui_apu.COSTE).text() == "100.00"
    assert ed.precio_venta == 2000 + 100


def test_editor_base_distinta_de_uno_y_coeficientes(qapp):
    apu = Apu(1.0, [Insumo("material", "Cemento", "saco", 8, 1, 10.0)])
    ed = ui_apu.ApuEditor(apu, ConfigApu(0.15, 0, 0, 0))
    assert ed.precio_venta == 92.0                                                   # 80 × 1.15
    ed.base_spin.setValue(2.0)
    assert apu.base == 2.0 and ed.precio_venta == 46.0


def test_editor_numero_invalido_se_reporta(qapp):
    apu = Apu()
    ed = ui_apu.ApuEditor(apu, cfg0())
    ed.agregar("material")
    ed.tablas["material"].item(0, ui_apu.DESC).setText("Bloque")
    ed.tablas["material"].item(0, ui_apu.PRECIO).setText("abc")
    assert "material" in ed.validar().lower() or "Materiales" in ed.validar()
    ed.tablas["material"].item(0, ui_apu.PRECIO).setText("2.5")
    assert ed.validar() is None and apu.insumos[0].precio == 2.5


def test_editor_solo_lectura(qapp):
    apu = Apu(1.0, [Insumo("material", "Cemento", "saco", 8, 1, 10.0)])
    ed = ui_apu.ApuEditor(apu, cfg0(), editable=False)
    ed.tablas["material"].item(0, ui_apu.PRECIO).setText("999")
    assert apu.insumos[0].precio == 10.0 and not ed.base_spin.isEnabled()


def test_dialogo_apu_acepta_y_limpia_filas_vacias(qapp, monkeypatch):
    original = Apu(1.0, [Insumo("material", "Cemento", "saco", 8, 1, 10.0)])
    d = ui_apu.ApuDialog("Muro", "m²", original, cfg0())
    d.editor.agregar("mano_obra")                       # fila en blanco: debe descartarse
    d._aceptar()
    assert d.result() == 1 and len(d.apu.insumos) == 1 and len(original.insumos) == 1   # trabaja sobre una copia


def test_dialogo_ajustes_coeficientes_e_indirectos(qapp):
    d = ui_apu.AjustesApuDialog(ConfigApu(0.15, 0.15, 0.15, 0.15), costo_directo=1000.0)
    d.spins["material"].setValue(20)
    d.agregar()
    d.tabla.item(0, d.I_CONCEPTO).setText("Alquiler de patio")
    d.tabla.item(0, d.I_CANT).setText("1")
    d.tabla.item(0, d.I_PERIODO).setText("2")
    d.tabla.item(0, d.I_COSTO).setText("500")
    assert d.tabla.item(0, d.I_SUBTOTAL).text() == "B/. 1,000.00"
    assert d.coef_indirectos == pytest.approx(1.0) and "100.00%" in d.resumen.text()
    d.agregar()                                          # fila vacía: se descarta al aceptar
    d._aceptar()
    assert d.cfg.coef_material == pytest.approx(0.20)
    assert d.cfg.indirectos == [Indirecto("Alquiler de patio", 1, 2, 500.0)]


# ----------------------------------------------------------------- editor de la cotización
def test_tipo_de_item_servicio_u_obra(dlg):
    dlg.agregar_item()
    escribir = lambda f, c, t: dlg.tabla.item(f, c).setText(t)
    escribir(0, COL_DESC, "Muro")
    escribir(0, COL_UD, "m²")
    escribir(0, COL_CANT, "10")
    escribir(0, COL_PRECIO, "50")
    assert dlg.lineas[0].modalidad == SERVICIO and dlg.lineas[0].unidad == "m²"
    assert dlg.tabla.item(0, COL_IMPORTE).text() == "B/. 500.00"
    poner_obra(dlg, 0)                                   # pasa a mano de obra y material: precio sale del APU
    l = dlg.lineas[0]
    assert l.modalidad == OBRA and l.apu is not None and l.precio == 0
    assert not (dlg.tabla.item(0, COL_PRECIO).flags() & Qt.ItemIsEditable)
    assert dlg.tabla.item(0, COL_IMPORTE).text() == "B/. 0.00"


def test_abrir_apu_actualiza_precio_importe_y_totales(dlg, monkeypatch):
    dlg.agregar_item()
    dlg.tabla.item(0, COL_DESC).setText("Muro")
    dlg.tabla.item(0, COL_CANT).setText("10")
    poner_obra(dlg, 0)
    dlg.cfg = cfg0()

    class FalsoApu:
        def __init__(self, desc, ud, apu, cfg, coef_ind, editable, parent):
            self.apu = apu.copia()
            self.apu.insumos.append(Insumo("mano_obra", "Oficial", "día", 1, 1, 80.0))

        def exec(self):
            return 1

    monkeypatch.setattr(ui_items, "ApuDialog", FalsoApu)
    dlg.tabla.setCurrentCell(0, COL_DESC)
    dlg.abrir_apu()
    assert dlg.lineas[0].precio == 80.0
    assert dlg.tabla.item(0, COL_PRECIO).text() == "80.00" and dlg.tabla.item(0, COL_IMPORTE).text() == "B/. 800.00"
    assert "Subtotal ítems: <b>B/. 800.00</b>" in dlg.lbl_totales.text()


def test_abrir_apu_en_un_servicio_avisa(dlg, monkeypatch):
    avisos = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: avisos.append(a[2])))
    dlg.agregar_item()
    dlg.tabla.setCurrentCell(0, COL_DESC)
    dlg.abrir_apu()
    assert avisos and "servicio profesional" in avisos[0]


def test_volver_a_servicio_pide_confirmacion_si_hay_analisis(dlg, monkeypatch):
    dlg.agregar_item()
    poner_obra(dlg, 0)
    dlg.lineas[0].apu.insumos.append(Insumo("material", "Cemento", "saco", 8, 1, 10.0))
    dlg.cfg = cfg0()
    dlg._render_lineas(0)
    assert dlg.lineas[0].precio == 80.0
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.No))
    combo_tipo(dlg, 0).setCurrentIndex(combo_tipo(dlg, 0).findData(SERVICIO))
    assert dlg.lineas[0].modalidad == OBRA and combo_tipo(dlg, 0).currentData() == OBRA
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.Yes))
    combo_tipo(dlg, 0).setCurrentIndex(combo_tipo(dlg, 0).findData(SERVICIO))
    assert dlg.lineas[0].modalidad == SERVICIO and dlg.lineas[0].apu is None and dlg.lineas[0].precio == 80.0


def test_coeficientes_e_indirectos_recalculan_los_precios(dlg, monkeypatch):
    dlg.agregar_item()
    poner_obra(dlg, 0)
    dlg.lineas[0].apu.insumos.append(Insumo("mano_obra", "Oficial", "día", 1, 1, 100.0))
    dlg.cfg = cfg0()
    dlg._render_lineas(0)
    assert dlg.lineas[0].precio == 100.0

    class FalsoAjustes:
        def __init__(self, cfg, costo, editable, parent):
            assert costo == 100.0                          # costo directo informado al diálogo
            self.cfg = ConfigApu(0, 0.10, 0, 0, [Indirecto("Patio", 1, 1, 20.0)])

        def exec(self):
            return 1

    monkeypatch.setattr(ui_items, "AjustesApuDialog", FalsoAjustes)
    dlg.ajustes_apu()
    assert dlg.coef_ind == pytest.approx(0.2)
    assert dlg.lineas[0].precio == 130.0                   # 100 × (1 + 10 % + 20 % de indirectos)


def test_guardar_cotizacion_con_apu_y_reabrirla(dlg, conn):
    dlg.agregar_item()
    dlg.tabla.item(0, COL_DESC).setText("Muro")
    dlg.tabla.item(0, COL_CANT).setText("2")
    poner_obra(dlg, 0)
    dlg.lineas[0].apu.insumos.append(Insumo("material", "Bloque", "uni", 10, 1, 2.0))
    dlg.cfg = ConfigApu(0.10, 0, 0, 0, [])
    dlg._render_lineas(0)
    dlg.guardar()
    t = db.totales_cotizacion(1, conn)
    assert t.subtotal == 44.0                              # (10 × 2 × 1.10) × 2
    reabierto = ui_items.ItemsDialog(1, NUM, editable=True)
    assert reabierto.lineas[0].modalidad == OBRA and reabierto.lineas[0].apu.insumos[0].descripcion == "Bloque"
    assert reabierto.lineas[0].precio == 22.0
    assert combo_tipo(reabierto, 0).currentData() == OBRA


# ----------------------------------------------------------------- biblioteca desde la cotización
def test_guardar_item_en_biblioteca_y_actualizar(dlg, conn, monkeypatch):
    infos = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: infos.append(a[2])))
    dlg.agregar_item()
    dlg.tabla.item(0, COL_DESC).setText("Muro de bloque de 6")
    dlg.tabla.item(0, COL_UD).setText("m²")
    poner_obra(dlg, 0)
    dlg.lineas[0].apu.insumos.append(Insumo("material", "Bloque", "uni", 12.5, 1, 1.2))
    dlg.tabla.setCurrentCell(0, COL_DESC)
    dlg.guardar_en_biblioteca()
    c = db.listar_conceptos(conn)[0]
    assert (c.descripcion, c.unidad, c.modalidad, c.categoria) == ("Muro de bloque de 6", "m²", OBRA, "")
    assert c.apu.insumos[0].descripcion == "Bloque" and infos and "1 concepto" in infos[0]
    # existe ya: si se rechaza, no cambia; si se acepta, se actualiza
    dlg.lineas[0].apu.insumos[0].precio = 5.0
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.No))
    dlg.guardar_en_biblioteca()
    assert db.listar_conceptos(conn)[0].apu.insumos[0].precio == 1.2
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.Yes))
    dlg.guardar_en_biblioteca()
    assert len(db.listar_conceptos(conn)) == 1 and db.listar_conceptos(conn)[0].apu.insumos[0].precio == 5.0


def test_guardar_grupo_en_biblioteca_usa_el_grupo_como_categoria(dlg, conn, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: None))
    dlg.agregar_grupo()
    dlg.tabla.item(0, COL_DESC).setText("Albañilería")
    dlg.tabla.setCurrentCell(0, COL_DESC)
    for n, nombre in enumerate(("Muro de 6", "Muro de 4"), 1):
        dlg.agregar_subitem()
        dlg.tabla.item(n, COL_DESC).setText(nombre)
        dlg.tabla.item(n, COL_PRECIO).setText("10")
        dlg.tabla.setCurrentCell(0, COL_DESC)
    dlg.tabla.setCurrentCell(0, COL_DESC)
    dlg.guardar_en_biblioteca()
    guardados = db.listar_conceptos(conn)
    assert sorted(c.descripcion for c in guardados) == ["Muro de 4", "Muro de 6"]
    assert {c.categoria for c in guardados} == {"Albañilería"}
    assert all(c.modalidad == SERVICIO and c.precio == 10.0 for c in guardados)


def test_guardar_en_biblioteca_sin_seleccion_o_sin_descripcion(dlg, monkeypatch):
    avisos = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: avisos.append(a[2])))
    dlg.guardar_en_biblioteca()
    dlg.agregar_item()
    dlg.tabla.setCurrentCell(0, COL_DESC)
    dlg.guardar_en_biblioteca()
    assert len(avisos) == 2 and "descripción" in avisos[1]


class FalsoSelector:
    conceptos = []

    def __init__(self, parent=None):
        pass

    def exec(self):
        return 1

    def seleccion(self):
        return self.conceptos


def test_insertar_desde_biblioteca_al_final_o_en_el_grupo(dlg, conn, monkeypatch):
    apu = Apu(1.0, [Insumo("material", "Bloque", "uni", 10, 1, 2.0)])
    muro = db.obtener_concepto(db.guardar_concepto(Concepto(None, "Muro", "m²", OBRA, 0, "Albañilería", apu), conn), conn)
    plano = db.obtener_concepto(db.guardar_concepto(Concepto(None, "Plano", "uni", SERVICIO, 300.0), conn), conn)
    FalsoSelector.conceptos = [muro, plano]
    monkeypatch.setattr(ui_items, "SelectorConceptosDialog", FalsoSelector)
    dlg.cfg = cfg0()
    dlg.desde_biblioteca()                                   # sin grupo seleccionado: ítems independientes
    assert [(l.descripcion, l.nivel, l.modalidad) for l in dlg.lineas] == [("Muro", 0, OBRA), ("Plano", 0, SERVICIO)]
    assert dlg.lineas[0].precio == 20.0 and dlg.lineas[1].precio == 300.0
    dlg.agregar_grupo()
    dlg.tabla.item(2, COL_DESC).setText("Obra civil")
    dlg.tabla.setCurrentCell(2, COL_DESC)
    FalsoSelector.conceptos = [muro]
    dlg.desde_biblioteca()                                   # con grupo seleccionado: sub-ítem del grupo
    assert [l.nivel for l in dlg.lineas] == [0, 0, 0, 1]
    assert dlg.lineas[3].apu is not muro.apu                 # copia independiente


def test_insertar_con_seleccion_vacia_no_hace_nada(dlg, monkeypatch):
    FalsoSelector.conceptos = []
    monkeypatch.setattr(ui_items, "SelectorConceptosDialog", FalsoSelector)
    dlg.desde_biblioteca()
    assert dlg.lineas == []


def test_selector_busca_y_devuelve_los_seleccionados(conn, qapp):
    db.guardar_concepto(Concepto(None, "Muro de bloque", "m²", OBRA, 0, "Albañilería", Apu(1.0, [Insumo("material", "B", "u", 1, 1, 10.0)])), conn)
    db.guardar_concepto(Concepto(None, "Pintura interior", "m²", SERVICIO, 5.0, "Acabados"), conn)
    sel = ui_biblioteca.SelectorConceptosDialog()
    assert sel.tabla.rowCount() == 2 and sel.vacio.isHidden()
    sel.busqueda.setText("pintura")
    assert sel.tabla.rowCount() == 1
    sel.tabla.selectRow(0)
    assert [c.descripcion for c in sel.seleccion()] == ["Pintura interior"]
    sel.busqueda.setText("")
    sel.tabla.selectAll()
    assert len(sel.seleccion()) == 2


def test_selector_con_biblioteca_vacia_muestra_ayuda(conn, qapp):
    sel = ui_biblioteca.SelectorConceptosDialog()
    assert sel.tabla.rowCount() == 0 and not sel.vacio.isHidden()


# ----------------------------------------------------------------- pestaña Biblioteca
class FalsoConcepto:
    def __init__(self, concepto=None, parent=None):
        self._c = concepto or Concepto()

    def exec(self):
        return 1

    def concepto(self):
        c = self._c
        return Concepto(c.id, c.descripcion or "Nuevo desde diálogo", "uni", SERVICIO, 42.0, "Varios", None)


def test_biblioteca_tab_crud(conn, qapp, monkeypatch):
    tab = ui_biblioteca.BibliotecaTab()
    assert tab.tabla.rowCount() == 0 and not tab.btn_editar.isEnabled()
    monkeypatch.setattr(ui_biblioteca, "ConceptoDialog", FalsoConcepto)
    tab.nuevo()
    assert tab.tabla.rowCount() == 1 and tab.tabla.item(0, 1).text() == "Nuevo desde diálogo"
    tab.tabla.setCurrentCell(0, 1)
    assert tab.btn_editar.isEnabled() and tab.tabla.item(0, 4).text() == "B/. 42.00"
    tab.duplicar()
    assert tab.tabla.rowCount() == 2
    tab.busqueda.setText("copia")
    assert tab.tabla.rowCount() == 1
    tab.busqueda.setText("")
    tab.tipo.setCurrentIndex(tab.tipo.findData(OBRA))
    assert tab.tabla.rowCount() == 0
    tab.tipo.setCurrentIndex(0)
    tab.tabla.setCurrentCell(0, 1)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.Yes))
    tab.eliminar()
    assert tab.tabla.rowCount() == 1


def test_dialogo_de_concepto_servicio_y_obra(conn, qapp, monkeypatch):
    d = ui_biblioteca.ConceptoDialog()
    d.descripcion.setText("Muro")
    d.unidad.setText("m²")
    d.precio.setValue(15)
    d.modalidad.setCurrentIndex(d.modalidad.findData(SERVICIO))
    c = d.concepto()
    assert (c.modalidad, c.precio, c.apu) == (SERVICIO, 15.0, None) and d.pila.currentIndex() == 0
    d.modalidad.setCurrentIndex(d.modalidad.findData(OBRA))
    assert d.pila.currentIndex() == 1
    d.editor.agregar("material")
    d.editor.tablas["material"].item(0, ui_apu.DESC).setText("Bloque")
    d.editor.tablas["material"].item(0, ui_apu.PRECIO).setText("2")
    c = d.concepto()
    assert c.modalidad == OBRA and c.apu.insumos[0].descripcion == "Bloque"
    d._guardar()
    assert d.result() == 1
    # sin descripción no se acepta
    avisos = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: avisos.append(a[2])))
    d2 = ui_biblioteca.ConceptoDialog()
    d2._guardar()
    assert avisos and "descripción" in avisos[0]


def test_editar_concepto_existente_carga_su_analisis(conn, qapp):
    cid = db.guardar_concepto(Concepto(None, "Muro", "m²", OBRA, 0, "Alb", Apu(2.0, [Insumo("material", "B", "u", 1, 1, 10.0)])), conn)
    d = ui_biblioteca.ConceptoDialog(db.obtener_concepto(cid, conn))
    assert d.modalidad.currentData() == OBRA and d.pila.currentIndex() == 1
    assert d.editor.base_spin.value() == 2.0 and d.editor.tablas["material"].rowCount() == 1


# ----------------------------------------------------------------- configuración y ventana
def test_configuracion_guarda_los_coeficientes_por_defecto(conn, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: None))
    tab = ui_main.ConfiguracionTab()
    assert tab.spins_coef["material"].value() == 15
    tab.spins_coef["material"].setValue(22)
    tab.spins_coef["subcontrato"].setValue(8)
    tab.guardar_opciones()
    cfg = db.coef_apu_defecto(conn)
    assert cfg.coef_material == pytest.approx(0.22) and cfg.coef_subcontrato == pytest.approx(0.08)


def test_ventana_incluye_la_biblioteca(conn, qapp):
    w = ui_main.MainWindow()
    textos = [w.nav.item(i).text() for i in range(w.nav.count())]
    assert "Biblioteca" in textos
    w.nav.setCurrentRow(textos.index("Biblioteca"))
    assert w.pila.currentWidget() is w.biblioteca_tab
