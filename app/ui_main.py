"""
Ventana principal de QuoteTrack: pestañas de Clientes, Cotizaciones y Facturas.
Esto es un scaffold funcional mínimo — pensado para que Claude Code lo siga
desarrollando (edición de items, exportar PDF, conversión cotización -> factura, etc).
"""
import sys
from datetime import date

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QPushButton, QLineEdit, QLabel, QFormLayout,
    QComboBox, QMessageBox, QDialog, QDialogButtonBox, QHeaderView,
    QDateEdit, QFileDialog
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QColor

from app import db, pdf


def exportar_pdf(parent, funcion, registro_id, numero):
    """Pide la ruta de destino y exporta con `funcion` (pdf.exportar_*)."""
    ruta, _ = QFileDialog.getSaveFileName(parent, "Exportar PDF", f"{numero}.pdf", "PDF (*.pdf)")
    if not ruta:
        return
    try:
        funcion(registro_id, ruta)
    except (ValueError, OSError) as e:
        QMessageBox.warning(parent, "Exportar PDF", f"No se pudo exportar el PDF:\n{e}")
        return
    QMessageBox.information(parent, "Exportar PDF", f"PDF guardado en:\n{ruta}")


class FiltroBar(QHBoxLayout):
    """Barra de búsqueda (cliente o número) + filtro por estado; llama a `al_cambiar` al modificarse."""

    def __init__(self, estados, al_cambiar):
        super().__init__()
        self.busqueda = QLineEdit()
        self.busqueda.setPlaceholderText("Buscar por cliente o número…")
        self.busqueda.setClearButtonEnabled(True)
        self.estado = QComboBox()
        self.estado.addItem("Todos los estados", None)
        for e in estados:
            self.estado.addItem(e, e)
        self.addWidget(self.busqueda, 1)
        self.addWidget(QLabel("Estado:"))
        self.addWidget(self.estado)
        self.busqueda.textChanged.connect(lambda *_: al_cambiar())
        self.estado.currentIndexChanged.connect(lambda *_: al_cambiar())

    def clausula(self, alias, columna_estado):
        """Devuelve (SQL 'WHERE ...', parámetros); `alias` es el de la tabla principal."""
        condiciones, params = [], []
        texto = self.busqueda.text().strip()
        if texto:
            condiciones.append(f"(cl.nombre LIKE ? OR {alias}.numero LIKE ?)")
            params += [f"%{texto}%"] * 2
        if self.estado.currentData():
            condiciones.append(f"{alias}.{columna_estado} = ?")
            params.append(self.estado.currentData())
        return ("WHERE " + " AND ".join(condiciones) if condiciones else ""), params


class ClientesTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.nombre_edit = QLineEdit()
        self.id_edit = QLineEdit()
        self.contacto_edit = QLineEdit()
        form.addRow("Nombre:", self.nombre_edit)
        form.addRow("Identificación (RUC/Cédula):", self.id_edit)
        form.addRow("Contacto:", self.contacto_edit)
        layout.addLayout(form)

        btn_add = QPushButton("Agregar cliente")
        btn_add.clicked.connect(self.agregar_cliente)
        layout.addWidget(btn_add)

        self.tabla = QTableWidget(0, 3)
        self.tabla.setHorizontalHeaderLabels(["ID", "Nombre", "Identificación"])
        layout.addWidget(self.tabla)

        self.refrescar()

    def agregar_cliente(self):
        nombre = self.nombre_edit.text().strip()
        if not nombre:
            QMessageBox.warning(self, "Falta nombre", "El nombre del cliente es obligatorio.")
            return
        conn = db.get_connection()
        conn.execute(
            "INSERT INTO clientes (nombre, identificacion, contacto) VALUES (?, ?, ?)",
            (nombre, self.id_edit.text().strip(), self.contacto_edit.text().strip()),
        )
        conn.commit()
        conn.close()
        self.nombre_edit.clear()
        self.id_edit.clear()
        self.contacto_edit.clear()
        self.refrescar()

    def refrescar(self):
        conn = db.get_connection()
        filas = conn.execute("SELECT id, nombre, identificacion FROM clientes ORDER BY nombre").fetchall()
        conn.close()
        self.tabla.setRowCount(len(filas))
        for i, fila in enumerate(filas):
            self.tabla.setItem(i, 0, QTableWidgetItem(str(fila["id"])))
            self.tabla.setItem(i, 1, QTableWidgetItem(fila["nombre"]))
            self.tabla.setItem(i, 2, QTableWidgetItem(fila["identificacion"] or ""))


class ItemsDialog(QDialog):
    """Editor de líneas de una cotización: tabla editable con totales automáticos."""
    COLS = ["Descripción", "Cantidad", "Precio unitario", "Importe"]

    def __init__(self, cotizacion_id, numero, editable, parent=None):
        super().__init__(parent)
        self.cotizacion_id = cotizacion_id
        self.editable = editable
        self._cargando = False
        self.setWindowTitle(f"Items de {numero}")
        self.resize(700, 450)
        layout = QVBoxLayout(self)

        self.tabla = QTableWidget(0, 4)
        self.tabla.setHorizontalHeaderLabels(self.COLS)
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tabla.itemChanged.connect(self._al_editar)
        layout.addWidget(self.tabla)

        botones = QHBoxLayout()
        self.btn_agregar = QPushButton("Agregar línea")
        self.btn_quitar = QPushButton("Quitar línea")
        self.btn_agregar.clicked.connect(lambda: self.agregar_fila())
        self.btn_quitar.clicked.connect(self.quitar_fila)
        botones.addWidget(self.btn_agregar)
        botones.addWidget(self.btn_quitar)
        botones.addStretch()
        layout.addLayout(botones)

        self.lbl_totales = QLabel()
        self.lbl_totales.setAlignment(Qt.AlignRight)
        layout.addWidget(self.lbl_totales)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("Guardar")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self.guardar)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

        if not editable:
            self.btn_agregar.setEnabled(False)
            self.btn_quitar.setEnabled(False)
            self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
            bb.button(QDialogButtonBox.Save).setEnabled(False)
            self.setWindowTitle(f"Items de {numero} (solo lectura)")

        conn = db.get_connection()
        items = db.obtener_items(cotizacion_id, conn)
        conn.close()
        for desc, cant, precio in items:
            self.agregar_fila(desc, cant, precio)
        if editable and not items:
            self.agregar_fila()
        self._actualizar_totales()

    def agregar_fila(self, desc="", cant=1.0, precio=0.0):
        self._cargando = True
        r = self.tabla.rowCount()
        self.tabla.insertRow(r)
        self.tabla.setItem(r, 0, QTableWidgetItem(desc))
        self.tabla.setItem(r, 1, QTableWidgetItem(f"{cant:g}"))
        self.tabla.setItem(r, 2, QTableWidgetItem(f"{precio:.2f}"))
        importe = QTableWidgetItem(f"{cant * precio:.2f}")
        importe.setFlags(importe.flags() & ~Qt.ItemIsEditable)
        self.tabla.setItem(r, 3, importe)
        self._cargando = False
        self._actualizar_totales()

    def quitar_fila(self):
        filas = sorted({i.row() for i in self.tabla.selectedIndexes()}, reverse=True)
        if not filas and self.tabla.rowCount():
            filas = [self.tabla.rowCount() - 1]
        for r in filas:
            self.tabla.removeRow(r)
        self._actualizar_totales()

    @staticmethod
    def _numero(item, defecto=0.0):
        try:
            return float(item.text().replace(",", ".")) if item else defecto
        except ValueError:
            return None

    def _al_editar(self, item):
        if self._cargando or item.column() == 3:
            return
        self._actualizar_totales()

    def _leer_items(self):
        """Devuelve (items, error). Ignora filas totalmente vacías."""
        items = []
        for r in range(self.tabla.rowCount()):
            desc_it = self.tabla.item(r, 0)
            desc = desc_it.text().strip() if desc_it else ""
            cant = self._numero(self.tabla.item(r, 1))
            precio = self._numero(self.tabla.item(r, 2))
            if cant is None or precio is None:
                return None, f"Fila {r + 1}: cantidad o precio no es un número válido."
            if not desc and cant == 0 and precio == 0:
                continue
            if not desc:
                return None, f"Fila {r + 1}: falta la descripción."
            items.append((desc, cant, precio))
        return items, None

    def _actualizar_totales(self):
        self._cargando = True
        validos = []
        for r in range(self.tabla.rowCount()):
            cant = self._numero(self.tabla.item(r, 1))
            precio = self._numero(self.tabla.item(r, 2))
            importe = self.tabla.item(r, 3)
            if cant is None or precio is None:
                if importe:
                    importe.setText("—")
                continue
            if importe:
                importe.setText(f"{cant * precio:.2f}")
            validos.append(("", cant, precio))
        self._cargando = False
        sub, itbms, total = db.calcular_totales(validos)
        self.lbl_totales.setText(
            f"Subtotal: {sub:,.2f}    ITBMS ({db.ITBMS_RATE:.0%}): {itbms:,.2f}    "
            f"<b>Total: {total:,.2f}</b>"
        )

    def guardar(self):
        items, error = self._leer_items()
        if error:
            QMessageBox.warning(self, "Datos inválidos", error)
            return
        conn = db.get_connection()
        db.guardar_items(self.cotizacion_id, items, conn)
        conn.close()
        self.accept()


class CotizacionesTab(QWidget):
    def __init__(self, on_factura_generada=None):
        super().__init__()
        self.on_factura_generada = on_factura_generada
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.cliente_combo = QComboBox()
        btn_nueva = QPushButton("Nueva cotización")
        btn_nueva.clicked.connect(self.nueva_cotizacion)
        top.addWidget(QLabel("Cliente:"))
        top.addWidget(self.cliente_combo)
        top.addWidget(btn_nueva)
        top.addStretch()
        layout.addLayout(top)

        self.filtro = FiltroBar(list(db.TRANSICIONES_COTIZACION), lambda: self.refrescar())
        layout.addLayout(self.filtro)

        self.tabla = QTableWidget(0, 5)
        self.tabla.setHorizontalHeaderLabels(["Número", "Cliente", "Fecha", "Estado", "Total"])
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla.setSelectionMode(QTableWidget.SingleSelection)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.cellDoubleClicked.connect(lambda *_: self.editar_items())
        self.tabla.currentCellChanged.connect(lambda *_: self._actualizar_acciones())
        layout.addWidget(self.tabla)

        acciones = QHBoxLayout()
        btn_items = QPushButton("Editar items")
        btn_items.clicked.connect(self.editar_items)
        acciones.addWidget(btn_items)
        acciones.addStretch()
        acciones.addWidget(QLabel("Cambiar estado a:"))
        self.estado_combo = QComboBox()
        acciones.addWidget(self.estado_combo)
        self.btn_estado = QPushButton("Aplicar")
        self.btn_estado.clicked.connect(self.cambiar_estado)
        acciones.addWidget(self.btn_estado)
        self.btn_factura = QPushButton("Generar factura")
        self.btn_factura.clicked.connect(self.generar_factura)
        acciones.addWidget(self.btn_factura)
        btn_pdf = QPushButton("Exportar PDF")
        btn_pdf.clicked.connect(self.exportar_pdf)
        acciones.addWidget(btn_pdf)
        layout.addLayout(acciones)

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

        where, params = self.filtro.clausula("c", "estado")
        filas = conn.execute(f"""
            SELECT c.id, c.numero, cl.nombre AS cliente, c.fecha, c.estado, c.total
            FROM cotizaciones c JOIN clientes cl ON cl.id = c.cliente_id
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
            self.tabla.setItem(i, 2, QTableWidgetItem(fila["fecha"]))
            self.tabla.setItem(i, 3, QTableWidgetItem(fila["estado"]))
            self.tabla.setItem(i, 4, QTableWidgetItem(f"{fila['total']:.2f}"))
            if fila["id"] == sel_id:
                self.tabla.setCurrentCell(i, 0)
        self._actualizar_acciones()

    def _id_seleccionado(self):
        fila = self.tabla.currentRow()
        item = self.tabla.item(fila, 0) if fila >= 0 else None
        return item.data(Qt.UserRole) if item else None

    def _actualizar_acciones(self):
        """Llena el combo con los estados a los que se puede pasar desde el actual."""
        self.estado_combo.clear()
        fila = self.tabla.currentRow()
        if fila >= 0:
            self.estado_combo.addItems(db.TRANSICIONES_COTIZACION.get(self.tabla.item(fila, 3).text(), []))
        self.btn_estado.setEnabled(self.estado_combo.count() > 0)
        self.btn_factura.setEnabled(fila >= 0 and self.tabla.item(fila, 3).text() == "aprobada")

    def cambiar_estado(self):
        sel = self._seleccionada()
        if not sel or not self.estado_combo.currentText():
            return
        conn = db.get_connection()
        try:
            db.cambiar_estado_cotizacion(sel[0], self.estado_combo.currentText(), conn)
        except ValueError as e:
            QMessageBox.warning(self, "Cambio de estado", str(e))
            return
        finally:
            conn.close()
        self.refrescar()

    def exportar_pdf(self):
        sel = self._seleccionada()
        if sel:
            exportar_pdf(self, pdf.exportar_cotizacion, sel[0], sel[1])

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
        return item.data(Qt.UserRole), item.text(), self.tabla.item(fila, 3).text()

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
            QMessageBox.warning(self, "Falta cliente", "Agrega un cliente primero en la pestaña Clientes.")
            return
        conn = db.get_connection()
        numero = db.next_numero("COT", "cotizaciones", conn)
        conn.execute(
            "INSERT INTO cotizaciones (numero, cliente_id, fecha, estado) VALUES (?, ?, ?, 'borrador')",
            (numero, cliente_id, date.today().isoformat()),
        )
        conn.commit()
        conn.close()
        self.refrescar()


class FacturasTab(QWidget):
    COLOR_VENCIDA = QColor(255, 205, 205)
    COLOR_PAGADA = QColor(215, 245, 215)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        self.filtro = FiltroBar(["pendiente", "pagada", "vencida"], lambda: self.refrescar())
        layout.addLayout(self.filtro)
        self.tabla = QTableWidget(0, 6)
        self.tabla.setHorizontalHeaderLabels(
            ["Número", "Cliente", "Fecha", "Estado de pago", "Fecha de pago", "Total"])
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla.setSelectionMode(QTableWidget.SingleSelection)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.tabla)

        acciones = QHBoxLayout()
        self.btn_pagada = QPushButton("Marcar como pagada")
        self.btn_vencida = QPushButton("Marcar como vencida")
        self.btn_pagada.clicked.connect(self.marcar_pagada)
        self.btn_vencida.clicked.connect(self.marcar_vencida)
        acciones.addWidget(self.btn_pagada)
        acciones.addWidget(self.btn_vencida)
        btn_pdf = QPushButton("Exportar PDF")
        btn_pdf.clicked.connect(self.exportar_pdf)
        acciones.addWidget(btn_pdf)
        acciones.addStretch()
        layout.addLayout(acciones)
        self.tabla.currentCellChanged.connect(lambda *_: self._actualizar_acciones())
        self.refrescar()

    def _actualizar_acciones(self):
        fila = self.tabla.currentRow()
        estado = self.tabla.item(fila, 3).text() if fila >= 0 else None
        self.btn_pagada.setEnabled(estado in ("pendiente", "vencida"))
        self.btn_vencida.setEnabled(estado == "pendiente")

    def _id_seleccionado(self):
        fila = self.tabla.currentRow()
        item = self.tabla.item(fila, 0) if fila >= 0 else None
        return item.data(Qt.UserRole) if item else None

    def refrescar(self):
        conn = db.get_connection()
        where, params = self.filtro.clausula("f", "estado_pago")
        filas = conn.execute(f"""
            SELECT f.id, f.numero, cl.nombre AS cliente, f.fecha, f.estado_pago, f.fecha_pago, f.total
            FROM facturas f JOIN clientes cl ON cl.id = f.cliente_id
            {where}
            ORDER BY f.id DESC
        """, params).fetchall()
        conn.close()
        sel_id = self._id_seleccionado()
        self.tabla.setRowCount(len(filas))
        for i, fila in enumerate(filas):
            valores = [fila["numero"], fila["cliente"], fila["fecha"], fila["estado_pago"],
                       fila["fecha_pago"] or "", f"{fila['total']:.2f}"]
            color = {"vencida": self.COLOR_VENCIDA, "pagada": self.COLOR_PAGADA}.get(fila["estado_pago"])
            for c, v in enumerate(valores):
                it = QTableWidgetItem(v)
                if c == 0:
                    it.setData(Qt.UserRole, fila["id"])
                if color:
                    it.setBackground(color)
                self.tabla.setItem(i, c, it)
            if fila["id"] == sel_id:
                self.tabla.setCurrentCell(i, 0)
        self._actualizar_acciones()

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

    def exportar_pdf(self):
        fid = self._id_seleccionado()
        if fid is None:
            QMessageBox.information(self, "Selecciona una factura", "Selecciona una factura de la tabla.")
            return
        exportar_pdf(self, pdf.exportar_factura, fid, self.tabla.item(self.tabla.currentRow(), 0).text())

    def marcar_vencida(self):
        fid = self._id_seleccionado()
        if fid is not None:
            self._aplicar(db.marcar_factura_vencida, fid)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QuoteTrack — Cotizaciones y Facturas")
        self.resize(900, 600)

        self.clientes_tab = ClientesTab()
        self.facturas_tab = FacturasTab()
        self.cotizaciones_tab = CotizacionesTab(on_factura_generada=self.facturas_tab.refrescar)
        tabs = QTabWidget()
        tabs.addTab(self.clientes_tab, "Clientes")
        tabs.addTab(self.cotizaciones_tab, "Cotizaciones")
        tabs.addTab(self.facturas_tab, "Facturas")
        tabs.currentChanged.connect(lambda i: tabs.widget(i).refrescar())
        self.setCentralWidget(tabs)


def main():
    db.init_db()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
