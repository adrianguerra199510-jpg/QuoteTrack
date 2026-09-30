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
    QComboBox, QMessageBox
)

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
        layout.addLayout(top)

        self.tabla = QTableWidget(0, 5)
        self.tabla.setHorizontalHeaderLabels(["Número", "Cliente", "Fecha", "Estado", "Total"])
        layout.addWidget(self.tabla)

        self.refrescar()

    def refrescar(self):
        conn = db.get_connection()
        clientes = conn.execute("SELECT id, nombre FROM clientes ORDER BY nombre").fetchall()
        self.cliente_combo.clear()
        for c in clientes:
            self.cliente_combo.addItem(c["nombre"], c["id"])

        filas = conn.execute("""
            SELECT c.numero, cl.nombre AS cliente, c.fecha, c.estado, c.total
            FROM cotizaciones c JOIN clientes cl ON cl.id = c.cliente_id
            ORDER BY c.id DESC
        """).fetchall()
        conn.close()
        self.tabla.setRowCount(len(filas))
        for i, fila in enumerate(filas):
            self.tabla.setItem(i, 0, QTableWidgetItem(fila["numero"]))
            self.tabla.setItem(i, 1, QTableWidgetItem(fila["cliente"]))
            self.tabla.setItem(i, 2, QTableWidgetItem(fila["fecha"]))
            self.tabla.setItem(i, 3, QTableWidgetItem(fila["estado"]))
            self.tabla.setItem(i, 4, QTableWidgetItem(f"{fila['total']:.2f}"))

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
