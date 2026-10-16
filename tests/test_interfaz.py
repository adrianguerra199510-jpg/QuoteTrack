import struct

from app import db, estilo, iconos, ui_main
from app.recursos import ruta_recurso


def test_todos_los_iconos_se_dibujan(qapp):
    from PySide6.QtGui import QImage
    for nombre in iconos.nombres():
        img = iconos.pixmap(nombre, "#1D4ED8", 24).toImage()
        assert not img.isNull(), nombre
        visibles = sum(1 for x in range(0, img.width(), 2) for y in range(0, img.height(), 2)
                       if QImage.pixelColor(img, x, y).alpha() > 0)
        assert visibles > 0, f"el icono {nombre} está vacío"


def test_icono_tiene_estado_desactivado(qapp):
    from PySide6.QtGui import QIcon
    ic = iconos.icono("plus")
    assert not ic.pixmap(20, QIcon.Disabled).isNull() and not ic.pixmap(20, QIcon.Normal).isNull()


def test_logo_e_iconos_existen_y_son_validos():
    for nombre in ("logo.svg", "logo.png", "icon.png", "icon.ico"):
        assert ruta_recurso(f"assets/{nombre}").stat().st_size > 500, nombre
    assert ruta_recurso("assets/logo.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    ico = ruta_recurso("assets/icon.ico").read_bytes()
    reservado, tipo, n = struct.unpack("<HHH", ico[:6])
    assert (reservado, tipo) == (0, 1) and n >= 4
    assert ico[6 + 16 * n:6 + 16 * n + 8] == b"\x89PNG\r\n\x1a\n"      # imágenes PNG incrustadas


def test_ventana_principal_con_tema_y_navegacion(conn, qapp):
    estilo.aplicar(qapp)
    w = ui_main.MainWindow()
    assert [w.nav.item(i).text() for i in range(w.nav.count())] == \
        ["Cotizaciones", "Facturas", "Clientes", "Empresas", "Configuración"]
    for i in range(w.nav.count()):          # cada sección se puede abrir sin errores
        w.nav.setCurrentRow(i)
        assert w.pila.currentIndex() == i
    assert not qapp.windowIcon() is None


def test_estado_con_color_y_fila_vencida(conn, qapp):
    db.cambiar_estado_cotizacion(1, "enviada", conn)
    db.cambiar_estado_cotizacion(1, "aprobada", conn)
    db.generar_factura(1, conn)
    db.marcar_factura_vencida(1, conn)
    w = ui_main.MainWindow()
    w.facturas_tab.refrescar()
    celda = w.facturas_tab.tabla.item(0, ui_main.FAC_ESTADO)
    assert celda.text() == "vencida" and celda.background().color().name() == estilo.COLOR_ESTADO["vencida"][0].lower()
    assert w.facturas_tab.tabla.item(0, 0).background().color().name() == ui_main.FacturasTab.COLOR_FILA_VENCIDA.lower()
