from app import db, ui_main


def test_editor_carga_guarda_e_inserta_plantilla(conn, qapp):
    db.guardar_notas(1, "Nota previa", conn)
    dlg = ui_main.ItemsDialog(1, "COT-2026-0001", editable=True)
    assert dlg.notas_edit.toPlainText() == "Nota previa"

    dlg.notas_edit.clear()
    dlg.insertar_plantilla()
    assert dlg.notas_edit.toPlainText() == db.PLANTILLA_NOTAS_INICIAL

    dlg.notas_edit.setPlainText("Nuevo texto\nsegunda línea")
    dlg.guardar()
    assert db.obtener_notas(1, conn) == "Nuevo texto\nsegunda línea"


def test_editor_solo_lectura_si_no_es_borrador(conn, qapp):
    dlg = ui_main.ItemsDialog(1, "COT-2026-0001", editable=False)
    assert dlg.notas_edit.isReadOnly()
    assert not dlg.btn_plantilla.isEnabled()
