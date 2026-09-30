import importlib.util
from pathlib import Path

from app import db, ui_main


def test_plantilla_inicial_exacta(conn):
    t = db.obtener_plantilla_notas(conn)
    assert t.startswith("ALCANCE\n• Diseño estructural integral:")
    assert t.endswith("el precio de esa torre se reajustará.")
    assert t.count("\n• ") == 13
    for titulo in ("EXCLUSIONES", "REVISIONES", "FORMA DE PAGO", "VALIDEZ DE LA OFERTA", "OBSERVACIONES"):
        assert f"\n{titulo}\n" in t


def test_plantilla_persiste_y_se_restaura(conn):
    db.guardar_plantilla_notas("Personalizada", conn)
    conn.close()
    c2 = db.get_connection()  # "nueva sesión"
    assert db.obtener_plantilla_notas(c2) == "Personalizada"
    assert db.restaurar_plantilla_notas(c2) == db.PLANTILLA_NOTAS_INICIAL
    assert db.obtener_plantilla_notas(c2) == db.PLANTILLA_NOTAS_INICIAL
    c2.close()


def test_opciones_por_defecto(conn):
    assert db.mostrar_estado_pdf(conn) is False
    assert db.obtener_tasa_itbms(conn) == 0.07


def test_itbms_exento_se_aplica_al_guardar_items(conn):
    db.guardar_config("itbms_tasa", "0", conn)
    sub, itbms, total = db.guardar_items(1, [("x", 1, 23551.60), ("y", 1, 9420.64)], conn)
    assert (sub, itbms, total) == (32972.24, 0, 32972.24)


def test_parsear_numero():
    p = ui_main.parsear_numero
    assert p("23,551.60") == 23551.60
    assert p("23551.60") == 23551.60
    assert p("23551,60") == 23551.60
    assert p("1,234") == 1234
    assert p("B/. 9,420.64") == 9420.64
    assert p("") == 0 and p("abc") is None


def test_ui_configuracion_guarda_y_restaura(conn, qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: None))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.Yes))
    tab = ui_main.ConfiguracionTab()
    assert not tab.chk_estado.isChecked()
    tab.chk_estado.setChecked(True)
    tab.itbms_tasa.setText("0")
    tab.plantilla_edit.setPlainText("Mi plantilla")
    tab.guardar_opciones()
    tab.guardar_plantilla()
    assert db.mostrar_estado_pdf(conn) and db.obtener_tasa_itbms(conn) == 0
    assert db.obtener_plantilla_notas(conn) == "Mi plantilla"
    tab.restaurar_plantilla()
    assert db.obtener_plantilla_notas(conn) == db.PLANTILLA_NOTAS_INICIAL
    assert tab.plantilla_edit.toPlainText() == db.PLANTILLA_NOTAS_INICIAL


def test_insertar_plantilla_agrega_o_reemplaza(conn, qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    dlg = ui_main.ItemsDialog(1, "COT", editable=True)
    dlg.insertar_plantilla()  # vacío: inserta directo
    assert dlg.notas_edit.toPlainText() == db.PLANTILLA_NOTAS_INICIAL

    dlg.notas_edit.setPlainText("Previo")
    def elegir(texto):
        monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
        monkeypatch.setattr(QMessageBox, "clickedButton",
                            lambda self: next(b for b in self.buttons() if b.text() == texto))

    elegir("Agregar al final")
    dlg.insertar_plantilla()
    assert dlg.notas_edit.toPlainText() == "Previo\n\n" + db.PLANTILLA_NOTAS_INICIAL

    dlg.notas_edit.setPlainText("Previo")
    elegir("Reemplazar")
    dlg.insertar_plantilla()
    assert dlg.notas_edit.toPlainText() == db.PLANTILLA_NOTAS_INICIAL

    dlg.notas_edit.setPlainText("Previo")
    elegir("Cancelar")
    dlg.insertar_plantilla()
    assert dlg.notas_edit.toPlainText() == "Previo"


def test_notas_de_factura_editables(conn):
    db.guardar_notas(1, "Original", conn)
    db.cambiar_estado_cotizacion(1, "enviada", conn)
    db.cambiar_estado_cotizacion(1, "aprobada", conn)
    db.generar_factura(1, conn)
    assert db.obtener_notas_factura(1, conn) == "Original"
    db.guardar_notas_factura(1, "Editada en factura", conn)
    assert db.obtener_notas_factura(1, conn) == "Editada en factura"
    assert db.obtener_notas(1, conn) == "Original"


def test_script_ejemplo_curio(conn):
    spec = importlib.util.spec_from_file_location(
        "ejemplo_curio", Path(__file__).resolve().parent.parent / "scripts" / "ejemplo_curio.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    antes = dict(conn.execute("SELECT * FROM cotizaciones WHERE id = 1").fetchone())
    numero = mod.crear_ejemplo(conn)
    assert numero == "COT-2026-0002" or numero.startswith("COT-")
    fila = conn.execute("SELECT * FROM cotizaciones WHERE numero = ?", (numero,)).fetchone()
    assert (fila["subtotal"], fila["itbms"], fila["total"]) == (32972.24, 0, 32972.24)
    assert fila["proyecto"] == "Torres Curio A y B"
    assert fila["notas"] == db.PLANTILLA_NOTAS_INICIAL
    assert mod.crear_ejemplo(conn) is None  # no duplica
    assert dict(conn.execute("SELECT * FROM cotizaciones WHERE id = 1").fetchone()) == antes
