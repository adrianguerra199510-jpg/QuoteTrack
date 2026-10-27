import re

import pytest

from app import db, pdf, ui_main
from app.calculo import Linea


def contenido(ruta):
    return ruta.read_bytes().decode("latin-1")


def test_empresa_inicial_y_varias_empresas(conn):
    assert [e["nombre"] for e in db.listar_empresas(conn)] == ["INTEGRO SA"]
    b = db.guardar_empresa({"nombre": "Empresa B", "itbms_tasa": 7, "ruc": "123-45"}, conn)
    c = db.guardar_empresa({"nombre": "Empresa C", "itbms_tasa": 0}, conn)
    nombres = [e["nombre"] for e in db.listar_empresas(conn)]
    assert nombres[0] == "INTEGRO SA" and set(nombres) == {"INTEGRO SA", "Empresa B", "Empresa C"}
    assert db.obtener_empresa(b, conn)["ruc"] == "123-45"
    assert db.obtener_empresa(c, conn)["predeterminada"] == 0


def test_nombre_obligatorio_y_tasa_valida(conn):
    with pytest.raises(ValueError):
        db.guardar_empresa({"nombre": "  "}, conn)
    with pytest.raises(ValueError):
        db.guardar_empresa({"nombre": "X", "itbms_tasa": -1}, conn)


def test_editar_y_cambiar_predeterminada(conn):
    b = db.guardar_empresa({"nombre": "Empresa B"}, conn)
    db.guardar_empresa({"nombre": "Empresa B2", "itbms_tasa": 5}, conn, b)
    assert db.obtener_empresa(b, conn)["nombre"] == "Empresa B2"
    db.establecer_empresa_predeterminada(b, conn)
    assert db.empresa_predeterminada_id(conn) == b
    assert sum(e["predeterminada"] for e in db.listar_empresas(conn)) == 1


def test_eliminar_protege_ultima_y_en_uso(conn):
    with pytest.raises(ValueError):
        db.eliminar_empresa(db.empresa_predeterminada_id(conn), conn)       # es la única
    b = db.guardar_empresa({"nombre": "Empresa B"}, conn)
    db.cambiar_empresa_cotizacion(1, b, conn)
    with pytest.raises(ValueError):
        db.eliminar_empresa(b, conn)                                          # tiene cotizaciones
    sin_uso = db.guardar_empresa({"nombre": "Sin uso"}, conn)
    db.eliminar_empresa(sin_uso, conn)
    assert db.obtener_empresa(sin_uso, conn) is None


def test_eliminar_la_predeterminada_asigna_otra(conn):
    b = db.guardar_empresa({"nombre": "Empresa B"}, conn)
    db.cambiar_empresa_cotizacion(1, b, conn)
    db.eliminar_empresa(db.empresa_predeterminada_id(conn), conn)
    assert db.empresa_predeterminada_id(conn) == b
    assert db.listar_empresas(conn)[0]["predeterminada"] == 1


def test_cotizacion_usa_la_tasa_de_su_empresa(conn):
    exenta = db.guardar_empresa({"nombre": "Exenta", "itbms_tasa": 0}, conn)
    con_itbms = db.guardar_empresa({"nombre": "Con ITBMS", "itbms_tasa": 7}, conn)
    i1, _ = db.crear_cotizacion(1, conn, exenta)
    i2, _ = db.crear_cotizacion(1, conn, con_itbms)
    for i in (i1, i2):
        db.guardar_cotizacion(i, [Linea("item", 0, "x", 1, 100.0)], [], conn)
    assert db.totales_cotizacion(i1, conn).total == 100.0
    assert db.totales_cotizacion(i2, conn).total == 107.0


def test_factura_hereda_la_empresa(conn):
    b = db.guardar_empresa({"nombre": "Empresa B"}, conn)
    db.cambiar_empresa_cotizacion(1, b, conn)
    db.cambiar_estado_cotizacion(1, "enviada", conn)
    db.cambiar_estado_cotizacion(1, "aprobada", conn)
    db.generar_factura(1, conn)
    assert conn.execute("SELECT empresa_id FROM facturas").fetchone()["empresa_id"] == b
    assert db.empresa_de_factura(1, conn)["nombre"] == "Empresa B"


def test_pdf_imprime_la_empresa_de_cada_cotizacion(conn, tmp_path, pdf_sin_comprimir):
    b = db.guardar_empresa({"nombre": "Constructora Beta", "subtitulo": "OBRAS CIVILES", "ruc": "99-88"}, conn)
    pdf.exportar_cotizacion(1, str(tmp_path / "a.pdf"))
    db.cambiar_empresa_cotizacion(1, b, conn)
    pdf.exportar_cotizacion(1, str(tmp_path / "b.pdf"))
    assert "INTEGRO SA" in contenido(tmp_path / "a.pdf") and "Constructora Beta" not in contenido(tmp_path / "a.pdf")
    txt = contenido(tmp_path / "b.pdf")
    assert "Constructora Beta" in txt and "OBRAS CIVILES" in txt and "RUC: 99-88" in txt and "INTEGRO SA" not in txt


def test_logo_de_la_empresa_en_el_pdf(conn, tmp_path, qapp):
    from PySide6.QtGui import QColor, QImage
    from app.ui_empresas import preparar_logo
    img = QImage(900, 400, QImage.Format_ARGB32)
    img.fill(QColor("#1D4ED8"))
    ruta_img = tmp_path / "logo.png"
    img.save(str(ruta_img))
    logo = preparar_logo(str(ruta_img))
    assert logo[:8] == b"\x89PNG\r\n\x1a\n"
    assert QImage.fromData(logo).width() <= 700          # se reduce si es muy grande
    db.guardar_empresa({"nombre": "Con Logo", "logo": logo}, conn, db.empresa_predeterminada_id(conn))
    ruta = tmp_path / "c.pdf"
    pdf.exportar_cotizacion(1, str(ruta))
    assert re.search(rb"/Subtype /Image", ruta.read_bytes())


def test_logo_invalido_se_rechaza(tmp_path, qapp):
    from app.ui_empresas import preparar_logo
    malo = tmp_path / "no_es_imagen.png"
    malo.write_bytes(b"esto no es una imagen")
    with pytest.raises(ValueError):
        preparar_logo(str(malo))


def test_logo_corrupto_no_rompe_el_pdf(conn, tmp_path):
    db.guardar_empresa({"nombre": "Logo roto", "logo": b"basura"}, conn, db.empresa_predeterminada_id(conn))
    pdf.exportar_cotizacion(1, str(tmp_path / "c.pdf"))


def test_ui_empresas_tab(conn, qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from app.ui_empresas import EmpresasTab
    db.guardar_empresa({"nombre": "Empresa B"}, conn)
    db.cambiar_empresa_cotizacion(1, db.empresa_predeterminada_id(conn), conn)  # INTEGRO SA queda en uso
    tab = EmpresasTab()
    assert tab.tabla.rowCount() == 2
    assert not tab.btn_eliminar.isEnabled() or tab._id_seleccionado() is not None
    tab.tabla.setCurrentCell(1, 1)
    assert tab.tabla.item(1, 1).text() == "Empresa B"
    tab.hacer_predeterminada()
    assert tab.tabla.item(0, 1).text() == "Empresa B"       # la predeterminada va primero
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.Yes))
    tab.tabla.setCurrentCell(1, 1)                          # INTEGRO SA, con cotización asociada
    avisos = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: avisos.append(a[2])))
    tab.eliminar_empresa()
    assert avisos and "cotización" in avisos[0] and tab.tabla.rowCount() == 2


def test_ui_nueva_cotizacion_con_empresa_elegida(conn, qapp, monkeypatch):
    b = db.guardar_empresa({"nombre": "Empresa B"}, conn)
    w = ui_main.MainWindow()
    tab = w.cotizaciones_tab
    tab.refrescar()
    cliente = conn.execute("SELECT id FROM clientes").fetchone()["id"]
    pedidos = []
    monkeypatch.setattr(ui_main.CotizacionesTab, "_pedir_cliente_y_empresa",
                        staticmethod(lambda p: pedidos.append(1) or (cliente, b)))
    tab.nueva_cotizacion()
    assert pedidos
    fila = conn.execute("SELECT empresa_id FROM cotizaciones ORDER BY id DESC LIMIT 1").fetchone()
    assert fila["empresa_id"] == b
    assert tab.tabla.item(0, 3).text() == "Empresa B"
