"""Biblioteca de conceptos reutilizables: servicios con precio fijo o ítems con análisis de precio unitario."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QStackedWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app import calculo, db, estilo, iconos
from app.calculo import Apu, Concepto
from app.ui_apu import ApuEditor
from app.ui_comun import permitir_maximizar, anchos_fijos, boton, encabezado_pagina, pagina, tabla_estandar

ICONO_MODALIDAD = {calculo.SERVICIO: "briefcase", calculo.OBRA: "tool"}
NOMBRE_CORTO = {calculo.SERVICIO: "Servicio", calculo.OBRA: "Obra"}


def celda_tipo(modalidad: str) -> QTableWidgetItem:
    """Tipo con icono; texto corto («Servicio» / «Obra») y el nombre completo en el tooltip."""
    it = QTableWidgetItem(NOMBRE_CORTO.get(modalidad, modalidad))
    it.setToolTip(calculo.MODALIDADES.get(modalidad, modalidad))
    it.setIcon(iconos.icono(ICONO_MODALIDAD.get(modalidad, "file"), estilo.AZUL, 18))
    return it


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
        permitir_maximizar(self)
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
        self.biblioteca = QComboBox()
        self.biblioteca.setMinimumWidth(260)
        self.biblioteca.addItem("Todas las bibliotecas", None)
        conn = db.get_connection()
        for b in db.listar_bibliotecas(conn):
            self.biblioteca.addItem(f"{b['nombre']} ({b['n']:,})", b["id"])
        conn.close()
        self.biblioteca.currentIndexChanged.connect(lambda *_: self._cargar())
        fila.addWidget(self.busqueda, 1)
        fila.addWidget(self.biblioteca)
        lay.addLayout(fila)
        self.tabla = tabla_estandar(["Categoría", "Descripción", "Ud.", "Tipo", "Precio"], estirar=1)
        anchos_fijos(self.tabla, {0: 230, 2: 60, 3: 105, 4: 110})
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
        self._conceptos = db.listar_conceptos(conn, self.busqueda.text(), biblioteca_id=self.biblioteca.currentData())
        cfg = db.coef_apu_defecto(conn)
        precios = [db.precio_referencial(c, conn, cfg) for c in self._conceptos]
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
            "Servicios y análisis de precio unitario para reutilizar en cualquier cotización, organizados en bibliotecas."))

        # --- bibliotecas
        fila = QHBoxLayout()
        etiqueta = QLabel("Biblioteca:")
        etiqueta.setObjectName("seccion")
        self.bib_combo = QComboBox()
        self.bib_combo.setMinimumWidth(260)
        self.btn_bib_nueva = boton("Nueva", "folder-plus", "primario", tooltip="Nueva biblioteca")
        self.btn_bib_renombrar = boton("Renombrar", "edit", tooltip="Renombrar la biblioteca")
        self.btn_bib_duplicar = boton("Duplicar", "copy", tooltip="Duplicar la biblioteca con todos sus conceptos")
        self.btn_bib_eliminar = boton("Eliminar", "trash", "peligro", tooltip="Eliminar la biblioteca y sus conceptos")
        fila.addWidget(etiqueta)
        fila.addWidget(self.bib_combo, 1)
        for b in (self.btn_bib_nueva, self.btn_bib_renombrar, self.btn_bib_duplicar, self.btn_bib_eliminar):
            fila.addWidget(b)
        lay.addLayout(fila)

        # --- conceptos
        barra = QHBoxLayout()
        etiqueta_c = QLabel("Conceptos:")
        etiqueta_c.setObjectName("seccion")
        barra.addWidget(etiqueta_c)
        self.btn_nuevo = boton("Nuevo concepto", "plus", "primario")
        self.btn_editar = boton("Editar", "edit")
        self.btn_duplicar = boton("Duplicar", "copy")
        self.btn_copiar = boton("Copiar a…", "download",
                                tooltip="Copia los conceptos seleccionados a otra biblioteca")
        self.btn_eliminar = boton("Eliminar", "trash", "peligro")
        for b in (self.btn_nuevo, self.btn_editar, self.btn_duplicar, self.btn_copiar):
            barra.addWidget(b)
        barra.addStretch()
        barra.addWidget(self.btn_eliminar)
        lay.addLayout(barra)

        filtros = QHBoxLayout()
        self.busqueda = QLineEdit()
        self.busqueda.setPlaceholderText("Buscar por descripción o categoría…")
        self.busqueda.setClearButtonEnabled(True)
        self.busqueda.addAction(iconos.icono("search", estilo.APAGADO, 16), QLineEdit.LeadingPosition)
        self.disciplina = QComboBox()
        self.disciplina.setMinimumWidth(220)
        self.tipo = QComboBox()
        self.tipo.addItem("Todos los tipos", None)
        for clave, nombre in calculo.MODALIDADES.items():
            self.tipo.addItem(nombre, clave)
        filtros.addWidget(self.busqueda, 1)
        filtros.addWidget(self.disciplina)
        filtros.addWidget(self.tipo)
        lay.addLayout(filtros)

        self.tabla = tabla_estandar(["Categoría", "Descripción", "Ud.", "Tipo", "Costo directo", "Precio ref."], estirar=1)
        anchos_fijos(self.tabla, {0: 250, 2: 60, 3: 105, 4: 125, 5: 115})
        self.tabla.verticalHeader().setDefaultSectionSize(34)
        self.tabla.setSelectionMode(QAbstractItemView.ExtendedSelection)
        lay.addWidget(self.tabla, 1)
        self.lbl_total = QLabel()
        self.lbl_total.setObjectName("subtitulo")
        lay.addWidget(self.lbl_total)
        nota = QLabel("Costo directo: suma de los insumos sin coeficientes. Precio ref.: con los coeficientes por defecto "
                      "(Configuración); en cada cotización se recalcula con los suyos.")
        nota.setObjectName("subtitulo")
        nota.setWordWrap(True)
        lay.addWidget(nota)

        self.bib_combo.currentIndexChanged.connect(lambda *_: self._cambio_biblioteca())
        self.busqueda.textChanged.connect(lambda *_: self.refrescar_conceptos())
        self.tipo.currentIndexChanged.connect(lambda *_: self.refrescar_conceptos())
        self.disciplina.currentIndexChanged.connect(lambda *_: self.refrescar_conceptos())
        self.tabla.cellDoubleClicked.connect(lambda *_: self.editar())
        self.tabla.currentCellChanged.connect(lambda *_: self._actualizar_acciones())
        self.tabla.itemSelectionChanged.connect(self._actualizar_acciones)
        self.btn_nuevo.clicked.connect(self.nuevo)
        self.btn_editar.clicked.connect(self.editar)
        self.btn_duplicar.clicked.connect(self.duplicar)
        self.btn_copiar.clicked.connect(self.copiar_a_otra)
        self.btn_eliminar.clicked.connect(self.eliminar)
        self.btn_bib_nueva.clicked.connect(self.nueva_biblioteca)
        self.btn_bib_renombrar.clicked.connect(self.renombrar_biblioteca)
        self.btn_bib_duplicar.clicked.connect(self.duplicar_biblioteca)
        self.btn_bib_eliminar.clicked.connect(self.eliminar_biblioteca)
        self.refrescar()

    # ------------------------------------------------------------------ bibliotecas
    def _biblioteca_id(self):
        return self.bib_combo.currentData()

    def _cargar_bibliotecas(self, seleccionar=None):
        """Llena el combo de bibliotecas (conserva la elegida, o la indicada)."""
        actual = seleccionar if seleccionar is not None else self.bib_combo.currentData()
        conn = db.get_connection()
        bibliotecas = db.listar_bibliotecas(conn)
        conn.close()
        self.bib_combo.blockSignals(True)
        self.bib_combo.clear()
        for b in bibliotecas:
            self.bib_combo.addItem(f"{b['nombre']} ({b['n']:,})", b["id"])
            self.bib_combo.setItemData(self.bib_combo.count() - 1, f"{b['nombre']}: {b['n']:,} conceptos", Qt.ToolTipRole)
        idx = self.bib_combo.findData(actual)
        self.bib_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.bib_combo.blockSignals(False)
        self.btn_bib_eliminar.setEnabled(len(bibliotecas) > 1)

    def _nombre_actual(self):
        i = self.bib_combo.currentIndex()
        if i < 0:
            return ""
        return self.bib_combo.itemText(i).rsplit(" (", 1)[0]

    def _cambio_biblioteca(self):
        self.disciplina.blockSignals(True)
        self.disciplina.setCurrentIndex(0)
        self.disciplina.blockSignals(False)
        self.refrescar_conceptos()

    def nueva_biblioteca(self):
        nombre, ok = QInputDialog.getText(self, "Nueva biblioteca", "Nombre de la biblioteca:")
        if not ok:
            return
        conn = db.get_connection()
        try:
            bid = db.crear_biblioteca(nombre, conn)
        except ValueError as e:
            QMessageBox.warning(self, "Biblioteca", str(e))
            return
        finally:
            conn.close()
        self._cargar_bibliotecas(bid)
        self.refrescar_conceptos()

    def renombrar_biblioteca(self):
        bid = self._biblioteca_id()
        if bid is None:
            return
        nombre, ok = QInputDialog.getText(self, "Renombrar biblioteca", "Nuevo nombre:", text=self._nombre_actual())
        if not ok:
            return
        conn = db.get_connection()
        try:
            db.renombrar_biblioteca(bid, nombre, conn)
        except ValueError as e:
            QMessageBox.warning(self, "Biblioteca", str(e))
            return
        finally:
            conn.close()
        self._cargar_bibliotecas(bid)

    def duplicar_biblioteca(self):
        bid = self._biblioteca_id()
        if bid is None:
            return
        conn = db.get_connection()
        try:
            nuevo = db.duplicar_biblioteca(bid, conn)
        except ValueError as e:
            QMessageBox.warning(self, "Biblioteca", str(e))
            return
        finally:
            conn.close()
        self._cargar_bibliotecas(nuevo)
        self.refrescar_conceptos()

    def eliminar_biblioteca(self):
        bid = self._biblioteca_id()
        if bid is None:
            return
        r = QMessageBox.question(
            self, "Eliminar biblioteca",
            f"¿Eliminar la biblioteca «{self._nombre_actual()}» con todos sus conceptos?\n\n"
            "Esta acción no se puede deshacer. Las cotizaciones que ya usan esos conceptos no cambian.")
        if r != QMessageBox.Yes:
            return
        conn = db.get_connection()
        try:
            db.eliminar_biblioteca(bid, conn)
        except ValueError as e:
            QMessageBox.warning(self, "Biblioteca", str(e))
            return
        finally:
            conn.close()
        self._cargar_bibliotecas()
        self.refrescar_conceptos()

    # ------------------------------------------------------------------ conceptos
    def _ids_seleccionados(self):
        filas = sorted({i.row() for i in self.tabla.selectedIndexes()})
        ids = []
        for f in filas:
            it = self.tabla.item(f, 1)
            if it is not None and it.data(Qt.UserRole) is not None:
                ids.append(it.data(Qt.UserRole))
        return ids

    def _id_seleccionado(self):
        f = self.tabla.currentRow()
        it = self.tabla.item(f, 1) if f >= 0 else None
        return it.data(Qt.UserRole) if it else None

    def _actualizar_acciones(self):
        hay = self._id_seleccionado() is not None
        for b in (self.btn_editar, self.btn_duplicar, self.btn_eliminar):
            b.setEnabled(hay)
        self.btn_copiar.setEnabled(bool(self._ids_seleccionados()) and self.bib_combo.count() > 1)

    def _cargar_disciplinas(self, conn):
        """Llena el filtro de categorías de la biblioteca elegida (conserva la elegida si sigue existiendo)."""
        actual = self.disciplina.currentData()
        self.disciplina.blockSignals(True)
        self.disciplina.clear()
        self.disciplina.addItem("Todas las categorías", None)
        for d in db.disciplinas_conceptos(conn, self._biblioteca_id()):
            self.disciplina.addItem(d, d)
        idx = self.disciplina.findData(actual)
        self.disciplina.setCurrentIndex(max(idx, 0))
        self.disciplina.blockSignals(False)

    def refrescar(self):
        self._cargar_bibliotecas()
        self.refrescar_conceptos()

    def refrescar_conceptos(self):
        conn = db.get_connection()
        self._cargar_disciplinas(conn)
        bid = self._biblioteca_id()
        conceptos = db.listar_conceptos(conn, self.busqueda.text(), self.tipo.currentData(),
                                        self.disciplina.currentData(), bid)
        cfg = db.coef_apu_defecto(conn)
        precios = [db.precio_referencial(c, conn, cfg) for c in conceptos]
        total = conn.execute("SELECT COUNT(*) AS n FROM conceptos WHERE biblioteca_id = ?", (bid,)).fetchone()["n"]
        conn.close()
        sel = self._id_seleccionado()
        self.tabla.setUpdatesEnabled(False)
        self.tabla.setRowCount(len(conceptos))
        for r, (c, p) in enumerate(zip(conceptos, precios)):
            desc = QTableWidgetItem(c.descripcion)
            desc.setData(Qt.UserRole, c.id)
            desc.setToolTip(c.descripcion)
            costo = QTableWidgetItem(f"B/. {db.costo_directo(c):,.2f}")
            costo.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            precio = QTableWidgetItem(f"B/. {p:,.2f}")
            precio.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            for col, it in enumerate((QTableWidgetItem(c.categoria), desc, QTableWidgetItem(c.unidad),
                                      celda_tipo(c.modalidad), costo, precio)):
                self.tabla.setItem(r, col, it)
            if c.id == sel:
                self.tabla.setCurrentCell(r, 1)
        self.tabla.setUpdatesEnabled(True)
        self.lbl_total.setText(f"{len(conceptos):,} de {total:,} conceptos" if total else
                               "Esta biblioteca está vacía. Crea un concepto, guarda ítems desde una cotización o "
                               "copia conceptos desde otra biblioteca.")
        self._actualizar_acciones()

    def _guardar(self, dlg):
        conn = db.get_connection()
        try:
            c = dlg.concepto()
            if c.id is None:
                c.biblioteca_id = self._biblioteca_id()
            db.guardar_concepto(c, conn)
        except ValueError as e:
            QMessageBox.warning(self, "Concepto", str(e))
        finally:
            conn.close()
        self._cargar_bibliotecas()
        self.refrescar_conceptos()

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
            self._cargar_bibliotecas()
            self.refrescar_conceptos()

    def copiar_a_otra(self):
        ids = self._ids_seleccionados()
        if not ids:
            return
        conn = db.get_connection()
        otras = [b for b in db.listar_bibliotecas(conn) if b["id"] != self._biblioteca_id()]
        conn.close()
        if not otras:
            QMessageBox.information(self, "Copiar", "Crea primero otra biblioteca para copiar los conceptos.")
            return
        nombres = [b["nombre"] for b in otras]
        elegido, ok = QInputDialog.getItem(self, "Copiar a otra biblioteca",
                                           f"Copiar {len(ids)} concepto(s) a:", nombres, 0, False)
        if not ok:
            return
        destino = otras[nombres.index(elegido)]["id"]
        conn = db.get_connection()
        n = db.copiar_conceptos(ids, destino, conn)
        conn.close()
        self._cargar_bibliotecas()
        QMessageBox.information(self, "Copiar", f"Se copiaron {n} concepto(s) a «{elegido}».")

    def eliminar(self):
        ids = self._ids_seleccionados()
        if not ids:
            return
        cuantos = f"{len(ids)} conceptos" if len(ids) > 1 else "el concepto seleccionado"
        if QMessageBox.question(self, "Eliminar concepto",
                                f"¿Eliminar {cuantos} de la biblioteca? Las cotizaciones que ya lo usan no cambian.") \
                != QMessageBox.Yes:
            return
        conn = db.get_connection()
        for cid in ids:
            db.eliminar_concepto(cid, conn)
        conn.close()
        self._cargar_bibliotecas()
        self.refrescar_conceptos()
