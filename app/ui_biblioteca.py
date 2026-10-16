"""Biblioteca de conceptos reutilizables: servicios con precio fijo o ítems con análisis de precio unitario."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QStackedWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app import calculo, db, estilo, iconos
from app.calculo import Apu, Concepto
from app.ui_apu import ApuEditor
from app.ui_comun import boton, encabezado_pagina, pagina, tabla_estandar

ICONO_MODALIDAD = {calculo.SERVICIO: "briefcase", calculo.OBRA: "tool"}


def celda_tipo(modalidad: str) -> QTableWidgetItem:
    it = QTableWidgetItem(calculo.MODALIDADES.get(modalidad, modalidad))
    it.setIcon(iconos.icono(ICONO_MODALIDAD.get(modalidad, "file"), estilo.AZUL, 18))
    return it


NOMBRE_CORTO = {calculo.SERVICIO: "Servicio", calculo.OBRA: "Obra"}


def combo_modalidad(corto: bool = False) -> QComboBox:
    """Combo de tipo de concepto con icono (maletín = servicio profesional, herramienta = mano de obra y material).
    Con `corto` el texto se abrevia (para tablas); el nombre completo queda en el tooltip."""
    cb = QComboBox()
    for clave, nombre in calculo.MODALIDADES.items():
        cb.addItem(iconos.icono(ICONO_MODALIDAD[clave], estilo.AZUL_OSCURO, 18),
                   NOMBRE_CORTO[clave] if corto else nombre, clave)
        cb.setItemData(cb.count() - 1, nombre, Qt.ToolTipRole)
    cb.setToolTip(calculo.MODALIDADES[cb.currentData()])
    cb.currentIndexChanged.connect(lambda *_: cb.setToolTip(calculo.MODALIDADES[cb.currentData()]))
    return cb


class ConceptoDialog(QDialog):
    def __init__(self, concepto: Concepto | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editar concepto" if concepto and concepto.id else "Nuevo concepto")
        self.resize(900, 720)
        self.concepto_id = concepto.id if concepto else None
        self.apu = concepto.apu.copia() if concepto and concepto.apu else Apu()
        conn = db.get_connection()
        self.cfg = db.coef_apu_defecto(conn)
        conn.close()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 14)
        form = QFormLayout()
        form.setVerticalSpacing(8)
        self.descripcion = QLineEdit(concepto.descripcion if concepto else "")
        self.descripcion.setPlaceholderText("Ej.: Muro de bloque de 6\"")
        self.unidad = QLineEdit(concepto.unidad if concepto else "")
        self.unidad.setPlaceholderText("m², m³, ml, uni…")
        self.categoria = QLineEdit(concepto.categoria if concepto else "")
        self.categoria.setPlaceholderText("Capítulo o familia (opcional): Albañilería, Pintura…")
        self.modalidad = combo_modalidad()
        if concepto:
            self.modalidad.setCurrentIndex(self.modalidad.findData(concepto.modalidad))
        form.addRow("Descripción *:", self.descripcion)
        form.addRow("Unidad:", self.unidad)
        form.addRow("Categoría:", self.categoria)
        form.addRow("Tipo de concepto:", self.modalidad)
        lay.addLayout(form)

        self.pila = QStackedWidget()
        pag_servicio = QWidget()
        ls = QFormLayout(pag_servicio)
        self.precio = QDoubleSpinBox()
        self.precio.setRange(0, 1_000_000_000)
        self.precio.setDecimals(2)
        self.precio.setPrefix("B/. ")
        self.precio.setValue(concepto.precio if concepto else 0)
        ls.addRow("Precio unitario:", self.precio)
        nota = QLabel("Servicio profesional: se cotiza con un precio fijo por unidad.")
        nota.setObjectName("subtitulo")
        ls.addRow("", nota)
        self.editor = ApuEditor(self.apu, self.cfg, 0.0)
        self.pila.addWidget(pag_servicio)
        self.pila.addWidget(self.editor)
        lay.addWidget(self.pila, 1)
        info = QLabel("Los coeficientes de venta del análisis son los valores por defecto (Configuración); "
                      "cada cotización aplica los suyos.")
        info.setObjectName("subtitulo")
        info.setWordWrap(True)
        lay.addWidget(info)

        pie = QHBoxLayout()
        pie.addStretch()
        cancelar = boton("Cancelar", "x")
        guardar = boton("Guardar", "save", "primario")
        cancelar.clicked.connect(self.reject)
        guardar.clicked.connect(self._guardar)
        pie.addWidget(cancelar)
        pie.addWidget(guardar)
        lay.addLayout(pie)
        self.modalidad.currentIndexChanged.connect(lambda *_: self._cambio_modalidad())
        self._cambio_modalidad()

    def _cambio_modalidad(self):
        self.pila.setCurrentIndex(1 if self.modalidad.currentData() == calculo.OBRA else 0)

    def concepto(self) -> Concepto:
        obra = self.modalidad.currentData() == calculo.OBRA
        return Concepto(self.concepto_id, self.descripcion.text(), self.unidad.text(), self.modalidad.currentData(),
                        self.precio.value(), self.categoria.text(), self.apu if obra else None)

    def _guardar(self):
        if self.modalidad.currentData() == calculo.OBRA:
            error = self.editor.validar()
            if error:
                QMessageBox.warning(self, "Concepto", error)
                return
            self.editor.limpiar_vacios()
        if not self.descripcion.text().strip():
            QMessageBox.warning(self, "Concepto", "La descripción del concepto es obligatoria.")
            return
        self.accept()


class SelectorConceptosDialog(QDialog):
    """Elige uno o varios conceptos de la biblioteca para insertarlos en una cotización."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Insertar desde la biblioteca")
        self.resize(820, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 14)
        fila = QHBoxLayout()
        self.busqueda = QLineEdit()
        self.busqueda.setPlaceholderText("Buscar por descripción o categoría…")
        self.busqueda.setClearButtonEnabled(True)
        self.busqueda.addAction(iconos.icono("search", estilo.APAGADO, 16), QLineEdit.LeadingPosition)
        self.busqueda.textChanged.connect(lambda *_: self._cargar())
        fila.addWidget(self.busqueda, 1)
        lay.addLayout(fila)
        self.tabla = tabla_estandar(["Categoría", "Descripción", "Ud.", "Tipo", "Precio"], estirar=1)
        self.tabla.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tabla.doubleClicked.connect(lambda *_: self.accept())
        lay.addWidget(self.tabla, 1)
        self.vacio = QLabel("La biblioteca está vacía. Guarda conceptos desde la cotización o en la sección Biblioteca.")
        self.vacio.setObjectName("subtitulo")
        self.vacio.setWordWrap(True)
        lay.addWidget(self.vacio)
        pie = QHBoxLayout()
        pie.addStretch()
        cancelar = boton("Cancelar", "x")
        self.btn_insertar = boton("Insertar seleccionados", "plus", "primario")
        cancelar.clicked.connect(self.reject)
        self.btn_insertar.clicked.connect(self.accept)
        pie.addWidget(cancelar)
        pie.addWidget(self.btn_insertar)
        lay.addLayout(pie)
        self._conceptos = []
        self._cargar()

    def _cargar(self):
        conn = db.get_connection()
        self._conceptos = db.listar_conceptos(conn, self.busqueda.text())
        precios = [db.precio_referencial(c, conn) for c in self._conceptos]
        total = conn.execute("SELECT COUNT(*) AS n FROM conceptos").fetchone()["n"]
        conn.close()
        self.vacio.setVisible(total == 0)
        self.tabla.setRowCount(len(self._conceptos))
        for r, (c, p) in enumerate(zip(self._conceptos, precios)):
            precio = QTableWidgetItem(f"B/. {p:,.2f}")
            precio.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            for col, it in enumerate((QTableWidgetItem(c.categoria), QTableWidgetItem(c.descripcion),
                                      QTableWidgetItem(c.unidad), celda_tipo(c.modalidad), precio)):
                self.tabla.setItem(r, col, it)

    def seleccion(self) -> list[Concepto]:
        filas = sorted({i.row() for i in self.tabla.selectedIndexes()})
        return [self._conceptos[f] for f in filas if f < len(self._conceptos)]


class BibliotecaTab(QWidget):
    def __init__(self):
        super().__init__()
        lay = pagina(self)
        lay.addWidget(encabezado_pagina(
            "Biblioteca de conceptos",
            "Guarda servicios y análisis de precio unitario para reutilizarlos en cualquier cotización."))
        barra = QHBoxLayout()
        self.btn_nuevo = boton("Nuevo concepto", "plus", "primario")
        self.btn_editar = boton("Editar", "edit")
        self.btn_duplicar = boton("Duplicar", "copy")
        self.btn_eliminar = boton("Eliminar", "trash", "peligro")
        for b in (self.btn_nuevo, self.btn_editar, self.btn_duplicar):
            barra.addWidget(b)
        barra.addStretch()
        barra.addWidget(self.btn_eliminar)
        lay.addLayout(barra)

        filtros = QHBoxLayout()
        self.busqueda = QLineEdit()
        self.busqueda.setPlaceholderText("Buscar por descripción o categoría…")
        self.busqueda.setClearButtonEnabled(True)
        self.busqueda.addAction(iconos.icono("search", estilo.APAGADO, 16), QLineEdit.LeadingPosition)
        self.tipo = QComboBox()
        self.tipo.addItem("Todos los tipos", None)
        for clave, nombre in calculo.MODALIDADES.items():
            self.tipo.addItem(nombre, clave)
        filtros.addWidget(self.busqueda, 1)
        filtros.addWidget(self.tipo)
        lay.addLayout(filtros)

        self.tabla = tabla_estandar(["Categoría", "Descripción", "Ud.", "Tipo", "Precio referencial"], estirar=1)
        lay.addWidget(self.tabla, 1)
        nota = QLabel("El precio de un concepto «mano de obra y material» es referencial: se calcula con los coeficientes "
                      "por defecto; en cada cotización se recalcula con los suyos.")
        nota.setObjectName("subtitulo")
        nota.setWordWrap(True)
        lay.addWidget(nota)

        self.busqueda.textChanged.connect(lambda *_: self.refrescar())
        self.tipo.currentIndexChanged.connect(lambda *_: self.refrescar())
        self.tabla.cellDoubleClicked.connect(lambda *_: self.editar())
        self.tabla.currentCellChanged.connect(lambda *_: self._actualizar_acciones())
        self.btn_nuevo.clicked.connect(self.nuevo)
        self.btn_editar.clicked.connect(self.editar)
        self.btn_duplicar.clicked.connect(self.duplicar)
        self.btn_eliminar.clicked.connect(self.eliminar)
        self.refrescar()

    def _id_seleccionado(self):
        f = self.tabla.currentRow()
        it = self.tabla.item(f, 1) if f >= 0 else None
        return it.data(Qt.UserRole) if it else None

    def _actualizar_acciones(self):
        hay = self._id_seleccionado() is not None
        for b in (self.btn_editar, self.btn_duplicar, self.btn_eliminar):
            b.setEnabled(hay)

    def refrescar(self):
        conn = db.get_connection()
        conceptos = db.listar_conceptos(conn, self.busqueda.text(), self.tipo.currentData())
        precios = [db.precio_referencial(c, conn) for c in conceptos]
        conn.close()
        sel = self._id_seleccionado()
        self.tabla.setRowCount(len(conceptos))
        for r, (c, p) in enumerate(zip(conceptos, precios)):
            desc = QTableWidgetItem(c.descripcion)
            desc.setData(Qt.UserRole, c.id)
            precio = QTableWidgetItem(f"B/. {p:,.2f}")
            precio.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            for col, it in enumerate((QTableWidgetItem(c.categoria), desc, QTableWidgetItem(c.unidad),
                                      celda_tipo(c.modalidad), precio)):
                self.tabla.setItem(r, col, it)
            if c.id == sel:
                self.tabla.setCurrentCell(r, 1)
        self._actualizar_acciones()

    def _guardar(self, dlg):
        conn = db.get_connection()
        try:
            db.guardar_concepto(dlg.concepto(), conn)
        except ValueError as e:
            QMessageBox.warning(self, "Concepto", str(e))
        finally:
            conn.close()
        self.refrescar()

    def nuevo(self):
        dlg = ConceptoDialog(parent=self)
        if dlg.exec():
            self._guardar(dlg)

    def editar(self):
        cid = self._id_seleccionado()
        if cid is None:
            return
        conn = db.get_connection()
        concepto = db.obtener_concepto(cid, conn)
        conn.close()
        dlg = ConceptoDialog(concepto, parent=self)
        if dlg.exec():
            self._guardar(dlg)

    def duplicar(self):
        cid = self._id_seleccionado()
        if cid is not None:
            conn = db.get_connection()
            db.duplicar_concepto(cid, conn)
            conn.close()
            self.refrescar()

    def eliminar(self):
        cid = self._id_seleccionado()
        if cid is None:
            return
        if QMessageBox.question(self, "Eliminar concepto",
                                "¿Eliminar el concepto de la biblioteca? Las cotizaciones que ya lo usan no cambian.") \
                != QMessageBox.Yes:
            return
        conn = db.get_connection()
        db.eliminar_concepto(cid, conn)
        conn.close()
        self.refrescar()
