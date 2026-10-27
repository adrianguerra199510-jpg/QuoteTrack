import pytest
from docx import Document

from app import db, documento, pdf, ui_main, word
from app.calculo import Linea


@pytest.fixture
def cot(conn):
    """Cotización 1 aprobada: 1 ítem de 1,000.00 con ITBMS 7% -> total 1,070.00."""
    db.guardar_cotizacion(1, [Linea("item", 0, "Diseño", 1, 1000.0, True, "gl")], [], conn, tasa=0.07)
    db.cambiar_estado_cotizacion(1, "enviada", conn)
    db.cambiar_estado_cotizacion(1, "aprobada", conn)
    return conn


def facturas(conn):
    return conn.execute("SELECT * FROM facturas ORDER BY id").fetchall()


def test_factura_unica_como_antes(cot):
    db.generar_factura(1, cot)
    f = facturas(cot)[0]
    assert f["total"] == 1070.0 and f["concepto"] == "" and f["porcentaje"] == 100
    with pytest.raises(ValueError, match="por completo"):
        db.generar_factura(1, cot)


def test_tres_etapas_30_40_30(cot):
    db.generar_factura(1, cot, porcentaje=30)
    db.generar_factura(1, cot, porcentaje=40)
    r = db.resumen_facturacion(1, cot)
    assert r["facturado"] == 749.0 and r["saldo"] == 321.0 and r["facturas"] == 2
    db.generar_factura(1, cot, porcentaje=30)                 # 30% de 1,070 = 321.00 = saldo exacto
    f = facturas(cot)
    assert [x["total"] for x in f] == [321.0, 428.0, 321.0]
    assert [x["concepto"] for x in f] == ["Abono 1 (30%)", "Abono 2 (40%)", "Saldo final"]
    assert db.resumen_facturacion(1, cot)["saldo"] == 0
    with pytest.raises(ValueError):
        db.generar_factura(1, cot)


def test_la_ultima_toma_el_saldo_exacto_sin_centavos_sueltos(conn):
    db.guardar_cotizacion(1, [Linea("item", 0, "X", 1, 100.0, True, "gl")], [], conn, tasa=0.0)
    db.cambiar_estado_cotizacion(1, "enviada", conn)
    db.cambiar_estado_cotizacion(1, "aprobada", conn)
    for _ in range(2):
        db.generar_factura(1, conn, porcentaje=33.33)          # 33.33 + 33.33
    db.generar_factura(1, conn, porcentaje=33.34)
    assert round(sum(f["total"] for f in facturas(conn)), 2) == 100.0
    assert db.resumen_facturacion(1, conn)["saldo"] == 0


def test_validaciones(cot):
    for kwargs in ({"porcentaje": 0}, {"porcentaje": 101}, {"monto": 0}, {"monto": 2000}):
        with pytest.raises(ValueError):
            db.generar_factura(1, cot, **kwargs)
    db.generar_factura(1, cot, monto=500, concepto="Anticipo")
    assert facturas(cot)[0]["concepto"] == "Anticipo" and facturas(cot)[0]["porcentaje"] == pytest.approx(46.729, abs=0.001)
    with pytest.raises(ValueError):
        db.generar_factura(1, cot, monto=600)                  # excede el saldo de 570


def test_borrador_no_se_factura(conn):
    with pytest.raises(ValueError, match="aprobada"):
        db.generar_factura(1, conn, porcentaje=30)


def test_documento_reparte_itbms_y_resumen(cot):
    for p in (30, 40, 30):
        db.generar_factura(1, cot, porcentaje=p)
    ids = [f["id"] for f in facturas(cot)]
    docs = [documento.de_factura(i, False) for i in ids]
    assert round(sum(d.totales.itbms for d in docs), 2) == 70.0       # el ITBMS suma el de la cotización
    assert round(sum(d.totales.total for d in docs), 2) == 1070.0
    assert all(round(d.totales.subtotal + d.totales.itbms, 2) == d.totales.total for d in docs)
    segunda = docs[1]
    assert [round(m, 2) for _e, m, _u in segunda.resumen] == [1070.0, 321.0, 428.0, 321.0]
    assert "40%" in segunda.concepto
    # una factura única conserva el desglose completo de la cotización
    assert documento.de_factura(ids[0], False).resumen


def test_factura_unica_sin_resumen(cot):
    db.generar_factura(1, cot)
    d = documento.de_factura(facturas(cot)[0]["id"], False)
    assert d.resumen == [] and d.concepto == "" and d.totales.total == 1070.0


def test_pdf_y_word_de_una_etapa(cot, tmp_path, pdf_sin_comprimir):
    db.generar_factura(1, cot, porcentaje=30, concepto="Abono inicial")
    fid = facturas(cot)[0]["id"]
    pdf.exportar_factura(fid, str(tmp_path / "f.pdf"))
    datos = (tmp_path / "f.pdf").read_bytes()
    assert b"Abono inicial" in datos and b"Saldo pendiente" in datos
    word.exportar_factura(fid, str(tmp_path / "f.docx"))
    d = Document(str(tmp_path / "f.docx"))
    texto = "\n".join([p.text for p in d.paragraphs] + [c.text for t in d.tables for r in t.rows for c in r.cells])
    assert "Abono inicial" in texto and "Saldo pendiente:" in texto and "749.00" in texto


def test_dialogo_de_etapa(cot, qapp):
    r = db.resumen_facturacion(1, cot)
    d = ui_main.FacturaEtapaDialog("COT-2026-0001", r)
    assert d.datos() == {"monto": 1070.0, "concepto": None}          # por defecto: todo el saldo
    d.pct.setValue(30)
    assert d.monto.value() == 321.0 and d.datos()["monto"] == 321.0
    d.monto.setValue(107.0)
    assert d.pct.value() == 10.0
    d._porcentaje(40)
    assert d.monto.value() == 428.0
    d.concepto.setText("Anticipo")
    assert d.datos() == {"monto": 428.0, "concepto": "Anticipo"}


def test_generar_desde_la_pestana(conn, qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    db.guardar_cotizacion(1, [Linea("item", 0, "Diseño", 1, 1000.0, True, "gl")], [], conn, tasa=0.0)
    db.cambiar_estado_cotizacion(1, "enviada", conn)
    db.cambiar_estado_cotizacion(1, "aprobada", conn)
    w = ui_main.MainWindow()
    t = w.cotizaciones_tab
    t._ventana = w
    t.refrescar()
    t.tabla.setCurrentCell(0, 0)
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: None))
    avisos = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: avisos.append(a[2])))
    pedidos = iter([{"monto": 300.0, "concepto": None}, {"monto": 700.0, "concepto": None}])
    monkeypatch.setattr(ui_main.CotizacionesTab, "_pedir_factura", staticmethod(lambda p, n, r: next(pedidos)))
    t.generar_factura()
    t.generar_factura()
    assert [f["total"] for f in facturas(conn)] == [300.0, 700.0]
    t.generar_factura()                                           # ya no hay saldo
    assert avisos and "por completo" in avisos[0]
    f = w.facturas_tab
    f.refrescar()
    assert f.tabla.rowCount() == 2 and {f.tabla.item(i, 7).text() for i in range(2)} == {"Abono 1 (30%)", "Saldo final"}


def test_notas_de_cada_factura_por_etapa(cot):
    db.generar_factura(1, cot, porcentaje=30)
    db.generar_factura(1, cot, porcentaje=70)
    abono, final = [f["notas"] for f in facturas(cot)]
    assert "abono del 30%" in abono and "B/. 321.00" in abono and "saldo pendiente tras este pago será de B/. 749.00" in abono
    assert "se aplicará a la cotización COT-2026-0001" in abono
    assert "cancelación del saldo pendiente y liquidación total del monto final acordado de B/. 1,070.00" in final
    assert "formalmente finiquitada" in final and "Banco General" in final and "Yappy" in final
    assert all(f["titulo_notas"] == "Términos de pago" for f in facturas(cot))


def test_plantilla_de_facturas_editable(cot):
    db.guardar_plantilla_factura("Pagar {monto} de {total} ({porcentaje}%) ref {cotizacion}", cot)
    db.generar_factura(1, cot, porcentaje=25)
    assert facturas(cot)[0]["notas"] == "Pagar B/. 267.50 de B/. 1,070.00 (25%) ref COT-2026-0001"
    assert db.restaurar_plantilla_factura(cot) == db.PLANTILLA_FACTURA_INICIAL


def test_pdf_y_word_con_viñetas_anidadas(cot, tmp_path):
    db.generar_factura(1, cot)
    fid = facturas(cot)[0]["id"]
    word.exportar_factura(fid, str(tmp_path / "f.docx"))
    d = Document(str(tmp_path / "f.docx"))
    estilos = {p.text: p.style.name for p in d.paragraphs}
    assert estilos["ACH / Transferencia Bancaria:"] == "List Bullet"
    assert estilos["Banco: Banco General"] == "List Bullet 2"
    pdf.exportar_factura(fid, str(tmp_path / "f.pdf"))


def test_configuracion_edita_plantilla_de_facturas(conn, qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: None))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.Yes))
    w = ui_main.MainWindow()
    cfg = w.configuracion_tab
    cfg.plantilla_factura_edit.setPlainText("Texto propio {monto}")
    cfg.guardar_plantilla_factura()
    assert db.obtener_plantilla_factura(conn) == "Texto propio {monto}"
    cfg.restaurar_plantilla_factura()
    assert db.obtener_plantilla_factura(conn) == db.PLANTILLA_FACTURA_INICIAL


def test_eliminar_factura_devuelve_el_saldo(cot):
    db.generar_factura(1, cot, porcentaje=30)
    db.generar_factura(1, cot, porcentaje=40)
    primera = facturas(cot)[0]
    assert db.eliminar_factura(primera["id"], cot) == primera["numero"]
    assert db.resumen_facturacion(1, cot)["facturado"] == 428.0
    db.generar_factura(1, cot, porcentaje=30)                          # el saldo liberado se puede volver a facturar
    assert len(facturas(cot)) == 2
    with pytest.raises(ValueError):
        db.eliminar_factura(999, cot)


def test_eliminar_factura_pagada_desde_la_interfaz(cot, qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    db.generar_factura(1, cot)
    db.marcar_factura_pagada(1, "2026-02-01", cot)
    w = ui_main.MainWindow()
    f = w.facturas_tab
    f._ventana = w
    f.refrescar()
    f.tabla.setCurrentCell(0, 0)
    assert f.btn_eliminar.isEnabled()
    mensajes = []
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda p, t, texto, *a: mensajes.append(texto) or QMessageBox.No))
    f.eliminar_factura()                                               # se cancela: no se borra
    assert len(facturas(cot)) == 1 and "PAGADA" in mensajes[0]
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.Yes))
    [a for a in f.construir_menu().actions() if a.text() == "Eliminar factura…"][0].trigger()
    assert facturas(cot) == [] and f.tabla.rowCount() == 0 and not f.btn_eliminar.isEnabled()
