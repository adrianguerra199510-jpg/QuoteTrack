import pytest

from app import calculo
from app.calculo import Apu, Cargo, ConfigApu, Insumo, Linea


def obra(cantidad=1.0):
    """Ítem con APU: materiales 100, mano de obra 50 (coeficientes 0% para cuentas redondas)."""
    apu = Apu(1.0, [Insumo("material", "Bloques", "u", 1, 1, 100.0), Insumo("mano_obra", "Albañil", "h", 1, 1, 50.0)])
    return Linea("item", 0, "Muro", cantidad, 0.0, True, "m2", calculo.OBRA, apu)


CFG = ConfigApu(0, 0, 0, 0)


def servicio(precio):
    return Linea("item", 0, "Diseño", 1, precio, True, "gl")


def test_sin_base_ni_dilucion_no_cambia_nada():
    t = calculo.calcular([servicio(1000)], [Cargo("Admin", "porcentaje", 10)], 0.07, CFG)
    assert t.subtotal == 1000 and t.cargos_total == 100 and t.itbms == 77 and t.total == 1177 and t.diluidos == []


def test_porcentaje_solo_sobre_mano_de_obra():
    l = obra(2)                       # materiales 200 + mano de obra 100 = 300
    t = calculo.calcular([l], [Cargo("Admin", "porcentaje", 10, True, "mano_obra")], 0.0, CFG)
    assert t.subtotal == 300 and t.cargos_total == 10.0                      # 10% de 100, no de 300
    assert t.total == 310.0


def test_varias_categorias_y_servicios():
    lineas = [obra(1), servicio(400)]    # mat 100, mo 50, servicio 400
    t = calculo.calcular(lineas, [Cargo("X", "porcentaje", 10, True, "material,servicio")], 0.0, CFG)
    assert t.cargos_total == 50.0        # 10% de (100 + 400)


def test_diluir_uniforme_reparte_en_todos_los_items():
    a, b = servicio(300), servicio(100)
    t = calculo.calcular([a, b], [Cargo("Utilidad", "porcentaje", 20, True, "", True)], 0.0, CFG)
    assert (a.ajuste, b.ajuste) == (60.0, 20.0)                  # 20% de cada uno
    assert (a.importe_propio, b.importe_propio) == (360.0, 120.0)
    assert t.subtotal == 480.0 and t.cargos == [] and t.cargos_total == 0 and t.total == 480.0
    assert [m for _c, m in t.diluidos] == [80.0]
    assert a.precio_mostrado == 360.0 and a.precio == 300.0      # el precio guardado no cambia


def test_diluir_solo_en_la_categoria_elegida():
    muro, diseno = obra(1), servicio(500)
    cargo = Cargo("Administración", "porcentaje", 10, True, "mano_obra", True)
    calculo.calcular([muro, diseno], [cargo], 0.0, CFG)
    assert muro.ajuste == 5.0 and diseno.ajuste == 0.0           # solo el ítem que tiene mano de obra


def test_reparto_exacto_sin_centavos_perdidos():
    lineas = [servicio(10), servicio(10), servicio(10)]
    t = calculo.calcular(lineas, [Cargo("Fijo", "monto", 100, True, "", True)], 0.0, CFG)
    assert sorted(l.ajuste for l in lineas) == [33.33, 33.33, 33.34]
    assert t.subtotal == 130.0 and t.total == 130.0


def test_cargo_diluido_sigue_el_itbms_de_cada_item():
    gravado, exento = servicio(100), servicio(100)
    exento.aplica_itbms = False
    t = calculo.calcular([gravado, exento], [Cargo("Util", "monto", 100, False, "", True)], 0.10, CFG)
    assert (gravado.ajuste, exento.ajuste) == (50.0, 50.0)
    assert t.base_itbms == 150.0 and t.itbms == 15.0 and t.total == 315.0


def test_cargo_sin_base_en_la_categoria_se_reparte_en_todos():
    s = servicio(200)
    calculo.calcular([s], [Cargo("Fijo", "monto", 30, True, "material", True)], 0.0, CFG)
    assert s.ajuste == 30.0          # no hay materiales: cae al reparto uniforme


def test_recalcular_no_acumula_ajustes():
    l = servicio(100)
    cargo = Cargo("U", "porcentaje", 10, True, "", True)
    calculo.calcular([l], [cargo], 0.0, CFG)
    calculo.calcular([l], [cargo], 0.0, CFG)
    assert l.ajuste == 10.0


def test_grupo_suma_sus_subitems_diluidos():
    g = Linea("grupo", 0, "G")
    a, b = Linea("item", 1, "a", 1, 100.0), Linea("item", 1, "b", 1, 100.0)
    calculo.calcular([g, a, b], [Cargo("U", "porcentaje", 10, True, "", True)], 0.0, CFG)
    assert calculo.importes([g, a, b])[0] == 220.0


def test_resumen():
    lineas = [obra(1), servicio(400)]
    cfg = ConfigApu(0.10, 0.20, 0.15, 0.15)
    filas = calculo.resumen(lineas, [Cargo("Administración", "porcentaje", 10, True, "mano_obra", True),
                                     Cargo("Utilidad", "porcentaje", 5)], 0.07, cfg)
    d = {e: m for e, m, _s in filas}
    assert d["Materiales"] == 100.0 and d["Mano de obra"] == 50.0
    assert d["Servicios profesionales (precio fijo)"] == 400.0 and d["Costo directo total"] == 550.0
    assert d["Coeficientes de venta (utilidad y gastos del análisis)"] == 20.0      # 100×10% + 50×20%
    assert d["Subtotal de ítems (sin costos adicionales)"] == 570.0
    assert any(e.startswith("Administración (10% sobre mano de obra: B/. 60.00") and e.endswith("diluido en los ítems")
               for e in d)
    assert any(e.startswith("Utilidad (5% sobre todo el subtotal") for e in d)
    total = filas[-1]
    assert total[0] == "TOTAL" and total[2] == "total" and total[1] > 570


# ----------------------------------------------------------------- persistencia y documentos
def test_se_guardan_base_y_dilucion_y_se_duplican(conn):
    from app import db
    db.guardar_cotizacion(1, [obra(1), servicio(400)], [
        Cargo("Administración", "porcentaje", 10, True, "mano_obra,material", True), Cargo("Utilidad", "porcentaje", 5)],
        conn, tasa=0.0, cfg=CFG)
    c = db.obtener_cargos(1, conn)
    assert (c[0].base, c[0].diluir, c[1].base, c[1].diluir) == ("mano_obra,material", True, "", False)
    nuevo, _ = db.duplicar_cotizacion(1, conn)
    d = db.obtener_cargos(nuevo, conn)
    assert (d[0].base, d[0].diluir) == ("mano_obra,material", True)
    t = db.totales_cotizacion(1, conn)
    assert t.subtotal == 565.0 and conn.execute("SELECT total FROM cotizaciones WHERE id = 1").fetchone()[0] == t.total


def test_pdf_y_word_muestran_el_precio_diluido(conn, tmp_path, pdf_sin_comprimir):
    from docx import Document
    from app import db, documento, pdf, word
    db.guardar_cotizacion(1, [servicio(1000)], [Cargo("Utilidad", "porcentaje", 20, True, "", True)], conn,
                          tasa=0.0, cfg=CFG)
    doc = documento.de_cotizacion(1, False)
    assert doc.lineas[0].precio_mostrado == 1200.0 and doc.totales.cargos == [] and doc.totales.total == 1200.0
    pdf.exportar_cotizacion(1, str(tmp_path / "c.pdf"))
    datos = (tmp_path / "c.pdf").read_bytes()
    assert b"1,200.00" in datos and b"Utilidad" not in datos          # no aparece como línea aparte
    word.exportar_cotizacion(1, str(tmp_path / "c.docx"))
    d = Document(str(tmp_path / "c.docx"))
    texto = "\n".join(c.text for t in d.tables for r in t.rows for c in r.cells)
    assert "1,200.00" in texto and "Utilidad" not in texto


# ----------------------------------------------------------------- interfaz
def test_editor_base_dilucion_y_resumen(conn, qapp, monkeypatch):
    from PySide6.QtCore import Qt
    from app import db, ui_items
    from app.ui_items import CARGO_BASE, CARGO_DILUIR, CARGO_MONTO, COL_IMPORTE
    db.guardar_cotizacion(1, [servicio(1000)], [Cargo("Utilidad", "porcentaje", 10, True)], conn, tasa=0.0, cfg=CFG)
    d = ui_items.ItemsDialog(1, "COT-2026-0001", editable=True)
    assert d.tabla_cargos.item(0, CARGO_BASE).text() == "Todo el subtotal"
    assert d.tabla_cargos.item(0, CARGO_MONTO).text() == "B/. 100.00"
    d.tabla_cargos.item(0, CARGO_DILUIR).setCheckState(Qt.Checked)               # diluir en los ítems
    assert d.cargos[0].diluir and d.tabla.item(0, COL_IMPORTE).text() == "B/. 1,100.00"
    assert "Incluye" in d.tabla.item(0, COL_IMPORTE).toolTip()
    assert "diluidos" in d.lbl_totales.text()
    # elegir la base con el diálogo (simulando la selección)
    monkeypatch.setattr(ui_items.ItemsDialog, "_ejecutar", staticmethod(lambda dlg: dlg.checks["servicio"].setChecked(True) or 1))
    d.elegir_base_cargo(0)
    assert d.cargos[0].base == "servicio" and d.tabla_cargos.item(0, CARGO_BASE).text() == "Servicios profesionales"
    assert d._guardar_en_db()
    assert db.obtener_cargos(1, conn)[0].base == "servicio" and db.obtener_cargos(1, conn)[0].diluir


def test_dialogo_de_base():
    from app import ui_items
    c = Cargo("A", "porcentaje", 5, True, "material,mano_obra")
    dlg = ui_items.BaseCargoDialog(c)
    assert dlg.algunas.isChecked() and dlg.base() == "material,mano_obra"
    dlg.todo.setChecked(True)
    assert dlg.base() == "" and not any(ch.isChecked() for ch in dlg.checks.values())
    dlg.checks["auxiliar"].setChecked(True)
    assert dlg.algunas.isChecked() and dlg.base() == "auxiliar"


def test_resumen_boton_del_editor_y_de_la_pestana(conn, qapp, monkeypatch):
    from app import db, ui_items, ui_main
    db.guardar_cotizacion(1, [obra(1), servicio(400)], [Cargo("Administración", "porcentaje", 10, True, "mano_obra", True)],
                          conn, tasa=0.0, cfg=CFG)
    abiertos = []
    monkeypatch.setattr(ui_items.ResumenDialog, "exec", lambda self: abiertos.append(self) or 0)
    d = ui_items.ItemsDialog(1, "COT-2026-0001", editable=True)
    d.btn_resumen.click()
    r = abiertos[0]
    textos = [r.tabla.item(i, 0).text() for i in range(r.tabla.rowCount())]
    assert "Costo directo total" in textos and "TOTAL" in textos
    assert r.tabla.item(r.tabla.rowCount() - 1, 2).text() == "100.0%"
    assert "Materiales\t100.00" in r.texto()
    w = ui_main.MainWindow()
    t = w.cotizaciones_tab
    t._ventana = w
    t.refrescar()
    t.tabla.setCurrentCell(0, 0)
    t.btn_resumen.click()
    assert len(abiertos) == 2


def test_grafica_del_resumen(qapp):
    from app import ui_items
    filas = calculo.resumen([obra(1), servicio(400)], [Cargo("Administración", "porcentaje", 10, True, "mano_obra", True)],
                            0.07, ConfigApu(0.10, 0.20, 0.15, 0.15))
    dlg = ui_items.ResumenDialog(filas)
    g = dlg.grafica
    nombres = [n for n, _m in g.partes]
    assert nombres[0] == "Servicios profesionales" and "Administración" in nombres and "ITBMS" in nombres
    assert [m for _n, m in g.partes] == sorted((m for _n, m in g.partes), reverse=True)
    assert round(sum(m for _n, m in g.partes), 2) == g.total          # los componentes suman el total
    assert dlg.pestanas.count() == 2
    dlg.show()
    dlg.pestanas.setCurrentIndex(1)
    assert not dlg.grab().isNull()                                    # se dibuja sin errores
