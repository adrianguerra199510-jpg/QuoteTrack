"""Editor de una cotización: grupos y sub-ítems, ITBMS por línea, costos adicionales y notas."""
from dataclasses import replace

from PySide6.QtCore import QRectF, QTimer, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QRadioButton, QSplitter, QToolTip, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMenu,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app import calculo, db, estilo, iconos, texto_rico
from app.calculo import Apu, Cargo, Linea
from app.ui_apu import AjustesApuDialog, ApuDialog
from app.ui_biblioteca import SelectorConceptosDialog, combo_modalidad
from app.ui_comun import ROL_HTML, TextoRicoDelegate, boton, permitir_maximizar, parsear_numero, tabla_estandar
from app.ui_texto import EditorTextoDialog
from app.ui_vista_previa import vista_previa

COL_COD, COL_DESC, COL_TIPO, COL_UD, COL_CANT, COL_PRECIO, COL_IMPORTE, COL_ITBMS = range(8)
CARGO_CONCEPTO, CARGO_TIPO, CARGO_VALOR, CARGO_MONTO, CARGO_ITBMS, CARGO_BASE, CARGO_DILUIR = range(7)
FONDO_GRUPO = QBrush(QColor("#E8EEFC"))
ROJO = QBrush(QColor(estilo.ROJO))
PRESETS_CARGO = ["Administración", "Utilidad", "Imprevistos", "Otro…"]


def _dinero(v: float) -> str:
    return f"B/. {v:,.2f}"


class BaseCargoDialog(QDialog):
    """Elige sobre qué actúa un costo adicional: todo el subtotal o solo algunas categorías del análisis de precio."""

    def __init__(self, cargo, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Se aplica sobre · {cargo.concepto or 'costo adicional'}")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 14)
        info = QLabel("El porcentaje se calcula sobre lo que elijas, y si el costo está marcado como «Diluir» "
                      "se reparte solo entre los ítems que tengan esas categorías.")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.todo = QRadioButton("Todo el subtotal de ítems (uniformemente)")
        self.algunas = QRadioButton("Solo sobre estas categorías:")
        lay.addWidget(self.todo)
        lay.addWidget(self.algunas)
        self.checks = {}
        for clave, nombre in calculo.CATEGORIAS_BASE.items():
            ch = QCheckBox(nombre)
            ch.setStyleSheet("margin-left: 24px;")
            ch.toggled.connect(lambda *_: self.algunas.setChecked(True) if any(
                x.isChecked() for x in self.checks.values()) else None)
            self.checks[clave] = ch
            lay.addWidget(ch)
        for clave in cargo.categorias:
            self.checks[clave].setChecked(True)
        (self.algunas if cargo.categorias else self.todo).setChecked(True)
        self.todo.toggled.connect(lambda v: [c.setChecked(False) for c in self.checks.values()] if v else None)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def base(self) -> str:
        """Categorías elegidas separadas por coma; vacío = todo el subtotal."""
        if self.todo.isChecked():
            return ""
        return ",".join(k for k, c in self.checks.items() if c.isChecked())


class GraficaResumen(QWidget):
    """Barras horizontales con la composición del total, de mayor a menor: cada componente del resumen con su monto
    y su porcentaje escritos junto a la barra. Un solo tono (es magnitud, no identidad) y fondo claro."""

    COLOR = QColor("#2A78D6")
    ALTO_FILA, ANCHO_ETIQUETA = 26, 250

    def __init__(self, filas, parent=None):
        super().__init__(parent)
        self.total = next((m for _e, m, s in filas if s == "total"), 0) or 0
        partes = [(e.split(" (")[0], m) for e, m, s in filas if s == "fila" and m]
        self.partes = sorted((p for p in partes if p[1] > 0), key=lambda p: p[1], reverse=True)
        self.setMouseTracking(True)
        self.setMinimumHeight(70 + self.ALTO_FILA * max(len(self.partes), 1))
        self.setMinimumWidth(520)

    def _geometria(self):
        ancho_barra = max(self.width() - self.ANCHO_ETIQUETA - 150, 80)
        mayor = self.partes[0][1] if self.partes else 1
        return ancho_barra, mayor

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        tinta, tenue = QColor(estilo.TEXTO), QColor(estilo.APAGADO)
        fuente = p.font()
        negrita = QFont(fuente)
        negrita.setBold(True)
        p.setFont(negrita)
        p.setPen(tinta)
        p.drawText(0, 4, self.width(), 24, Qt.AlignLeft | Qt.AlignVCenter, "¿De qué se compone el total?")
        p.setFont(fuente)
        p.setPen(tenue)
        p.drawText(0, 26, self.width(), 20, Qt.AlignLeft | Qt.AlignVCenter,
                   f"Total de la cotización: {_dinero(self.total)} · cada barra es un componente del resumen")
        ancho_barra, mayor = self._geometria()
        x0 = self.ANCHO_ETIQUETA
        top = 56
        # rejilla tenue y eje de base
        p.setPen(QPen(QColor("#E5E7EB"), 1))
        for f in (0.5, 1.0):
            x = x0 + int(ancho_barra * f)
            p.drawLine(x, top - 4, x, top + self.ALTO_FILA * len(self.partes))
        p.setPen(QPen(QColor("#9CA3AF"), 1))
        p.drawLine(x0, top - 4, x0, top + self.ALTO_FILA * len(self.partes))
        for i, (nombre, monto) in enumerate(self.partes):
            y = top + i * self.ALTO_FILA
            p.setPen(tinta)
            p.drawText(0, y, x0 - 10, self.ALTO_FILA, Qt.AlignRight | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(nombre, Qt.ElideRight, x0 - 10))
            largo = max(int(ancho_barra * monto / mayor), 3)
            alto = self.ALTO_FILA - 12
            p.setPen(Qt.NoPen)
            p.setBrush(self.COLOR)
            p.drawRoundedRect(QRectF(x0 + 1, y + 6, largo, alto), 4, 4)
            p.drawRect(QRectF(x0 + 1, y + 6, min(largo, 5), alto))        # la base pegada al eje es recta
            pct = f"{monto / self.total * 100:.1f}%" if self.total else ""
            p.setPen(tinta)
            p.drawText(x0 + largo + 8, y, 150, self.ALTO_FILA, Qt.AlignLeft | Qt.AlignVCenter,
                       f"{_dinero(monto)}  ·  {pct}")
        p.end()

    def mouseMoveEvent(self, ev):
        i = int((ev.position().y() - 56) // self.ALTO_FILA)
        if 0 <= i < len(self.partes):
            nombre, monto = self.partes[i]
            pct = f" ({monto / self.total * 100:.1f}% del total)" if self.total else ""
            QToolTip.showText(ev.globalPosition().toPoint(), f"{nombre}: {_dinero(monto)}{pct}", self)
        else:
            QToolTip.hideText()


class ResumenDialog(QDialog):
    """Resumen de la cotización: costos directos por categoría, margen de los análisis, costos adicionales y total."""

    def __init__(self, filas, titulo="Resumen de la cotización", parent=None):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.resize(900, 920)
        permitir_maximizar(self)
        self.filas = filas
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 12)
        self.tabla = tabla_estandar(["Concepto", "Monto", "% del total"], estirar=0)
        self.tabla.setSelectionMode(QTableWidget.NoSelection)
        self.tabla.setFocusPolicy(Qt.NoFocus)
        self.tabla.verticalHeader().setDefaultSectionSize(28)
        self.tabla.verticalHeader().setMinimumSectionSize(24)
        total = next((m for _e, m, s in filas if s == "total"), 0) or 0
        self.tabla.setRowCount(len(filas))
        negrita = QFont()
        negrita.setBold(True)
        for i, (etiqueta, monto, tipo) in enumerate(filas):
            celdas = [QTableWidgetItem(etiqueta),
                      QTableWidgetItem("" if monto is None else _dinero(monto)),
                      QTableWidgetItem("" if monto is None or not total else f"{monto / total * 100:.1f}%")]
            for c, it in enumerate(celdas):
                it.setFlags(Qt.ItemIsEnabled)
                if c:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if tipo in ("seccion", "subtotal", "total"):
                    it.setFont(negrita)
                if tipo == "seccion":
                    it.setBackground(FONDO_GRUPO)
                elif tipo == "total":
                    it.setBackground(QBrush(QColor("#DBEAFE")))
                self.tabla.setItem(i, c, it)
        hc = self.tabla.horizontalHeader()
        hc.setSectionResizeMode(1, QHeaderView.Fixed)
        hc.setSectionResizeMode(2, QHeaderView.Fixed)
        self.tabla.setColumnWidth(1, 140)
        self.tabla.setColumnWidth(2, 110)
        self.tabla.setWordWrap(True)                       # las descripciones largas de los costos no se cortan
        hc.sectionResized.connect(lambda *_: self.tabla.resizeRowsToContents())
        QTimer.singleShot(0, self.tabla.resizeRowsToContents)
        self.grafica = GraficaResumen(filas)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(self.grafica)
        self.divisor = QSplitter(Qt.Vertical)           # gráfica arriba y tabla debajo, en la misma vista
        self.divisor.addWidget(scroll)
        self.divisor.addWidget(self.tabla)
        self.divisor.setChildrenCollapsible(False)
        self.divisor.setSizes([min(self.grafica.minimumHeight() + 6, 330), 520])
        lay.addWidget(self.divisor, 1)
        fila = QHBoxLayout()
        self.btn_copiar = boton("Copiar", "copy", tooltip="Copia el resumen al portapapeles (para pegarlo en un correo o en Excel)")
        self.btn_copiar.clicked.connect(self.copiar)
        cerrar = boton("Cerrar", "x")
        cerrar.clicked.connect(self.accept)
        fila.addWidget(self.btn_copiar)
        fila.addStretch()
        fila.addWidget(cerrar)
        lay.addLayout(fila)

    def texto(self) -> str:
        total = next((m for _e, m, s in self.filas if s == "total"), 0) or 0
        return "\n".join(
            f"{e}\t{'' if m is None else f'{m:,.2f}'}\t{'' if m is None or not total else f'{m / total * 100:.1f}%'}"
            for e, m, _s in self.filas)

    def copiar(self):
        QApplication.clipboard().setText(self.texto())


def mostrar_resumen(parent, lineas, cargos, tasa, cfg, titulo="Resumen de la cotización"):
    """Abre el resumen de una cotización a partir de sus líneas, costos adicionales, tasa y coeficientes."""
    ResumenDialog(calculo.resumen(lineas, cargos, tasa, cfg), titulo, parent).exec()


class ItemsDialog(QDialog):
    def __init__(self, cotizacion_id, numero, editable, parent=None):
        super().__init__(parent)
        self.cotizacion_id = cotizacion_id
        self.editable = editable
        self._cargando = False
        self._invalidos = {}          # {("l"|"c", fila, columna): texto} con números mal escritos
        self._ocultas = {}            # {id(línea): True/False} texto oculto/visible de un ítem concreto
        self.setWindowTitle(f"Cotización {numero}" + ("" if editable else " (solo lectura)"))
        self.resize(1120, 820)
        permitir_maximizar(self)

        conn = db.get_connection()
        self.lineas = db.obtener_lineas(cotizacion_id, conn)
        self.cargos = db.obtener_cargos(cotizacion_id, conn)
        notas = db.obtener_notas(cotizacion_id, conn)
        titulo_notas = db.obtener_titulo_notas("cotizaciones", cotizacion_id, conn)
        proyecto = db.obtener_proyecto(cotizacion_id, conn)
        empresas = db.listar_empresas(conn)
        clientes = conn.execute("SELECT id, nombre FROM clientes ORDER BY nombre").fetchall()
        cliente_id = conn.execute("SELECT cliente_id FROM cotizaciones WHERE id = ?", (cotizacion_id,)).fetchone()["cliente_id"]
        empresa_actual = db.empresa_de_cotizacion(cotizacion_id, conn)
        self.tasa_guardada = db.tasa_de_cotizacion(cotizacion_id, conn)
        self.cfg = db.obtener_config_apu(cotizacion_id, conn)      # coeficientes e indirectos del APU
        self.coef_ind, self.costo_directo = 0.0, 0.0
        conn.close()
        if editable and not self.lineas:
            self.lineas.append(Linea())

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        contenido = QWidget()
        contenido.setObjectName("pagina")
        scroll.setWidget(contenido)
        raiz.addWidget(scroll, 1)
        layout = QVBoxLayout(contenido)
        layout.setContentsMargins(20, 18, 20, 12)
        layout.setSpacing(10)

        # --- encabezado: proyecto y empresa
        form = QFormLayout()
        self.proyecto_edit = QLineEdit(proyecto)
        self.proyecto_edit.setPlaceholderText("Nombre del proyecto (opcional)")
        self.empresa_combo = QComboBox()
        for e in empresas:
            self.empresa_combo.addItem(e["nombre"], e["id"])
        idx = self.empresa_combo.findData(empresa_actual["id"]) if empresa_actual else -1
        self.empresa_combo.setCurrentIndex(max(idx, 0))
        self.empresa_combo.currentIndexChanged.connect(lambda *_: self._cambio_empresa())
        self.cliente_combo = QComboBox()
        for cl in clientes:
            self.cliente_combo.addItem(cl["nombre"], cl["id"])
        self.cliente_combo.setCurrentIndex(max(self.cliente_combo.findData(cliente_id), 0))
        self._cliente_inicial = cliente_id
        self.cliente_combo.setEnabled(editable)            # el editor solo es editable con la cotización en borrador
        form.addRow("Cliente:", self.cliente_combo)
        form.addRow("Proyecto:", self.proyecto_edit)
        form.addRow("Empresa que cotiza:", self.empresa_combo)
        layout.addLayout(form)

        # --- ítems
        layout.addWidget(self._seccion("Detalle de ítems"))
        barra = QHBoxLayout()
        self.btn_grupo = boton("Agregar grupo", "folder-plus")
        self.btn_item = boton("Agregar ítem", "plus")
        self.btn_subitem = boton("Agregar sub-ítem", "subitem")
        self.btn_subir = boton("", "arrow-up", tooltip="Mover arriba")
        self.btn_bajar = boton("", "arrow-down", tooltip="Mover abajo")
        self.btn_texto = boton("Editar texto", "edit", tooltip="Editar la descripción con formato (F2 o doble clic)")
        self.btn_ver_texto = boton("Ocultar texto", "eye", tooltip="Muestra u oculta el detalle de las descripciones en la tabla (solo la primera línea)")
        self.btn_ver_texto.setCheckable(True)
        self.btn_ver_texto.setChecked(True)
        self.btn_quitar = boton("Quitar", "trash", "peligro")
        self.btn_itbms = boton("ITBMS", "percent")
        menu = QMenu(self.btn_itbms)
        menu.addAction("Aplicar ITBMS a todos los ítems", lambda: self._itbms_todos(True))
        menu.addAction("Quitar ITBMS de todos los ítems", lambda: self._itbms_todos(False))
        self.btn_itbms.setMenu(menu)
        self.btn_grupo.clicked.connect(self.agregar_grupo)
        self.btn_item.clicked.connect(self.agregar_item)
        self.btn_subitem.clicked.connect(self.agregar_subitem)
        self.btn_subir.clicked.connect(lambda: self.mover(-1))
        self.btn_bajar.clicked.connect(lambda: self.mover(1))
        self.btn_quitar.clicked.connect(self.quitar)
        self.btn_texto.clicked.connect(lambda: self.editar_descripcion())
        self.btn_ver_texto.toggled.connect(self._alternar_texto)
        for b in (self.btn_grupo, self.btn_item, self.btn_subitem, self.btn_texto, self.btn_ver_texto, self.btn_subir, self.btn_bajar):
            barra.addWidget(b)
        barra.addStretch()
        barra.addWidget(self.btn_itbms)
        barra.addWidget(self.btn_quitar)
        layout.addLayout(barra)

        barra2 = QHBoxLayout()
        self.btn_biblioteca = boton("Desde biblioteca", "book", tooltip="Insertar conceptos guardados")
        self.btn_guardar_biblioteca = boton("Guardar en biblioteca", "download",
                                            tooltip="Guarda el ítem (o los sub-ítems del grupo) para reutilizarlos")
        self.btn_apu = boton("Análisis de precio", "calculator",
                             tooltip="Análisis de precio unitario del ítem «mano de obra y material» seleccionado")
        self.btn_resumen = boton("Resumen", "receipt", tooltip="Costos directos, mano de obra, servicios, administración, utilidad y total")
        self.btn_resumen.clicked.connect(self.ver_resumen)
        self.btn_coef = boton("Coeficientes e indirectos", "sliders")
        self.btn_biblioteca.clicked.connect(self.desde_biblioteca)
        self.btn_guardar_biblioteca.clicked.connect(self.guardar_en_biblioteca)
        self.btn_apu.clicked.connect(self.abrir_apu)
        self.btn_coef.clicked.connect(self.ajustes_apu)
        for b in (self.btn_biblioteca, self.btn_guardar_biblioteca):
            barra2.addWidget(b)
        barra2.addStretch()
        for b in (self.btn_resumen, self.btn_apu, self.btn_coef):
            barra2.addWidget(b)
        layout.addLayout(barra2)

        self.tabla = tabla_estandar(["Ítem", "Descripción", "Tipo", "Ud.", "Cantidad", "Precio unitario", "Importe", "ITBMS"])
        self.tabla.setMinimumHeight(240)
        self.tabla.setWordWrap(True)
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla.setVerticalScrollMode(QTableWidget.ScrollPerPixel)      # una fila muy alta se puede recorrer completa
        self.tabla.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabla.customContextMenuRequested.connect(self._menu_contextual)
        self.tabla.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed
                                   | QTableWidget.AnyKeyPressed if editable else QTableWidget.NoEditTriggers)
        self.tabla.setItemDelegateForColumn(COL_DESC, TextoRicoDelegate(self.tabla))
        h = self.tabla.horizontalHeader()
        h.setSectionResizeMode(COL_COD, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(COL_DESC, QHeaderView.Stretch)
        for c, ancho in ((COL_TIPO, 150), (COL_UD, 64), (COL_CANT, 90), (COL_PRECIO, 135), (COL_IMPORTE, 135), (COL_ITBMS, 66)):
            h.setSectionResizeMode(c, QHeaderView.Fixed)
            self.tabla.setColumnWidth(c, ancho)
        self.tabla.itemChanged.connect(self._al_editar_linea)
        self.tabla.cellDoubleClicked.connect(self._doble_clic)
        QShortcut(QKeySequence(Qt.Key_F2), self.tabla, activated=self.editar_descripcion)
        # el alto de cada fila depende del ancho de la descripción: se recalcula al cambiar el ancho
        h.sectionResized.connect(lambda *_: self.tabla.resizeRowsToContents())
        layout.addWidget(self.tabla, 3)

        # --- costos adicionales
        fila = QHBoxLayout()
        fila.addWidget(self._seccion("Costos adicionales (administración, utilidad, imprevistos…)"))
        fila.addStretch()
        self.btn_cargo = boton("Agregar costo", "plus")
        menu_c = QMenu(self.btn_cargo)
        for nombre in PRESETS_CARGO:
            menu_c.addAction(nombre, lambda n=nombre: self.agregar_cargo("" if n == "Otro…" else n))
        self.btn_cargo.setMenu(menu_c)
        self.btn_quitar_cargo = boton("Quitar costo", "trash", "peligro")
        self.btn_quitar_cargo.clicked.connect(self.quitar_cargo)
        fila.addWidget(self.btn_cargo)
        fila.addWidget(self.btn_quitar_cargo)
        self.btn_ver_cargos = self._boton_seccion(fila, lambda v: self.tabla_cargos.setVisible(v)
                                                  or self.btn_cargo.setVisible(v) or self.btn_quitar_cargo.setVisible(v))
        layout.addLayout(fila)
        self.tabla_cargos = tabla_estandar(["Concepto", "Tipo", "Valor", "Monto", "ITBMS", "Se aplica sobre", "Diluir"])
        self.tabla_cargos.setFixedHeight(150)
        self.tabla_cargos.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed
                                          | QTableWidget.AnyKeyPressed if editable else QTableWidget.NoEditTriggers)
        hc = self.tabla_cargos.horizontalHeader()
        hc.setSectionResizeMode(CARGO_CONCEPTO, QHeaderView.Stretch)
        for c, ancho in ((CARGO_TIPO, 150), (CARGO_VALOR, 110), (CARGO_MONTO, 130), (CARGO_ITBMS, 64),
                         (CARGO_BASE, 230), (CARGO_DILUIR, 70)):
            hc.setSectionResizeMode(c, QHeaderView.Fixed)
            self.tabla_cargos.setColumnWidth(c, ancho)
        self.tabla_cargos.itemChanged.connect(self._al_editar_cargo)
        self.tabla_cargos.cellDoubleClicked.connect(self._doble_clic_cargo)
        layout.addWidget(self.tabla_cargos)

        self.lbl_totales = QLabel()
        self.lbl_totales.setObjectName("totales")
        self.lbl_totales.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        # --- notas
        fila_notas = QHBoxLayout()
        fila_notas.addWidget(self._seccion("Notas / Términos y condiciones"))
        fila_notas.addStretch()
        self.btn_plantilla = boton("Insertar plantilla", "file-plus")
        self.btn_plantilla.clicked.connect(self.insertar_plantilla)
        fila_notas.addWidget(self.btn_plantilla)
        self.btn_ver_notas = self._boton_seccion(
            fila_notas, lambda v: self.cuerpo_notas.setVisible(v) or self.btn_plantilla.setVisible(v))
        layout.addLayout(fila_notas)
        self.cuerpo_notas = QWidget()
        cuerpo = QVBoxLayout(self.cuerpo_notas)
        cuerpo.setContentsMargins(0, 0, 0, 0)
        fila_titulo = QHBoxLayout()
        fila_titulo.addWidget(QLabel("Título del bloque:"))
        self.titulo_notas_edit = QLineEdit(titulo_notas)
        self.titulo_notas_edit.setPlaceholderText(db.TITULO_NOTAS)
        fila_titulo.addWidget(self.titulo_notas_edit, 1)
        cuerpo.addLayout(fila_titulo)
        self.notas_edit = QPlainTextEdit()
        self.notas_edit.setPlainText(notas)
        self.notas_edit.setPlaceholderText("Alcance, exclusiones y condiciones que saldrán en el PDF…")
        self.notas_edit.setMinimumHeight(self.notas_edit.fontMetrics().lineSpacing() * 6 + 20)
        cuerpo.addWidget(self.notas_edit)
        layout.addWidget(self.cuerpo_notas)
        self.btn_ver_cargos.setChecked(False)      # costos adicionales y notas empiezan contraídos (más espacio a los ítems)
        self.btn_ver_notas.setChecked(False)

        # --- botones
        pie = QWidget()
        pie.setObjectName("pagina")
        pv = QVBoxLayout(pie)
        pv.setContentsMargins(20, 6, 20, 12)
        pv.addWidget(self.lbl_totales)
        lp = QHBoxLayout()
        pv.addLayout(lp)
        self.btn_cancelar = boton("Cancelar" if editable else "Cerrar", "x")
        self.btn_guardar = boton("Guardar", "save", "primario")
        self.btn_vista = boton("Guardar y vista previa" if editable else "Vista previa", "eye",
                               tooltip="Muestra cómo saldrá la cotización en el PDF" + (
                                   " (guarda primero los cambios)" if editable else ""))
        self.numero = numero
        self.btn_cancelar.clicked.connect(self.reject)
        self.btn_guardar.clicked.connect(self.guardar)
        self.btn_vista.clicked.connect(self.vista_previa)
        lp.addWidget(self.btn_vista)
        lp.addStretch()
        lp.addWidget(self.btn_cancelar)
        if editable:
            lp.addWidget(self.btn_guardar)
        raiz.addWidget(pie)

        if not editable:
            for w in (self.btn_grupo, self.btn_item, self.btn_subitem, self.btn_subir, self.btn_bajar,
                      self.btn_quitar, self.btn_itbms, self.btn_cargo, self.btn_quitar_cargo, self.btn_plantilla,
                      self.btn_biblioteca):
                w.setEnabled(False)
            self.notas_edit.setReadOnly(True)
            self.titulo_notas_edit.setReadOnly(True)
            self.proyecto_edit.setReadOnly(True)
            self.empresa_combo.setEnabled(False)

        self._cambio_empresa(render=False)
        self._render_lineas()
        self._render_cargos()

    # ------------------------------------------------------------------ utilidades
    @staticmethod
    def _seccion(texto):
        l = QLabel(texto)
        l.setObjectName("seccion")
        return l

    def _cambio_empresa(self, render=True):
        """La tasa de ITBMS es la de la empresa elegida; con tasa 0 se ocultan las columnas de ITBMS."""
        conn = db.get_connection()
        emp = db.obtener_empresa(self.empresa_combo.currentData(), conn)
        conn.close()
        self.tasa = (emp["itbms_tasa"] / 100) if emp else 0.0
        self.tabla.setColumnHidden(COL_ITBMS, self.tasa == 0)
        self.tabla_cargos.setColumnHidden(CARGO_ITBMS, self.tasa == 0)
        if render:
            self._refrescar_derivados()

    @staticmethod
    def _limpiar_widgets(tabla, columna):
        """Oculta y retira los combos de una columna antes de volver a dibujarla (evita restos visibles)."""
        for r in range(tabla.rowCount()):
            w = tabla.cellWidget(r, columna)
            if w is not None:
                w.hide()
                tabla.removeCellWidget(r, columna)

    def _fila_actual(self):
        f = self.tabla.currentRow()
        return f if 0 <= f < len(self.lineas) else -1

    def _hijos(self, i):
        """Cantidad de sub-ítems que cuelgan de la línea i."""
        n = 0
        while i + 1 + n < len(self.lineas) and self.lineas[i + 1 + n].nivel == 1:
            n += 1
        return n

    def _padre(self, i):
        while i >= 0 and self.lineas[i].nivel == 1:
            i -= 1
        return i

    # ------------------------------------------------------------------ render ítems
    def _render_lineas(self, seleccionar=None):
        self._cargando = True
        self._invalidos = {k: v for k, v in self._invalidos.items() if k[0] != "l"}
        self._limpiar_widgets(self.tabla, COL_TIPO)
        self.tabla.setRowCount(len(self.lineas))
        negrita = QFont()
        negrita.setBold(True)
        for i, l in enumerate(self.lineas):
            cod = QTableWidgetItem()
            cod.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            plano = texto_rico.a_texto_plano(texto_rico.con_titulo(l.titulo, l.descripcion))
            visible = not self._texto_oculto(l)
            primera, _, resto = plano.partition("\n")
            desc = QTableWidgetItem(plano if visible or not resto else primera + " …")
            completo = texto_rico.con_titulo(l.titulo, l.descripcion)
            parrafos = texto_rico.parsear(completo)
            if not visible and len(parrafos) > 1:
                parrafos = [texto_rico.Parrafo(parrafos[0].tipo, parrafos[0].tramos + [texto_rico.Tramo(" …")])]
            desc.setData(ROL_HTML, texto_rico.serializar(parrafos))     # lo dibuja con formato TextoRicoDelegate
            desc.setToolTip(plano if not visible and resto else
                            "Doble clic o F2 para editar el texto con formato" if self.editable else "")
            desc.setIcon(iconos.icono("folder", estilo.AZUL, 18) if l.es_grupo else
                         iconos.icono("subitem", estilo.APAGADO, 18) if l.nivel == 1 else iconos.icono("file", estilo.APAGADO, 18))
            tipo = QTableWidgetItem()
            ud = QTableWidgetItem("" if l.es_grupo else l.unidad)
            ud.setTextAlignment(Qt.AlignCenter)
            cant = QTableWidgetItem("" if l.es_grupo else f"{l.cantidad:g}")
            precio = QTableWidgetItem("" if l.es_grupo else f"{l.precio:,.2f}")
            importe = QTableWidgetItem()
            itbms = QTableWidgetItem()
            for it in (cant, precio, importe):
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            importe.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
            itbms.setFlags(base | (Qt.ItemIsUserCheckable if self.editable else Qt.NoItemFlags))
            itbms.setTextAlignment(Qt.AlignCenter)
            tipo.setFlags(base)
            if l.usa_apu:        # el precio sale del análisis de precio unitario
                precio.setFlags(base)
                precio.setForeground(QBrush(QColor(estilo.AZUL)))
                precio.setToolTip("Calculado con el análisis de precio unitario (doble clic para abrirlo)")
            if l.es_grupo:
                for it in (ud, cant, precio):
                    it.setFlags(base)
                for it in (cod, desc, tipo, ud, cant, precio, importe, itbms):
                    it.setBackground(FONDO_GRUPO)
                    it.setFont(negrita)
            desc.setFlags(base)      # la descripción se edita en su propia ventana
            if not self.editable:
                for it in (ud, cant, precio):
                    it.setFlags(base)
            for c, it in enumerate((cod, desc, tipo, ud, cant, precio, importe, itbms)):
                self.tabla.setItem(i, c, it)
            if not l.es_grupo:
                combo = combo_modalidad(corto=True)
                combo.setCurrentIndex(combo.findData(l.modalidad))
                combo.setEnabled(self.editable)
                combo.currentIndexChanged.connect(lambda _i, fila=i, cb=combo: self._cambio_modalidad(fila, cb))
                envoltorio = QWidget()          # centra el combo en la fila sin estirarlo
                envoltorio.setStyleSheet("background: transparent;")
                lc = QHBoxLayout(envoltorio)
                lc.setContentsMargins(6, 0, 6, 0)
                lc.addWidget(combo, 0, Qt.AlignVCenter)
                envoltorio.combo = combo
                self.tabla.setCellWidget(i, COL_TIPO, envoltorio)
        self._cargando = False
        self._refrescar_derivados()
        self.tabla.resizeRowsToContents()
        if seleccionar is not None and 0 <= seleccionar < len(self.lineas):
            self.tabla.setCurrentCell(seleccionar, COL_DESC)

    def _refrescar_derivados(self):
        """Actualiza código, importe y casillas de ITBMS (celdas calculadas) y los totales."""
        self._cargando = True
        self.costo_directo, self.coef_ind = calculo.aplicar_apu(self.lineas, self.cfg)   # precios de los APU
        t = calculo.calcular(self.lineas, self.cargos, self.tasa, self.cfg)        # reparte los costos que se diluyen
        cods, imps = calculo.codigos(self.lineas), calculo.importes(self.lineas)
        for i, l in enumerate(self.lineas):
            self.tabla.item(i, COL_COD).setText(cods[i])
            if l.usa_apu:
                self.tabla.item(i, COL_PRECIO).setText(f"{l.precio:,.2f}")
            self.tabla.item(i, COL_IMPORTE).setText(_dinero(imps[i]))
            self.tabla.item(i, COL_IMPORTE).setToolTip(
                f"Incluye {_dinero(l.ajuste)} de costos adicionales diluidos en este ítem" if l.ajuste else "")
            marca = self.tabla.item(i, COL_ITBMS)
            if l.es_grupo:
                hijos = self.lineas[i + 1:i + 1 + self._hijos(i)]
                marcados = sum(1 for h in hijos if h.aplica_itbms)
                estado = (Qt.Unchecked if not hijos or marcados == 0 else
                          Qt.Checked if marcados == len(hijos) else Qt.PartiallyChecked)
                marca.setCheckState(estado)
                if not hijos:
                    marca.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                elif self.editable:
                    marca.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            else:
                marca.setCheckState(Qt.Checked if l.aplica_itbms else Qt.Unchecked)
        montos = {id(c): m for c, m in t.cargos + t.diluidos}
        for c, cargo in enumerate(self.cargos):
            m = self.tabla_cargos.item(c, CARGO_MONTO)
            if m is not None:
                m.setText(_dinero(montos.get(id(cargo), 0.0)))
        self._cargando = False
        self._actualizar_totales()

    def _actualizar_totales(self):
        t = calculo.calcular(self.lineas, self.cargos, self.tasa, self.cfg)
        filas = [f"Subtotal ítems: <b>{_dinero(t.subtotal)}</b>"]
        for cargo, monto in t.cargos:
            etiqueta = f"{cargo.concepto or 'Costo'} ({cargo.valor:g}%)" if cargo.tipo == "porcentaje" else (cargo.concepto or "Costo")
            filas.append(f"{etiqueta}: {_dinero(monto)}")
        if t.diluidos:
            filas.append("Costos diluidos en los ítems: " + _dinero(sum(m for _c, m in t.diluidos)))
        filas.append("ITBMS (exento): " + _dinero(0) if self.tasa == 0 else
                     f"ITBMS ({self.tasa:.0%}) sobre {_dinero(t.base_itbms)}: {_dinero(t.itbms)}")
        filas.append(f"<span style='font-size:16px'><b>Total: {_dinero(t.total)}</b></span>")
        self.lbl_totales.setText("&nbsp;&nbsp;·&nbsp;&nbsp;".join(filas))

    # ------------------------------------------------------------------ edición de ítems
    def _al_editar_linea(self, item):
        if self._cargando:
            return
        if not self.editable:
            self._render_lineas()
            return
        r, c = item.row(), item.column()
        if r >= len(self.lineas):
            return
        l = self.lineas[r]
        if c == COL_DESC:
            l.descripcion = item.text().strip()
            self.tabla.resizeRowToContents(r)
        elif c == COL_UD:
            l.unidad = item.text().strip()
        elif c in (COL_CANT, COL_PRECIO):
            valor = parsear_numero(item.text())
            if valor is None:
                self._invalidos[("l", r, c)] = item.text()
                item.setForeground(ROJO)
            else:
                self._invalidos.pop(("l", r, c), None)
                item.setForeground(QBrush(QColor(estilo.TEXTO)))
                if c == COL_CANT:
                    l.cantidad = valor
                else:
                    l.precio = valor
                self._cargando = True
                item.setText(f"{valor:g}" if c == COL_CANT else f"{valor:,.2f}")
                self._cargando = False
        elif c == COL_ITBMS:
            marcado = item.checkState() != Qt.Unchecked
            if l.es_grupo:
                for h in range(r + 1, r + 1 + self._hijos(r)):
                    self.lineas[h].aplica_itbms = marcado
            else:
                l.aplica_itbms = marcado
        self._refrescar_derivados()

    def _itbms_todos(self, valor):
        for l in self.lineas:
            l.aplica_itbms = valor
        for c in self.cargos:
            c.aplica_itbms = valor
        self._render_lineas(self._fila_actual())
        self._render_cargos()

    # ------------------------------------------------------------------ estructura de ítems
    def _insertar(self, pos, linea):
        self.lineas.insert(pos, linea)
        self._render_lineas(pos)
        self.tabla.setCurrentCell(pos, COL_DESC)

    def agregar_grupo(self):
        self._insertar(len(self.lineas), Linea("grupo", 0))

    def agregar_item(self):
        self._insertar(len(self.lineas), Linea("item", 0))

    def agregar_subitem(self):
        i = self._fila_actual()
        g = self._padre(i) if i >= 0 else -1
        if g < 0 or not self.lineas[g].es_grupo:
            QMessageBox.information(self, "Sub-ítem", "Selecciona un grupo (o uno de sus sub-ítems) para agregarle un sub-ítem.")
            return
        self._insertar(g + 1 + self._hijos(g), Linea("item", 1))

    def quitar(self):
        i = self._fila_actual()
        if i < 0:
            return
        n = self._hijos(i) if self.lineas[i].nivel == 0 else 0
        if n:
            r = QMessageBox.question(
                self, "Quitar grupo", f"El grupo tiene {n} sub-ítem(s); también se quitarán. ¿Continuar?")
            if r != QMessageBox.Yes:
                return
        del self.lineas[i:i + 1 + n]
        self._render_lineas(min(i, len(self.lineas) - 1))

    def mover(self, delta):
        """Sube/baja un grupo completo (con sus sub-ítems) o un sub-ítem dentro de su grupo."""
        i = self._fila_actual()
        if i < 0:
            return
        L = self.lineas
        if L[i].nivel == 1:
            j = i + delta
            if 0 <= j < len(L) and L[j].nivel == 1:
                L[i], L[j] = L[j], L[i]
                self._render_lineas(j)
            return
        bloques, ini = [], 0
        while ini < len(L):
            fin = ini + self._hijos(ini)
            bloques.append((ini, fin))
            ini = fin + 1
        k = next(n for n, (a, b) in enumerate(bloques) if a == i)
        k2 = k + delta
        if not 0 <= k2 < len(bloques):
            return
        bloques[k], bloques[k2] = bloques[k2], bloques[k]
        nuevo = [x for a, b in bloques for x in L[a:b + 1]]
        pos = sum(b - a + 1 for a, b in bloques[:k2])
        self.lineas[:] = nuevo
        self._render_lineas(pos)

    # ------------------------------------------------------------------ modalidad, APU y biblioteca
    def _cambio_modalidad(self, fila, combo):
        if not (0 <= fila < len(self.lineas)) or not self.editable:
            return
        l = self.lineas[fila]
        nueva = combo.currentData()
        if nueva == l.modalidad:
            return
        if nueva == calculo.OBRA:
            l.modalidad, l.apu = calculo.OBRA, Apu()
        else:
            if l.apu and l.apu.insumos:
                r = QMessageBox.question(
                    self, "Servicio profesional",
                    "Al pasar a servicio profesional se descarta el análisis de precio unitario; "
                    "el precio actual queda como precio fijo. ¿Continuar?")
                if r != QMessageBox.Yes:
                    combo.blockSignals(True)
                    combo.setCurrentIndex(combo.findData(l.modalidad))
                    combo.blockSignals(False)
                    return
            l.modalidad, l.apu = calculo.SERVICIO, None
        self._render_lineas(fila)

    def _boton_seccion(self, fila, mostrar):
        """Botón que contrae o expande el contenido de una sección (nace expandido; quien lo crea puede contraerlo)."""
        b = boton("Contraer", "arrow-up", tooltip="Contraer o expandir esta sección")
        b.setCheckable(True)
        b.setChecked(True)

        def alternar(visible):
            b.setText("Contraer" if visible else "Expandir")
            b.setIcon(iconos.icono("arrow-up" if visible else "arrow-down", estilo.AZUL_OSCURO, 18))
            mostrar(visible)
        b.toggled.connect(alternar)
        fila.addWidget(b)
        return b

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.tabla.resizeRowsToContents)    # al mostrarse ya se conoce el ancho real de la descripción

    @staticmethod
    def _sin_texto(l) -> bool:
        return not (l.titulo or "").strip() and texto_rico.es_vacio(l.descripcion)

    def _texto_oculto(self, l) -> bool:
        return self._ocultas.get(id(l), not self.btn_ver_texto.isChecked())

    def alternar_texto_fila(self, i=None):
        """Oculta o muestra el detalle de la descripción de un solo ítem."""
        i = self._fila_actual() if i is None else i
        if 0 <= i < len(self.lineas):
            l = self.lineas[i]
            self._ocultas[id(l)] = not self._texto_oculto(l)
            self._render_lineas(i)

    def duplicar_item(self, i=None):
        """Duplica el ítem (o el grupo con sus sub-ítems) justo debajo."""
        i = self._fila_actual() if i is None else i
        if not (0 <= i < len(self.lineas)) or not self.editable:
            return
        n = self._hijos(i) if self.lineas[i].es_grupo else 0
        copias = [replace(l, apu=l.apu.copia() if l.apu else None) for l in self.lineas[i:i + 1 + n]]
        self.lineas[i + 1 + n:i + 1 + n] = copias
        self._render_lineas(i + 1 + n)

    def alternar_itbms_fila(self, i):
        if 0 <= i < len(self.lineas) and self.editable:
            self.lineas[i].aplica_itbms = not self.lineas[i].aplica_itbms
            self._render_lineas(i)

    # ------------------------------------------------------------------ clic derecho
    def _menu_contextual(self, pos):
        fila = self.tabla.rowAt(pos.y())
        if fila >= 0:
            self.tabla.setCurrentCell(fila, COL_DESC)
        self._mostrar_menu(self.construir_menu(fila), self.tabla.viewport().mapToGlobal(pos))

    @staticmethod
    def _mostrar_menu(menu, punto_global):
        menu.exec(punto_global)

    def construir_menu(self, fila=-1) -> QMenu:
        """Menú del clic derecho: acciones para el ítem bajo el cursor (o para agregar, si se pulsa fuera de las filas)."""
        menu = QMenu(self)
        ico = lambda nombre, color=estilo.AZUL_OSCURO: iconos.icono(nombre, color, 18)
        hay = 0 <= fila < len(self.lineas)
        ed = self.editable
        if hay:
            l = self.lineas[fila]
            menu.addAction(ico("edit"), "Editar título y texto…", lambda *_: self.editar_descripcion(fila))
            oculto = self._texto_oculto(l)
            menu.addAction(ico("eye"), "Mostrar texto completo" if oculto else "Ocultar texto",
                           lambda *_: self.alternar_texto_fila(fila))
            menu.addSeparator()
            menu.addAction(ico("copy"), "Duplicar grupo con sus sub-ítems" if l.es_grupo and self._hijos(fila) else "Duplicar",
                           lambda *_: self.duplicar_item(fila)).setEnabled(ed)
        if ed:
            nuevo = menu.addMenu(ico("plus"), "Agregar")
            nuevo.addAction(ico("plus"), "Ítem", lambda *_: self.agregar_item())
            nuevo.addAction(ico("folder-plus"), "Grupo", lambda *_: self.agregar_grupo())
            sub = nuevo.addAction(ico("subitem"), "Sub-ítem", lambda *_: self.agregar_subitem())
            sub.setEnabled(hay and self._padre(fila) >= 0 and self.lineas[self._padre(fila)].es_grupo)
            nuevo.addAction(ico("book"), "Desde la biblioteca…", lambda *_: self.desde_biblioteca())
        if hay:
            if ed:
                menu.addSeparator()
                menu.addAction(ico("arrow-up"), "Subir", lambda *_: self.mover(-1))
                menu.addAction(ico("arrow-down"), "Bajar", lambda *_: self.mover(1))
                if not l.es_grupo:
                    menu.addAction(ico("percent"), "Quitar ITBMS de este ítem" if l.aplica_itbms else "Aplicar ITBMS a este ítem",
                                   lambda *_: self.alternar_itbms_fila(fila))
            if not l.es_grupo:
                menu.addSeparator()
                menu.addAction(ico("calculator"), "Análisis de precio…", lambda *_: self.abrir_apu()).setEnabled(l.usa_apu)
                menu.addAction(ico("download"), "Guardar en biblioteca…", lambda *_: self.guardar_en_biblioteca()).setEnabled(ed)
            elif ed:
                menu.addSeparator()
                menu.addAction(ico("download"), "Guardar sub-ítems en biblioteca…", lambda *_: self.guardar_en_biblioteca())
            if ed:
                menu.addSeparator()
                menu.addAction(ico("trash", estilo.ROJO), "Eliminar", lambda *_: self.quitar())
        return menu

    def ver_resumen(self):
        mostrar_resumen(self, self.lineas, self.cargos, self.tasa, self.cfg, f"Resumen · {self.windowTitle()}")

    def _alternar_texto(self, visible):
        self._ocultas.clear()
        self.btn_ver_texto.setText("Ocultar texto" if visible else "Ver texto")
        self._render_lineas(self._fila_actual())

    def editar_descripcion(self, fila=None):
        """Abre el editor con formato de la descripción del ítem (o grupo) seleccionado."""
        i = self._fila_actual() if fila is None else fila
        if not (0 <= i < len(self.lineas)):
            return
        l = self.lineas[i]
        dlg = EditorTextoDialog(l.descripcion, f"Descripción · ítem {calculo.codigos(self.lineas)[i]}",
                                not self.editable, self, titulo_item=l.titulo)
        if self._ejecutar(dlg) and self.editable:
            l.descripcion = dlg.texto()
            l.titulo = dlg.titulo_item()
            self._render_lineas(i)

    @staticmethod
    def _ejecutar(dlg):
        return dlg.exec()

    def _doble_clic(self, fila, col):
        if col == COL_DESC:
            self.editar_descripcion(fila)
            return
        if col == COL_PRECIO and 0 <= fila < len(self.lineas) and self.lineas[fila].usa_apu:
            self.abrir_apu()

    def abrir_apu(self):
        i = self._fila_actual()
        if i < 0 or self.lineas[i].es_grupo:
            QMessageBox.information(self, "Análisis de precio", "Selecciona un ítem de «mano de obra y material».")
            return
        l = self.lineas[i]
        if not l.usa_apu:
            QMessageBox.information(
                self, "Análisis de precio",
                "Este ítem es un servicio profesional (precio fijo). Cambia su tipo a «Mano de obra y material» "
                "para analizar su precio unitario.")
            return
        dlg = ApuDialog(texto_rico.a_texto_plano(texto_rico.con_titulo(l.titulo, l.descripcion)), l.unidad, l.apu or Apu(), self.cfg, self.coef_ind, self.editable, self)
        if dlg.exec() and self.editable:
            l.apu = dlg.apu
            self._render_lineas(i)

    def ajustes_apu(self):
        dlg = AjustesApuDialog(self.cfg, self.costo_directo, self.editable, self)
        if dlg.exec() and self.editable:
            self.cfg = dlg.cfg
            self._refrescar_derivados()

    def desde_biblioteca(self):
        """Inserta conceptos de la biblioteca: en el grupo seleccionado (como sub-ítems) o al final."""
        dlg = SelectorConceptosDialog(self)
        if not dlg.exec():
            return
        conceptos = dlg.seleccion()
        if not conceptos:
            return
        i = self._fila_actual()
        g = self._padre(i) if i >= 0 else -1
        en_grupo = g >= 0 and self.lineas[g].es_grupo
        pos = g + 1 + self._hijos(g) if en_grupo else len(self.lineas)
        nuevas = [db.linea_desde_concepto(c, 1.0, 1 if en_grupo else 0) for c in conceptos]
        self.lineas[pos:pos] = nuevas
        self._render_lineas(pos)

    def guardar_en_biblioteca(self):
        """Guarda el ítem seleccionado (o los sub-ítems del grupo) como conceptos reutilizables."""
        i = self._fila_actual()
        if i < 0:
            QMessageBox.information(self, "Biblioteca", "Selecciona un ítem (o un grupo) para guardarlo.")
            return
        if self.lineas[i].es_grupo:
            candidatos = [(l, texto_rico.con_titulo(self.lineas[i].titulo, self.lineas[i].descripcion)) for l in self.lineas[i + 1:i + 1 + self._hijos(i)]]
        else:
            g = self._padre(i)
            candidatos = [(self.lineas[i], texto_rico.con_titulo(self.lineas[g].titulo, self.lineas[g].descripcion) if self.lineas[i].nivel == 1 and g >= 0 else "")]
        candidatos = [(l, texto_rico.a_texto_plano(cat)) for l, cat in candidatos if not self._sin_texto(l)]
        if not candidatos:
            QMessageBox.information(self, "Biblioteca", "Escribe primero la descripción del ítem.")
            return
        conn = db.get_connection()
        bibliotecas = db.listar_bibliotecas(conn)
        destino = bibliotecas[0]["id"]
        if len(bibliotecas) > 1:                       # con varias bibliotecas se pregunta en cuál guardar
            nombres = [b["nombre"] for b in bibliotecas]
            elegido, ok = QInputDialog.getItem(self, "Guardar en biblioteca", "Guardar en:", nombres, 0, False)
            if not ok:
                conn.close()
                return
            destino = bibliotecas[nombres.index(elegido)]["id"]
        guardados = 0
        for l, cat in candidatos:
            concepto = db.concepto_desde_linea(l, cat)
            concepto.biblioteca_id = destino
            existente = db.buscar_concepto(concepto.descripcion, concepto.unidad, conn, destino)
            if existente:
                r = QMessageBox.question(
                    self, "Biblioteca",
                    f"Ya existe «{concepto.descripcion}» en la biblioteca. ¿Actualizarlo con los datos de este ítem?")
                if r != QMessageBox.Yes:
                    continue
                concepto.id = existente.id
                concepto.categoria = concepto.categoria or existente.categoria
            db.guardar_concepto(concepto, conn)
            guardados += 1
        conn.close()
        if guardados:
            QMessageBox.information(self, "Biblioteca", f"Se guardó {guardados} concepto(s) en la biblioteca.")

    # ------------------------------------------------------------------ costos adicionales
    def _render_cargos(self):
        self._cargando = True
        self._invalidos = {k: v for k, v in self._invalidos.items() if k[0] != "c"}
        self._limpiar_widgets(self.tabla_cargos, CARGO_TIPO)
        self.tabla_cargos.setRowCount(len(self.cargos))
        for i, c in enumerate(self.cargos):
            concepto = QTableWidgetItem(c.concepto)
            valor = QTableWidgetItem(f"{c.valor:,.2f}")
            valor.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            monto = QTableWidgetItem()
            monto.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            monto.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            marca = QTableWidgetItem()
            marca.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | (Qt.ItemIsUserCheckable if self.editable else Qt.NoItemFlags))
            marca.setCheckState(Qt.Checked if c.aplica_itbms else Qt.Unchecked)
            if not self.editable:
                concepto.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                valor.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.tabla_cargos.setItem(i, CARGO_CONCEPTO, concepto)
            self.tabla_cargos.setItem(i, CARGO_VALOR, valor)
            self.tabla_cargos.setItem(i, CARGO_MONTO, monto)
            self.tabla_cargos.setItem(i, CARGO_ITBMS, marca)
            base = QTableWidgetItem(calculo.nombre_base(c).capitalize())
            base.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            base.setToolTip("Doble clic para elegir sobre qué actúa este costo" if self.editable else "")
            diluir = QTableWidgetItem()
            diluir.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | (Qt.ItemIsUserCheckable if self.editable else Qt.NoItemFlags))
            diluir.setCheckState(Qt.Checked if c.diluir else Qt.Unchecked)
            diluir.setToolTip("Marcado: el costo se reparte en el precio de los ítems y no sale como línea aparte")
            diluir.setTextAlignment(Qt.AlignCenter)
            self.tabla_cargos.setItem(i, CARGO_BASE, base)
            self.tabla_cargos.setItem(i, CARGO_DILUIR, diluir)
            combo = QComboBox()
            combo.addItem("Porcentaje", "porcentaje")
            combo.addItem("Monto fijo", "monto")
            combo.setCurrentIndex(0 if c.tipo == "porcentaje" else 1)
            combo.setEnabled(self.editable)
            combo.setStyleSheet("QComboBox { margin: 4px 6px; padding: 2px 8px; border-radius: 6px; }")
            combo.currentIndexChanged.connect(lambda _i, fila=i, cb=combo: self._tipo_cargo(fila, cb))
            self.tabla_cargos.setCellWidget(i, CARGO_TIPO, combo)
        self._cargando = False
        self._refrescar_derivados()

    def _tipo_cargo(self, fila, combo):
        if 0 <= fila < len(self.cargos):
            self.cargos[fila].tipo = combo.currentData()
            self._refrescar_derivados()

    def _al_editar_cargo(self, item):
        if self._cargando:
            return
        if not self.editable:
            self._render_cargos()
            return
        r, c = item.row(), item.column()
        if r >= len(self.cargos):
            return
        cargo = self.cargos[r]
        if c == CARGO_CONCEPTO:
            cargo.concepto = item.text().strip()
        elif c == CARGO_VALOR:
            v = parsear_numero(item.text())
            if v is None:
                self._invalidos[("c", r, c)] = item.text()
                item.setForeground(ROJO)
            else:
                self._invalidos.pop(("c", r, c), None)
                item.setForeground(QBrush(QColor(estilo.TEXTO)))
                cargo.valor = v
                self._cargando = True
                item.setText(f"{v:,.2f}")
                self._cargando = False
        elif c == CARGO_ITBMS:
            cargo.aplica_itbms = item.checkState() == Qt.Checked
        elif c == CARGO_DILUIR:
            cargo.diluir = item.checkState() == Qt.Checked
        self._refrescar_derivados()

    def _doble_clic_cargo(self, fila, col):
        if col == CARGO_BASE and self.editable:
            self.elegir_base_cargo(fila)

    def elegir_base_cargo(self, fila):
        """Pregunta sobre qué actúa un costo adicional (todo el subtotal o ciertas categorías)."""
        if not (0 <= fila < len(self.cargos)):
            return
        dlg = BaseCargoDialog(self.cargos[fila], self)
        if self._ejecutar(dlg):
            self.cargos[fila].base = dlg.base()
            self._render_cargos()
            self.tabla_cargos.setCurrentCell(fila, CARGO_BASE)

    def agregar_cargo(self, concepto=""):
        self.cargos.append(Cargo(concepto, "porcentaje", 0.0, True))
        self._render_cargos()
        fila = len(self.cargos) - 1
        self.tabla_cargos.setCurrentCell(fila, CARGO_VALOR if concepto else CARGO_CONCEPTO)
        self.tabla_cargos.editItem(self.tabla_cargos.item(fila, CARGO_VALOR if concepto else CARGO_CONCEPTO))

    def quitar_cargo(self):
        f = self.tabla_cargos.currentRow()
        if 0 <= f < len(self.cargos):
            del self.cargos[f]
            self._render_cargos()

    # ------------------------------------------------------------------ notas
    def insertar_plantilla(self):
        """Inserta la plantilla por defecto; si ya hay texto pregunta si reemplazar o agregar."""
        conn = db.get_connection()
        plantilla = db.obtener_plantilla_notas(conn)
        conn.close()
        if self.notas_edit.toPlainText().strip():
            caja = QMessageBox(self)
            caja.setWindowTitle("Insertar plantilla")
            caja.setText("El cuadro ya tiene texto. ¿Qué deseas hacer con la plantilla?")
            btn_reemplazar = caja.addButton("Reemplazar", QMessageBox.DestructiveRole)
            btn_agregar = caja.addButton("Agregar al final", QMessageBox.AcceptRole)
            caja.addButton("Cancelar", QMessageBox.RejectRole)
            caja.exec()
            if caja.clickedButton() == btn_reemplazar:
                self.notas_edit.setPlainText(plantilla)
            elif caja.clickedButton() == btn_agregar:
                self.notas_edit.setPlainText(self.notas_edit.toPlainText().rstrip() + "\n\n" + plantilla)
            else:
                return
        else:
            self.notas_edit.setPlainText(plantilla)
        self.notas_edit.setFocus()

    # ------------------------------------------------------------------ guardar
    def _validar(self):
        """Devuelve (lineas, cargos, error). Descarta filas totalmente vacías."""
        if self._invalidos:
            (tipo, fila, _col), _txt = next(iter(self._invalidos.items()))
            donde = f"ítem {calculo.codigos(self.lineas)[fila]}" if tipo == "l" else f"costo adicional {fila + 1}"
            return None, None, f"En el {donde} hay un número no válido."
        cods = calculo.codigos(self.lineas)
        lineas = []
        for i, l in enumerate(self.lineas):
            vacia = self._sin_texto(l) and (l.es_grupo and not self._hijos(i) or
                                           not l.es_grupo and l.precio == 0)
            if vacia:
                continue
            if self._sin_texto(l):
                return None, None, f"Falta la descripción del ítem {cods[i]}."
            lineas.append(l)
        cargos = []
        for n, c in enumerate(self.cargos, 1):
            if not c.concepto and c.valor == 0:
                continue
            if not c.concepto:
                return None, None, f"Falta el concepto del costo adicional {n}."
            cargos.append(c)
        # un sub-ítem no puede quedar huérfano tras descartar filas
        if lineas and lineas[0].nivel == 1:
            lineas[0].nivel = 0
        return lineas, cargos, None

    def vista_previa(self):
        """Muestra la cotización como saldrá en el PDF; en modo edición guarda antes los cambios (sin cerrar)."""
        if self.editable and not self._guardar_en_db():
            return
        vista_previa(self, "cotizacion", self.cotizacion_id, self.numero)

    def guardar(self):
        if self._guardar_en_db():
            self.accept()

    def _guardar_en_db(self) -> bool:
        lineas, cargos, error = self._validar()
        if error:
            QMessageBox.warning(self, "Datos inválidos", error)
            return False
        conn = db.get_connection()
        if self.cliente_combo.currentData() is not None and self.cliente_combo.currentData() != self._cliente_inicial:
            db.cambiar_cliente_cotizacion(self.cotizacion_id, self.cliente_combo.currentData(), conn)
            self._cliente_inicial = self.cliente_combo.currentData()
        if self.empresa_combo.currentData() is not None:
            db.cambiar_empresa_cotizacion(self.cotizacion_id, self.empresa_combo.currentData(), conn)
        db.guardar_cotizacion(self.cotizacion_id, lineas, cargos, conn, tasa=self.tasa, cfg=self.cfg)
        db.guardar_notas(self.cotizacion_id, self.notas_edit.toPlainText().strip("\n"), conn)
        db.guardar_titulo_notas("cotizaciones", self.cotizacion_id, self.titulo_notas_edit.text(), conn)
        db.guardar_proyecto(self.cotizacion_id, self.proyecto_edit.text().strip(), conn)
        conn.close()
        return True
