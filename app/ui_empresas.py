"""Gestión de empresas (varias razones sociales que pueden emitir cotizaciones y facturas)."""
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from app import db, estilo, iconos
from app.ui_comun import boton, encabezado_pagina, pagina, tabla_estandar


def preparar_logo(ruta: str, max_ancho: int = 700, max_alto: int = 350) -> bytes:
    """Lee una imagen, la reduce si es muy grande y la devuelve como PNG. Lanza ValueError si no es válida."""
    img = QImage(ruta)
    if img.isNull():
        raise ValueError("No se pudo leer la imagen. Usa un archivo PNG, JPG, BMP o SVG convertido a imagen.")
    if img.width() > max_ancho or img.height() > max_alto:
        img = img.scaled(max_ancho, max_alto, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    datos = QByteArray()
    buf = QBuffer(datos)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(datos)


class EmpresaDialog(QDialog):
    def __init__(self, empresa=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editar empresa" if empresa else "Nueva empresa")
        self.resize(520, 560)
        self.logo = empresa["logo"] if empresa else None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(12)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.nombre = QLineEdit(empresa["nombre"] if empresa else "")
        self.subtitulo = QLineEdit(empresa["subtitulo"] if empresa else "")
        self.ruc = QLineEdit(empresa["ruc"] if empresa else "")
        self.direccion = QLineEdit(empresa["direccion"] if empresa else "")
        self.telefono = QLineEdit(empresa["telefono"] if empresa else "")
        self.correo = QLineEdit(empresa["correo"] if empresa else "")
        self.itbms = QDoubleSpinBox()
        self.itbms.setRange(0, 100)
        self.itbms.setDecimals(2)
        self.itbms.setSuffix(" %")
        self.itbms.setValue(empresa["itbms_tasa"] if empresa else 7)
        self.itbms.setToolTip("0 % = exenta de ITBMS (p. ej. servicios profesionales)")
        form.addRow("Nombre *:", self.nombre)
        form.addRow("Subtítulo / giro:", self.subtitulo)
        form.addRow("RUC:", self.ruc)
        form.addRow("Dirección:", self.direccion)
        form.addRow("Teléfono:", self.telefono)
        form.addRow("Correo:", self.correo)
        form.addRow("ITBMS de esta empresa:", self.itbms)
        lay.addLayout(form)

        lay.addWidget(QLabel("Logo (aparece en el encabezado de los PDF)"))
        fila = QHBoxLayout()
        self.vista = QLabel("Sin logo")
        self.vista.setAlignment(Qt.AlignCenter)
        self.vista.setFixedSize(220, 90)
        self.vista.setStyleSheet(f"background: white; border: 1px dashed {estilo.BORDE}; border-radius: 8px;"
                                 f"color: {estilo.APAGADO};")
        fila.addWidget(self.vista)
        col = QVBoxLayout()
        self.btn_logo = boton("Elegir logo…", "image")
        self.btn_quitar_logo = boton("Quitar logo", "trash", "peligro")
        self.btn_logo.clicked.connect(self.elegir_logo)
        self.btn_quitar_logo.clicked.connect(self.quitar_logo)
        col.addWidget(self.btn_logo)
        col.addWidget(self.btn_quitar_logo)
        col.addStretch()
        fila.addLayout(col)
        fila.addStretch()
        lay.addLayout(fila)
        lay.addStretch()

        pie = QHBoxLayout()
        pie.addStretch()
        cancelar = boton("Cancelar", "x")
        guardar = boton("Guardar", "save", "primario")
        cancelar.clicked.connect(self.reject)
        guardar.clicked.connect(self._aceptar)
        pie.addWidget(cancelar)
        pie.addWidget(guardar)
        lay.addLayout(pie)
        self._mostrar_logo()

    def _mostrar_logo(self):
        if self.logo:
            pm = QPixmap()
            pm.loadFromData(self.logo)
            self.vista.setPixmap(pm.scaled(self.vista.size() - self.vista.size() * 0.1, Qt.KeepAspectRatio,
                                           Qt.SmoothTransformation))
        else:
            self.vista.setPixmap(QPixmap())
            self.vista.setText("Sin logo")
        self.btn_quitar_logo.setEnabled(bool(self.logo))

    def elegir_logo(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Elegir logo", "", "Imágenes (*.png *.jpg *.jpeg *.bmp *.gif)")
        if not ruta:
            return
        try:
            self.logo = preparar_logo(ruta)
        except ValueError as e:
            QMessageBox.warning(self, "Logo", str(e))
            return
        self._mostrar_logo()

    def quitar_logo(self):
        self.logo = None
        self._mostrar_logo()

    def _aceptar(self):
        if not self.nombre.text().strip():
            QMessageBox.warning(self, "Empresa", "El nombre de la empresa es obligatorio.")
            return
        self.accept()

    def datos(self) -> dict:
        return {"nombre": self.nombre.text(), "subtitulo": self.subtitulo.text(), "ruc": self.ruc.text(),
                "direccion": self.direccion.text(), "telefono": self.telefono.text(), "correo": self.correo.text(),
                "itbms_tasa": self.itbms.value(), "logo": self.logo}


class EmpresasTab(QWidget):
    def __init__(self):
        super().__init__()
        lay = pagina(self)
        lay.addWidget(encabezado_pagina(
            "Empresas", "Razones sociales que emiten cotizaciones y facturas. Cada una tiene su encabezado, "
                        "logo y tasa de ITBMS."))
        barra = QHBoxLayout()
        self.btn_nueva = boton("Nueva empresa", "plus", "primario")
        self.btn_editar = boton("Editar", "edit")
        self.btn_predet = boton("Hacer predeterminada", "star")
        self.btn_eliminar = boton("Eliminar", "trash", "peligro")
        for b in (self.btn_nueva, self.btn_editar, self.btn_predet):
            barra.addWidget(b)
        barra.addStretch()
        barra.addWidget(self.btn_eliminar)
        lay.addLayout(barra)
        self.tabla = tabla_estandar(["", "Empresa", "Subtítulo", "RUC", "Correo", "ITBMS", "Logo"], estirar=1)
        self.tabla.setColumnWidth(0, 40)
        self.tabla.cellDoubleClicked.connect(lambda *_: self.editar_empresa())
        self.tabla.currentCellChanged.connect(lambda *_: self._actualizar_acciones())
        lay.addWidget(self.tabla, 1)
        self.btn_nueva.clicked.connect(self.nueva_empresa)
        self.btn_editar.clicked.connect(self.editar_empresa)
        self.btn_predet.clicked.connect(self.hacer_predeterminada)
        self.btn_eliminar.clicked.connect(self.eliminar_empresa)
        self.refrescar()

    def _id_seleccionado(self):
        f = self.tabla.currentRow()
        it = self.tabla.item(f, 1) if f >= 0 else None
        return it.data(Qt.UserRole) if it else None

    def _actualizar_acciones(self):
        hay = self._id_seleccionado() is not None
        for b in (self.btn_editar, self.btn_predet, self.btn_eliminar):
            b.setEnabled(hay)

    def refrescar(self):
        conn = db.get_connection()
        filas = db.listar_empresas(conn)
        conn.close()
        sel = self._id_seleccionado()
        self.tabla.setRowCount(len(filas))
        for i, e in enumerate(filas):
            estrella = QTableWidgetItem()
            if e["predeterminada"]:
                estrella.setIcon(iconos.icono("star", estilo.AMBAR, 18))
                estrella.setToolTip("Empresa predeterminada")
            nombre = QTableWidgetItem(e["nombre"])
            nombre.setData(Qt.UserRole, e["id"])
            tasa = QTableWidgetItem("Exenta" if e["itbms_tasa"] == 0 else f"{e['itbms_tasa']:g} %")
            tasa.setTextAlignment(Qt.AlignCenter)
            logo = QTableWidgetItem("Sí" if e["logo"] else "—")
            logo.setTextAlignment(Qt.AlignCenter)
            for c, it in enumerate((estrella, nombre, QTableWidgetItem(e["subtitulo"]), QTableWidgetItem(e["ruc"]),
                                    QTableWidgetItem(e["correo"]), tasa, logo)):
                self.tabla.setItem(i, c, it)
            if e["id"] == sel:
                self.tabla.setCurrentCell(i, 1)
        self._actualizar_acciones()

    def nueva_empresa(self):
        dlg = EmpresaDialog(parent=self)
        if dlg.exec():
            conn = db.get_connection()
            try:
                db.guardar_empresa(dlg.datos(), conn)
            except ValueError as e:
                QMessageBox.warning(self, "Empresa", str(e))
            finally:
                conn.close()
            self.refrescar()

    def editar_empresa(self):
        eid = self._id_seleccionado()
        if eid is None:
            return
        conn = db.get_connection()
        empresa = db.obtener_empresa(eid, conn)
        conn.close()
        dlg = EmpresaDialog(empresa, parent=self)
        if dlg.exec():
            conn = db.get_connection()
            try:
                db.guardar_empresa(dlg.datos(), conn, eid)
            except ValueError as e:
                QMessageBox.warning(self, "Empresa", str(e))
            finally:
                conn.close()
            self.refrescar()

    def hacer_predeterminada(self):
        eid = self._id_seleccionado()
        if eid is not None:
            conn = db.get_connection()
            db.establecer_empresa_predeterminada(eid, conn)
            conn.close()
            self.refrescar()

    def eliminar_empresa(self):
        eid = self._id_seleccionado()
        if eid is None:
            return
        if QMessageBox.question(self, "Eliminar empresa", "¿Eliminar la empresa seleccionada?") != QMessageBox.Yes:
            return
        conn = db.get_connection()
        try:
            db.eliminar_empresa(eid, conn)
        except ValueError as e:
            QMessageBox.warning(self, "Eliminar empresa", str(e))
        finally:
            conn.close()
        self.refrescar()
