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
    QComboBox, QMessageBox, QDialog, QDialogButtonBox, QHeaderView
)
from PySide6.QtCore import Qt

from app import db


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
    def __init__(self):
        super().__init__()
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
        layout.addLayout(acciones)

        self.refrescar()

    def refrescar(self):
        conn = db.get_connection()
        clientes = conn.execute("SELECT id, nombre FROM clientes ORDER BY nombre").fetchall()
        self.cliente_combo.clear()
        for c in clientes:
            self.cliente_combo.addItem(c["nombre"], c["id"])

        filas = conn.execute("""
            SELECT c.id, c.numero, cl.nombre AS cliente, c.fecha, c.estado, c.total
            FROM cotizaciones c JOIN clientes cl ON cl.id = c.cliente_id
            ORDER BY c.id DESC
        """).fetchall()
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
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Pendiente: generar factura a partir de una cotización aprobada.\n"
            "(placeholder — siguiente paso de desarrollo)"
        ))
        self.tabla = QTableWidget(0, 4)
        self.tabla.setHorizontalHeaderLabels(["Número", "Cliente", "Estado de pago", "Total"])
        layout.addWidget(self.tabla)
        self.refrescar()

    def refrescar(self):
        conn = db.get_connection()
        filas = conn.execute("""
            SELECT f.numero, cl.nombre AS cliente, f.estado_pago, f.total
            FROM facturas f JOIN clientes cl ON cl.id = f.cliente_id
            ORDER BY f.id DESC
        """).fetchall()
        conn.close()
        self.tabla.setRowCount(len(filas))
        for i, fila in enumerate(filas):
            self.tabla.setItem(i, 0, QTableWidgetItem(fila["numero"]))
            self.tabla.setItem(i, 1, QTableWidgetItem(fila["cliente"]))
            self.tabla.setItem(i, 2, QTableWidgetItem(fila["estado_pago"]))
            self.tabla.setItem(i, 3, QTableWidgetItem(f"{fila['total']:.2f}"))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QuoteTrack — Cotizaciones y Facturas")
        self.resize(900, 600)

        tabs = QTabWidget()
        tabs.addTab(ClientesTab(), "Clientes")
        tabs.addTab(CotizacionesTab(), "Cotizaciones")
        tabs.addTab(FacturasTab(), "Facturas")
        self.setCentralWidget(tabs)


def main():
    db.init_db()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
