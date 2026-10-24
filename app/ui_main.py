"""Ventana principal de QuoteTrack: navegación lateral con Cotizaciones, Facturas, Clientes, Empresas y Configuración."""
import sys

from PySide6.QtCore import QSize, Qt, QDate
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QFrame,
    QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QStackedWidget,
    QMenu, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app import base_cgr, calculo, db, estilo, iconos, pdf, word
from app.recursos import ruta_recurso
from app.ui_comun import (  # noqa: F401  (se reexportan para compatibilidad)
    DescripcionDelegate, FiltroBar, boton, celda_dinero, celda_estado, encabezado_pagina, exportar_pdf, exportar_word,
    pagina,
    parsear_numero, tabla_estandar,
)
from app.ui_biblioteca import BibliotecaTab
from app.ui_empresas import EmpresasTab
from app.ui_items import ItemsDialog  # noqa: F401
from app.ui_vista_previa import vista_previa

COT_ESTADO = 5   # columna «Estado» de la tabla de cotizaciones
FAC_ESTADO = 4   # columna «Estado de pago» de la tabla de facturas


def tarjeta() -> QFrame:
    f = QFrame()
    f.setObjectName("tarjeta")
    f.setStyleSheet(f"QFrame#tarjeta {{ background: white; border: 1px solid {estilo.BORDE}; border-radius: 12px; }}")
    return f


class ClientesTab(QWidget):
    def __init__(self):
        super().__init__()
        lay = pagina(self)
        lay.addWidget(encabezado_pagina(
            "Clientes", "Catálogo de clientes. Selecciona uno de la tabla para editarlo o eliminarlo."))

        card = tarjeta()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 14)
        form = QFormLayout()
        form.setVerticalSpacing(8)
        self.nombre_edit = QLineEdit()
        self.id_edit = QLineEdit()
        self.contacto_edit = QLineEdit()
        form.addRow("Nombre:", self.nombre_edit)
        form.addRow("Identificación (RUC/Cédula):", self.id_edit)
        form.addRow("Contacto:", self.contacto_edit)
        cl.addLayout(form)
        fila = QHBoxLayout()
        self.btn_eliminar = boton("Eliminar", "trash", "peligro")
        self.btn_limpiar = boton("Limpiar", "x")
        self.btn_guardar = boton("Guardar cambios", "save")
        self.btn_add = boton("Agregar cliente", "plus", "primario")
        self.btn_eliminar.clicked.connect(self.eliminar_cliente)
        self.btn_limpiar.clicked.connect(self.limpiar)
        self.btn_guardar.clicked.connect(self.guardar_cambios)
        self.btn_add.clicked.connect(self.agregar_cliente)
        fila.addWidget(self.btn_eliminar)
        fila.addStretch()
        for b in (self.btn_limpiar, self.btn_guardar, self.btn_add):
            fila.addWidget(b)
        cl.addLayout(fila)
        lay.addWidget(card)

        self.tabla = tabla_estandar(["ID", "Nombre", "Identificación", "Contacto"], estirar=1)
        self.tabla.setColumnWidth(0, 60)
        self.tabla.currentCellChanged.connect(lambda *_: self._cargar_seleccion())
        lay.addWidget(self.tabla, 1)
        self.refrescar()

    def _id_seleccionado(self):
        fila = self.tabla.currentRow()
        item = self.tabla.item(fila, 1) if fila >= 0 else None
        return item.data(Qt.UserRole) if item else None

    def _datos(self):
        return {"nombre": self.nombre_edit.text(), "identificacion": self.id_edit.text(),
                "contacto": self.contacto_edit.text()}

    def _cargar_seleccion(self):
        """Al seleccionar una fila se cargan sus datos en el formulario para editarlos."""
        fila = self.tabla.currentRow()
        hay = fila >= 0 and self._id_seleccionado() is not None
        if hay:
            self.nombre_edit.setText(self.tabla.item(fila, 1).text())
            self.id_edit.setText(self.tabla.item(fila, 2).text())
            self.contacto_edit.setText(self.tabla.item(fila, 3).text())
        self.btn_guardar.setEnabled(hay)
        self.btn_eliminar.setEnabled(hay)

    def limpiar(self):
        self.tabla.clearSelection()
        self.tabla.setCurrentCell(-1, -1)
        self.nombre_edit.clear()
        self.id_edit.clear()
        self.contacto_edit.clear()
        self._cargar_seleccion()

    def agregar_cliente(self):
        conn = db.get_connection()
        try:
            db.guardar_cliente(self._datos(), conn)
        except ValueError as e:
            QMessageBox.warning(self, "Falta nombre", str(e))
            return
        finally:
            conn.close()
        self.limpiar()
        self.refrescar()

    def guardar_cambios(self):
        cid = self._id_seleccionado()
        if cid is None:
            return
        conn = db.get_connection()
        try:
            db.guardar_cliente(self._datos(), conn, cid)
        except ValueError as e:
            QMessageBox.warning(self, "Cliente", str(e))
            return
        finally:
            conn.close()
        self.refrescar()

    def eliminar_cliente(self):
        cid = self._id_seleccionado()
        if cid is None:
            return
        if QMessageBox.question(self, "Eliminar cliente", "¿Eliminar el cliente seleccionado?") != QMessageBox.Yes:
            return
        conn = db.get_connection()
        try:
            db.eliminar_cliente(cid, conn)
        except ValueError as e:
            QMessageBox.warning(self, "Eliminar cliente", str(e))
            return
        finally:
            conn.close()
        self.limpiar()
        self.refrescar()

    def refrescar(self):
        conn = db.get_connection()
        filas = conn.execute("SELECT id, nombre, identificacion, contacto FROM clientes ORDER BY nombre").fetchall()
        conn.close()
        sel = self._id_seleccionado()
        self.tabla.blockSignals(True)
        self.tabla.setRowCount(len(filas))
        for i, fila in enumerate(filas):
            nombre = QTableWidgetItem(fila["nombre"])
            nombre.setData(Qt.UserRole, fila["id"])
            self.tabla.setItem(i, 0, QTableWidgetItem(str(fila["id"])))
            self.tabla.setItem(i, 1, nombre)
            self.tabla.setItem(i, 2, QTableWidgetItem(fila["identificacion"] or ""))
            self.tabla.setItem(i, 3, QTableWidgetItem(fila["contacto"] or ""))
            if fila["id"] == sel:
                self.tabla.setCurrentCell(i, 1)
        self.tabla.blockSignals(False)
        self._cargar_seleccion()


class CotizacionesTab(QWidget):
    def __init__(self, on_factura_generada=None):
        super().__init__()
        self.on_factura_generada = on_factura_generada
        lay = pagina(self)
        lay.addWidget(encabezado_pagina("Cotizaciones", "Crea, envía y da seguimiento a tus cotizaciones."))

        top = QHBoxLayout()
        self.cliente_combo = QComboBox()
        self.cliente_combo.setMinimumWidth(220)
        self.empresa_combo = QComboBox()
        self.empresa_combo.setMinimumWidth(200)
        self.btn_nueva = boton("Nueva cotización", "file-plus", "primario")
        self.btn_nueva.clicked.connect(self.nueva_cotizacion)
        top.addWidget(QLabel("Cliente:"))
        top.addWidget(self.cliente_combo)
        top.addWidget(QLabel("Empresa:"))
        top.addWidget(self.empresa_combo)
        top.addStretch()
        top.addWidget(self.btn_nueva)
        lay.addLayout(top)

        self.filtro = FiltroBar(list(db.TRANSICIONES_COTIZACION), lambda: self.refrescar())
        lay.addLayout(self.filtro)

        self.tabla = tabla_estandar(["Número", "Cliente", "Proyecto", "Empresa", "Fecha", "Estado", "Total"], estirar=1)
        self.tabla.cellDoubleClicked.connect(lambda *_: self.editar_items())
        self.tabla.currentCellChanged.connect(lambda *_: self._actualizar_acciones())
        self.tabla.setContextMenuPolicy(Qt.CustomContextMenu)          # clic derecho sobre una cotización
        self.tabla.customContextMenuRequested.connect(self._menu_contextual)
        lay.addWidget(self.tabla, 1)

        acciones = QHBoxLayout()
        self.btn_items = boton("Abrir / Editar", "edit")
        self.btn_items.clicked.connect(self.editar_items)
        acciones.addWidget(self.btn_items)
        acciones.addStretch()
        acciones.addWidget(QLabel("Cambiar estado a:"))
        self.estado_combo = QComboBox()
        self.estado_combo.setMinimumWidth(120)
        acciones.addWidget(self.estado_combo)
        self.btn_estado = boton("Aplicar", "check")
        self.btn_estado.clicked.connect(self.cambiar_estado)
        acciones.addWidget(self.btn_estado)
        self.btn_factura = boton("Generar factura", "receipt")
        self.btn_factura.clicked.connect(self.generar_factura)
        acciones.addWidget(self.btn_factura)
        self.btn_vista = boton("Vista previa", "eye", tooltip="Ver cómo saldrá la cotización antes de exportarla")
        self.btn_vista.clicked.connect(self.vista_previa)
        acciones.addWidget(self.btn_vista)
        self.btn_pdf = boton("Exportar PDF", "download")
        self.btn_pdf.clicked.connect(self.exportar_pdf)
        acciones.addWidget(self.btn_pdf)
        self.btn_word = boton("Exportar Word", "word")
        self.btn_word.clicked.connect(self.exportar_word)
        acciones.addWidget(self.btn_word)
        lay.addLayout(acciones)

        self.refrescar()

    def refrescar(self):
        conn = db.get_connection()
        clientes = conn.execute("SELECT id, nombre FROM clientes ORDER BY nombre").fetchall()
        cliente_actual = self.cliente_combo.currentData()
        self.cliente_combo.clear()
        for c in clientes:
            self.cliente_combo.addItem(c["nombre"], c["id"])
        idx = self.cliente_combo.findData(cliente_actual)
        if idx >= 0:
            self.cliente_combo.setCurrentIndex(idx)

        empresa_actual = self.empresa_combo.currentData() or db.empresa_predeterminada_id(conn)
        self.empresa_combo.clear()
        for e in db.listar_empresas(conn):
            self.empresa_combo.addItem(e["nombre"], e["id"])
        idx = self.empresa_combo.findData(empresa_actual)
        if idx >= 0:
            self.empresa_combo.setCurrentIndex(idx)

        where, params = self.filtro.clausula("c", "estado")
        filas = conn.execute(f"""
            SELECT c.id, c.numero, cl.nombre AS cliente, c.proyecto, e.nombre AS empresa, c.fecha, c.estado, c.total
            FROM cotizaciones c JOIN clientes cl ON cl.id = c.cliente_id
            LEFT JOIN empresas e ON e.id = c.empresa_id
            {where}
            ORDER BY c.id DESC
        """, params).fetchall()
        conn.close()
        sel_id = self._id_seleccionado()
        self.tabla.setRowCount(len(filas))
        for i, fila in enumerate(filas):
            num = QTableWidgetItem(fila["numero"])
            num.setData(Qt.UserRole, fila["id"])
            self.tabla.setItem(i, 0, num)
            self.tabla.setItem(i, 1, QTableWidgetItem(fila["cliente"]))
            self.tabla.setItem(i, 2, QTableWidgetItem(fila["proyecto"] or ""))
            self.tabla.setItem(i, 3, QTableWidgetItem(fila["empresa"] or ""))
            self.tabla.setItem(i, 4, QTableWidgetItem(fila["fecha"]))
            self.tabla.setItem(i, COT_ESTADO, celda_estado(fila["estado"]))
            self.tabla.setItem(i, 6, celda_dinero(fila["total"]))
            if fila["id"] == sel_id:
                self.tabla.setCurrentCell(i, 0)
        self._actualizar_acciones()

    def _id_seleccionado(self):
        fila = self.tabla.currentRow()
        item = self.tabla.item(fila, 0) if fila >= 0 else None
        return item.data(Qt.UserRole) if item else None

    def _estado_actual(self):
        fila = self.tabla.currentRow()
        return self.tabla.item(fila, COT_ESTADO).text() if fila >= 0 else None

    def _actualizar_acciones(self):
        """Llena el combo con los estados a los que se puede pasar desde el actual."""
        self.estado_combo.clear()
        estado = self._estado_actual()
        if estado:
            self.estado_combo.addItems(db.TRANSICIONES_COTIZACION.get(estado, []))
        self.btn_estado.setEnabled(self.estado_combo.count() > 0)
        self.estado_combo.setEnabled(self.estado_combo.count() > 0)
        self.btn_factura.setEnabled(estado == "aprobada")
        self.btn_items.setEnabled(estado is not None)
        self.btn_pdf.setEnabled(estado is not None)
        self.btn_word.setEnabled(estado is not None)
        self.btn_vista.setEnabled(estado is not None)
        self.btn_items.setText("Abrir / Editar" if estado == "borrador" or estado is None else "Ver detalle")

    def cambiar_estado(self):
        if self.estado_combo.currentText():
            self._cambiar_estado_a(self.estado_combo.currentText())

    def _cambiar_estado_a(self, estado):
        sel = self._seleccionada()
        if not sel:
            return
        conn = db.get_connection()
        try:
            db.cambiar_estado_cotizacion(sel[0], estado, conn)
        except ValueError as e:
            QMessageBox.warning(self, "Cambio de estado", str(e))
            return
        finally:
            conn.close()
        self.refrescar()

    # ------------------------------------------------------------------ clic derecho
    def _menu_contextual(self, pos):
        fila = self.tabla.rowAt(pos.y())
        if fila < 0:
            return
        self.tabla.setCurrentCell(fila, 0)
        self._mostrar_menu(self.construir_menu(), self.tabla.viewport().mapToGlobal(pos))

    @staticmethod
    def _mostrar_menu(menu, punto_global):
        menu.exec(punto_global)

    def construir_menu(self) -> QMenu:
        """Menú del clic derecho para la cotización seleccionada (todas las acciones disponibles según su estado)."""
        estado = self._estado_actual()
        menu = QMenu(self)
        icono = lambda nombre, color=estilo.AZUL_OSCURO: iconos.icono(nombre, color, 18)
        menu.addAction(icono("edit"), "Abrir / Editar" if estado == "borrador" else "Ver detalle",
                       lambda *_: self.editar_items())
        menu.addAction(icono("eye"), "Vista previa", lambda *_: self.vista_previa())
        menu.addSeparator()
        siguientes = db.TRANSICIONES_COTIZACION.get(estado, [])
        sub = menu.addMenu(icono("check"), "Cambiar estado a")
        for e in siguientes:
            sub.addAction(e.capitalize(), lambda *_, e=e: self._cambiar_estado_a(e))
        sub.setEnabled(bool(siguientes))
        menu.addAction(icono("receipt"), "Generar factura", lambda *_: self.generar_factura()).setEnabled(
            estado == "aprobada")
        menu.addSeparator()
        menu.addAction(icono("download"), "Exportar PDF", lambda *_: self.exportar_pdf())
        menu.addAction(icono("word"), "Exportar Word", lambda *_: self.exportar_word())
        menu.addSeparator()
        menu.addAction(icono("copy"), "Duplicar cotización", lambda *_: self.duplicar_cotizacion())
        menu.addAction(icono("trash", estilo.ROJO), "Eliminar cotización…", lambda *_: self.eliminar_cotizacion())
        return menu

    def duplicar_cotizacion(self):
        sel = self._seleccionada()
        if not sel:
            return
        conn = db.get_connection()
        try:
            nuevo, numero = db.duplicar_cotizacion(sel[0], conn)
        except ValueError as e:
            QMessageBox.warning(self, "Duplicar cotización", str(e))
            return
        finally:
            conn.close()
        self.refrescar()
        for fila in range(self.tabla.rowCount()):                       # deja seleccionada la copia
            if self.tabla.item(fila, 0).data(Qt.UserRole) == nuevo:
                self.tabla.setCurrentCell(fila, 0)
                break

    def eliminar_cotizacion(self):
        sel = self._seleccionada()
        if not sel:
            return
        r = QMessageBox.question(self, "Eliminar cotización",
                                 f"¿Eliminar la cotización {sel[1]} con todos sus ítems?\nEsta acción no se puede deshacer.")
        if r != QMessageBox.Yes:
            return
        conn = db.get_connection()
        try:
            db.eliminar_cotizacion(sel[0], conn)
        except ValueError as e:
            QMessageBox.warning(self, "Eliminar cotización", str(e))
            return
        finally:
            conn.close()
        self.refrescar()

    def exportar_pdf(self):
        sel = self._seleccionada()
        if sel:
            exportar_pdf(self, pdf.exportar_cotizacion, sel[0], sel[1])

    def exportar_word(self):
        sel = self._seleccionada()
        if sel:
            exportar_word(self, word.exportar_cotizacion, sel[0], sel[1])

    def vista_previa(self):
        sel = self._seleccionada()
        if sel:
            vista_previa(self, "cotizacion", sel[0], sel[1])

    def generar_factura(self):
        sel = self._seleccionada()
        if not sel:
            return
        conn = db.get_connection()
        try:
            numero = db.generar_factura(sel[0], conn)
        except ValueError as e:
            QMessageBox.warning(self, "Generar factura", str(e))
            return
        finally:
            conn.close()
        QMessageBox.information(self, "Factura generada", f"Se creó la factura {numero}.")
        if self.on_factura_generada:
            self.on_factura_generada()

    def _seleccionada(self):
        fila = self.tabla.currentRow()
        if fila < 0:
            QMessageBox.information(self, "Selecciona una cotización", "Selecciona una cotización de la tabla.")
            return None
        item = self.tabla.item(fila, 0)
        return item.data(Qt.UserRole), item.text(), self.tabla.item(fila, COT_ESTADO).text()

    def editar_items(self):
        sel = self._seleccionada()
        if not sel:
            return
        cot_id, numero, estado = sel
        dlg = ItemsDialog(cot_id, numero, editable=(estado == "borrador"), parent=self)
        if dlg.exec():
            self.refrescar()

    def nueva_cotizacion(self):
        cliente_id = self.cliente_combo.currentData()
        if cliente_id is None:
            QMessageBox.warning(self, "Falta cliente", "Agrega un cliente primero en la sección Clientes.")
            return
        conn = db.get_connection()
        db.crear_cotizacion(cliente_id, conn, self.empresa_combo.currentData())
        conn.close()
        self.refrescar()
        self.tabla.setCurrentCell(0, 0)


class NotasDialog(QDialog):
    """Cuadro de texto multilínea con Guardar / Cancelar."""

    def __init__(self, titulo, texto, parent=None, titulo_bloque=None):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.resize(640, 480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        self.titulo_edit = None
        if titulo_bloque is not None:
            fila_t = QHBoxLayout()
            fila_t.addWidget(QLabel("Título del bloque:"))
            self.titulo_edit = QLineEdit(titulo_bloque)
            self.titulo_edit.setPlaceholderText(db.TITULO_NOTAS)
            fila_t.addWidget(self.titulo_edit, 1)
            lay.addLayout(fila_t)
        self.editor = QPlainTextEdit(texto)
        lay.addWidget(self.editor)
        fila = QHBoxLayout()
        fila.addStretch()
        cancelar = boton("Cancelar", "x")
        guardar = boton("Guardar", "save", "primario")
        cancelar.clicked.connect(self.reject)
        guardar.clicked.connect(self.accept)
        fila.addWidget(cancelar)
        fila.addWidget(guardar)
        lay.addLayout(fila)

    def texto(self):
        return self.editor.toPlainText().strip("\n")

    def titulo_bloque(self):
        return self.titulo_edit.text().strip() if self.titulo_edit else ""


class FacturasTab(QWidget):
    COLOR_FILA_VENCIDA = "#FEF2F2"

    def __init__(self):
        super().__init__()
        lay = pagina(self)
        lay.addWidget(encabezado_pagina("Facturas", "Seguimiento de cobros: pendientes, pagadas y vencidas."))
        self.filtro = FiltroBar(["pendiente", "pagada", "vencida"], lambda: self.refrescar())
        lay.addLayout(self.filtro)
        self.tabla = tabla_estandar(
            ["Número", "Cliente", "Empresa", "Fecha", "Estado de pago", "Fecha de pago", "Total"], estirar=1)
        self.tabla.currentCellChanged.connect(lambda *_: self._actualizar_acciones())
        self.tabla.setContextMenuPolicy(Qt.CustomContextMenu)          # clic derecho sobre una factura
        self.tabla.customContextMenuRequested.connect(self._menu_contextual)
        lay.addWidget(self.tabla, 1)

        acciones = QHBoxLayout()
        self.btn_pagada = boton("Marcar como pagada", "check-circle")
        self.btn_vencida = boton("Marcar como vencida", "clock", "peligro")
        self.btn_pagada.clicked.connect(self.marcar_pagada)
        self.btn_vencida.clicked.connect(self.marcar_vencida)
        acciones.addWidget(self.btn_pagada)
        acciones.addWidget(self.btn_vencida)
        acciones.addStretch()
        self.btn_notas = boton("Editar notas", "edit")
        self.btn_notas.clicked.connect(self.editar_notas)
        self.btn_pdf = boton("Exportar PDF", "download")
        self.btn_pdf.clicked.connect(self.exportar_pdf)
        self.btn_word = boton("Exportar Word", "word")
        self.btn_word.clicked.connect(self.exportar_word)
        self.btn_vista = boton("Vista previa", "eye", tooltip="Ver cómo saldrá la factura antes de exportarla")
        self.btn_vista.clicked.connect(self.vista_previa)
        acciones.addWidget(self.btn_notas)
        acciones.addWidget(self.btn_vista)
        acciones.addWidget(self.btn_pdf)
        acciones.addWidget(self.btn_word)
        lay.addLayout(acciones)
        self.refrescar()

    def _actualizar_acciones(self):
        fila = self.tabla.currentRow()
        estado = self.tabla.item(fila, FAC_ESTADO).text() if fila >= 0 else None
        self.btn_pagada.setEnabled(estado in ("pendiente", "vencida"))
        self.btn_vencida.setEnabled(estado == "pendiente")
        self.btn_notas.setEnabled(estado is not None)
        self.btn_pdf.setEnabled(estado is not None)
        self.btn_word.setEnabled(estado is not None)
        self.btn_vista.setEnabled(estado is not None)

    def _id_seleccionado(self):
        fila = self.tabla.currentRow()
        item = self.tabla.item(fila, 0) if fila >= 0 else None
        return item.data(Qt.UserRole) if item else None

    def refrescar(self):
        from PySide6.QtGui import QBrush, QColor
        conn = db.get_connection()
        where, params = self.filtro.clausula("f", "estado_pago")
        filas = conn.execute(f"""
            SELECT f.id, f.numero, cl.nombre AS cliente, e.nombre AS empresa, f.fecha, f.estado_pago,
                   f.fecha_pago, f.total
            FROM facturas f JOIN clientes cl ON cl.id = f.cliente_id
            LEFT JOIN empresas e ON e.id = f.empresa_id
            {where}
            ORDER BY f.id DESC
        """, params).fetchall()
        conn.close()
        sel_id = self._id_seleccionado()
        self.tabla.setRowCount(len(filas))
        for i, fila in enumerate(filas):
            celdas = [QTableWidgetItem(fila["numero"]), QTableWidgetItem(fila["cliente"]),
                      QTableWidgetItem(fila["empresa"] or ""), QTableWidgetItem(fila["fecha"]),
                      celda_estado(fila["estado_pago"]), QTableWidgetItem(fila["fecha_pago"] or ""),
                      celda_dinero(fila["total"])]
            celdas[0].setData(Qt.UserRole, fila["id"])
            for c, it in enumerate(celdas):
                if fila["estado_pago"] == "vencida" and c != FAC_ESTADO:
                    it.setBackground(QBrush(QColor(self.COLOR_FILA_VENCIDA)))  # fila vencida resaltada
                self.tabla.setItem(i, c, it)
            if fila["id"] == sel_id:
                self.tabla.setCurrentCell(i, 0)
        self._actualizar_acciones()

    def _menu_contextual(self, pos):
        fila = self.tabla.rowAt(pos.y())
        if fila < 0:
            return
        self.tabla.setCurrentCell(fila, 0)
        self._mostrar_menu(self.construir_menu(), self.tabla.viewport().mapToGlobal(pos))

    @staticmethod
    def _mostrar_menu(menu, punto_global):
        menu.exec(punto_global)

    def construir_menu(self) -> QMenu:
        """Menú del clic derecho para la factura seleccionada."""
        fila = self.tabla.currentRow()
        estado = self.tabla.item(fila, FAC_ESTADO).text() if fila >= 0 else None
        menu = QMenu(self)
        icono = lambda nombre, color=estilo.AZUL_OSCURO: iconos.icono(nombre, color, 18)
        menu.addAction(icono("eye"), "Vista previa", lambda *_: self.vista_previa())
        menu.addSeparator()
        menu.addAction(icono("check-circle"), "Marcar como pagada…", lambda *_: self.marcar_pagada()).setEnabled(
            estado in ("pendiente", "vencida"))
        menu.addAction(icono("clock", estilo.ROJO), "Marcar como vencida", lambda *_: self.marcar_vencida()).setEnabled(
            estado == "pendiente")
        menu.addAction(icono("edit"), "Editar notas", lambda *_: self.editar_notas())
        menu.addSeparator()
        menu.addAction(icono("download"), "Exportar PDF", lambda *_: self.exportar_pdf())
        menu.addAction(icono("word"), "Exportar Word", lambda *_: self.exportar_word())
        return menu

    def _aplicar(self, funcion, *args):
        conn = db.get_connection()
        try:
            funcion(*args, conn)
        except ValueError as e:
            QMessageBox.warning(self, "Factura", str(e))
            return
        finally:
            conn.close()
        self.refrescar()

    def marcar_pagada(self):
        fid = self._id_seleccionado()
        if fid is None:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Fecha de pago")
        form = QFormLayout(dlg)
        form.setContentsMargins(18, 16, 18, 14)
        fecha = QDateEdit(QDate.currentDate())
        fecha.setCalendarPopup(True)
        fecha.setDisplayFormat("yyyy-MM-dd")
        form.addRow("Fecha de pago:", fecha)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec():
            self._aplicar(db.marcar_factura_pagada, fid, fecha.date().toString("yyyy-MM-dd"))

    def editar_notas(self):
        fid = self._id_seleccionado()
        if fid is None:
            QMessageBox.information(self, "Selecciona una factura", "Selecciona una factura de la tabla.")
            return
        conn = db.get_connection()
        dlg = NotasDialog("Notas / Términos y condiciones de la factura", db.obtener_notas_factura(fid, conn), self,
                          db.obtener_titulo_notas("facturas", fid, conn))
        conn.close()
        if dlg.exec():
            conn = db.get_connection()
            db.guardar_notas_factura(fid, dlg.texto(), conn)
            db.guardar_titulo_notas("facturas", fid, dlg.titulo_bloque(), conn)
            conn.close()

    def exportar_pdf(self):
        fid = self._id_seleccionado()
        if fid is None:
            QMessageBox.information(self, "Selecciona una factura", "Selecciona una factura de la tabla.")
            return
        exportar_pdf(self, pdf.exportar_factura, fid, self.tabla.item(self.tabla.currentRow(), 0).text())

    def vista_previa(self):
        fid = self._id_seleccionado()
        if fid is None:
            QMessageBox.information(self, "Selecciona una factura", "Selecciona una factura de la tabla.")
            return
        vista_previa(self, "factura", fid, self.tabla.item(self.tabla.currentRow(), 0).text())

    def exportar_word(self):
        fid = self._id_seleccionado()
        if fid is None:
            QMessageBox.information(self, "Selecciona una factura", "Selecciona una factura de la tabla.")
            return
        exportar_word(self, word.exportar_factura, fid, self.tabla.item(self.tabla.currentRow(), 0).text())

    def marcar_vencida(self):
        fid = self._id_seleccionado()
        if fid is not None:
            self._aplicar(db.marcar_factura_vencida, fid)


class ConfiguracionTab(QWidget):
    def __init__(self):
        super().__init__()
        lay = pagina(self)
        lay.addWidget(encabezado_pagina("Configuración", "Opciones generales y plantilla de notas."))

        card = tarjeta()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 14)
        self.chk_estado = QCheckBox("Mostrar el estado de la cotización / factura en el PDF")
        cl.addWidget(self.chk_estado)
        sub = QLabel("Coeficientes de venta por defecto de los análisis de precio unitario "
                     "(cada cotización nueva parte de estos valores):")
        sub.setObjectName("subtitulo")
        sub.setWordWrap(True)
        cl.addWidget(sub)
        form = QFormLayout()
        self.spins_coef = {}
        for cat, nombre in calculo.CATEGORIAS.items():
            sp = QDoubleSpinBox()
            sp.setRange(0, 1000)
            sp.setDecimals(2)
            sp.setSuffix(" %")
            self.spins_coef[cat] = sp
            form.addRow(f"{nombre}:", sp)
        cl.addLayout(form)
        fila = QHBoxLayout()
        fila.addStretch()
        btn_guardar = boton("Guardar configuración", "save", "primario")
        btn_guardar.clicked.connect(self.guardar_opciones)
        fila.addWidget(btn_guardar)
        cl.addLayout(fila)
        lay.addWidget(card)

        sec = QLabel("Plantilla de notas por defecto")
        sec.setObjectName("seccion")
        lay.addWidget(sec)
        sub = QLabel("Se inserta con el botón «Insertar plantilla» al editar una cotización.")
        sub.setObjectName("subtitulo")
        lay.addWidget(sub)
        self.plantilla_edit = QPlainTextEdit()
        lay.addWidget(self.plantilla_edit, 1)
        fila = QHBoxLayout()
        self.btn_plantilla = boton("Guardar plantilla", "save", "primario")
        self.btn_plantilla.clicked.connect(self.guardar_plantilla)
        self.btn_restaurar = boton("Restaurar plantilla original", "refresh")
        self.btn_restaurar.clicked.connect(self.restaurar_plantilla)
        fila.addWidget(self.btn_plantilla)
        fila.addWidget(self.btn_restaurar)
        fila.addStretch()
        lay.addLayout(fila)
        self.refrescar()

    def refrescar(self):
        conn = db.get_connection()
        self.chk_estado.setChecked(db.mostrar_estado_pdf(conn))
        defecto = db.coef_apu_defecto(conn)
        for cat, sp in self.spins_coef.items():
            sp.setValue(defecto.coef(cat) * 100)
        self.plantilla_edit.setPlainText(db.obtener_plantilla_notas(conn))
        conn.close()

    def guardar_opciones(self):
        conn = db.get_connection()
        db.guardar_config("mostrar_estado_pdf", "1" if self.chk_estado.isChecked() else "0", conn)
        db.guardar_coef_apu_defecto({c: sp.value() for c, sp in self.spins_coef.items()}, conn)
        conn.close()
        QMessageBox.information(self, "Configuración", "Configuración guardada.")

    def guardar_plantilla(self):
        conn = db.get_connection()
        db.guardar_plantilla_notas(self.plantilla_edit.toPlainText(), conn)
        conn.close()
        QMessageBox.information(self, "Plantilla", "Plantilla guardada.")

    def restaurar_plantilla(self):
        if QMessageBox.question(self, "Restaurar plantilla",
                                "¿Restaurar la plantilla original? Se perderán tus cambios a la plantilla.") \
                != QMessageBox.Yes:
            return
        conn = db.get_connection()
        self.plantilla_edit.setPlainText(db.restaurar_plantilla_notas(conn))
        conn.close()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QuoteTrack — Cotizaciones y Facturas")
        self.resize(1180, 740)
        self.setMinimumSize(980, 620)

        self.facturas_tab = FacturasTab()
        self.cotizaciones_tab = CotizacionesTab(on_factura_generada=self.facturas_tab.refrescar)
        self.biblioteca_tab = BibliotecaTab()
        self.clientes_tab = ClientesTab()
        self.empresas_tab = EmpresasTab()
        self.configuracion_tab = ConfiguracionTab()
        secciones = [
            ("Cotizaciones", "file", self.cotizaciones_tab),
            ("Facturas", "receipt", self.facturas_tab),
            ("Biblioteca", "book", self.biblioteca_tab),
            ("Clientes", "users", self.clientes_tab),
            ("Empresas", "building", self.empresas_tab),
            ("Configuración", "sliders", self.configuracion_tab),
        ]

        central = QWidget()
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        lateral = QWidget()
        lateral.setObjectName("barraLateral")
        lateral.setFixedWidth(230)
        lv = QVBoxLayout(lateral)
        lv.setContentsMargins(0, 18, 0, 14)
        marca = QHBoxLayout()
        marca.setContentsMargins(18, 0, 12, 10)
        logo = QLabel()
        logo.setPixmap(QPixmap(str(ruta_recurso("assets/icon.png"))).scaled(
            44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        marca.addWidget(logo)
        textos = QVBoxLayout()
        textos.setSpacing(0)
        n = QLabel("QuoteTrack")
        n.setObjectName("marca")
        s = QLabel("Cotizaciones y facturas")
        s.setObjectName("marcaSub")
        textos.addWidget(n)
        textos.addWidget(s)
        marca.addLayout(textos)
        marca.addStretch()
        lv.addLayout(marca)

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setIconSize(QSize(20, 20))
        self.nav.setFocusPolicy(Qt.NoFocus)
        self.pila = QStackedWidget()
        for nombre, icono, widget in secciones:
            self.nav.addItem(QListWidgetItem(iconos.icono(icono, "#C7D4F2", 20, color_activo="#FFFFFF"), nombre))
            self.pila.addWidget(widget)
        self.nav.currentRowChanged.connect(self._cambiar_seccion)
        lv.addWidget(self.nav, 1)
        pie = QLabel("v1.2")
        pie.setObjectName("marcaSub")
        pie.setContentsMargins(20, 0, 0, 0)
        lv.addWidget(pie)

        h.addWidget(lateral)
        h.addWidget(self.pila, 1)
        self.setCentralWidget(central)
        self.nav.setCurrentRow(0)

    def _cambiar_seccion(self, fila):
        if fila < 0:
            return
        self.pila.setCurrentIndex(fila)
        widget = self.pila.widget(fila)
        if hasattr(widget, "refrescar"):
            widget.refrescar()


def main():
    db.init_db()
    conn = db.get_connection()
    base_cgr.precargar(conn)        # la base de costos de la Contraloría queda cargada como una biblioteca
    conn.close()
    app = QApplication(sys.argv)
    estilo.aplicar(app)
    app.setWindowIcon(QIcon(str(ruta_recurso("assets/icon.png"))))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
