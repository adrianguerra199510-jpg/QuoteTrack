"""Editor de una cotización: grupos y sub-ítems, ITBMS por línea, costos adicionales y notas."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMenu,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app import calculo, db, estilo, iconos, texto_rico
from app.calculo import Apu, Cargo, Linea
from app.ui_apu import AjustesApuDialog, ApuDialog
from app.ui_biblioteca import SelectorConceptosDialog, combo_modalidad
from app.ui_comun import boton, parsear_numero, tabla_estandar
from app.ui_texto import EditorTextoDialog
from app.ui_vista_previa import vista_previa

COL_COD, COL_DESC, COL_TIPO, COL_UD, COL_CANT, COL_PRECIO, COL_IMPORTE, COL_ITBMS = range(8)
CARGO_CONCEPTO, CARGO_TIPO, CARGO_VALOR, CARGO_MONTO, CARGO_ITBMS = range(5)
FONDO_GRUPO = QBrush(QColor("#E8EEFC"))
ROJO = QBrush(QColor(estilo.ROJO))
PRESETS_CARGO = ["Administración", "Utilidad", "Imprevistos", "Otro…"]


def _dinero(v: float) -> str:
    return f"B/. {v:,.2f}"


class ItemsDialog(QDialog):
    def __init__(self, cotizacion_id, numero, editable, parent=None):
        super().__init__(parent)
        self.cotizacion_id = cotizacion_id
        self.editable = editable
        self._cargando = False
        self._invalidos = {}          # {("l"|"c", fila, columna): texto} con números mal escritos
        self.setWindowTitle(f"Cotización {numero}" + ("" if editable else " (solo lectura)"))
        self.resize(1120, 820)

        conn = db.get_connection()
        self.lineas = db.obtener_lineas(cotizacion_id, conn)
        self.cargos = db.obtener_cargos(cotizacion_id, conn)
        notas = db.obtener_notas(cotizacion_id, conn)
        titulo_notas = db.obtener_titulo_notas("cotizaciones", cotizacion_id, conn)
        proyecto = db.obtener_proyecto(cotizacion_id, conn)
        empresas = db.listar_empresas(conn)
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
        for b in (self.btn_grupo, self.btn_item, self.btn_subitem, self.btn_texto, self.btn_subir, self.btn_bajar):
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
        self.btn_coef = boton("Coeficientes e indirectos", "sliders")
        self.btn_biblioteca.clicked.connect(self.desde_biblioteca)
        self.btn_guardar_biblioteca.clicked.connect(self.guardar_en_biblioteca)
        self.btn_apu.clicked.connect(self.abrir_apu)
        self.btn_coef.clicked.connect(self.ajustes_apu)
        for b in (self.btn_biblioteca, self.btn_guardar_biblioteca):
            barra2.addWidget(b)
        barra2.addStretch()
        for b in (self.btn_apu, self.btn_coef):
            barra2.addWidget(b)
        layout.addLayout(barra2)

        self.tabla = tabla_estandar(["Ítem", "Descripción", "Tipo", "Ud.", "Cantidad", "Precio unitario", "Importe", "ITBMS"])
        self.tabla.setMinimumHeight(240)
        self.tabla.setWordWrap(True)
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed
                                   | QTableWidget.AnyKeyPressed if editable else QTableWidget.NoEditTriggers)
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
        layout.addLayout(fila)
        self.tabla_cargos = tabla_estandar(["Concepto", "Tipo", "Valor", "Monto", "ITBMS"])
        self.tabla_cargos.setFixedHeight(150)
        self.tabla_cargos.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed
                                          | QTableWidget.AnyKeyPressed if editable else QTableWidget.NoEditTriggers)
        hc = self.tabla_cargos.horizontalHeader()
        hc.setSectionResizeMode(CARGO_CONCEPTO, QHeaderView.Stretch)
        for c, ancho in ((CARGO_TIPO, 150), (CARGO_VALOR, 110), (CARGO_MONTO, 130), (CARGO_ITBMS, 64)):
            hc.setSectionResizeMode(c, QHeaderView.Fixed)
            self.tabla_cargos.setColumnWidth(c, ancho)
        self.tabla_cargos.itemChanged.connect(self._al_editar_cargo)
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
        layout.addLayout(fila_notas)
        fila_titulo = QHBoxLayout()
        fila_titulo.addWidget(QLabel("Título del bloque:"))
        self.titulo_notas_edit = QLineEdit(titulo_notas)
        self.titulo_notas_edit.setPlaceholderText(db.TITULO_NOTAS)
        fila_titulo.addWidget(self.titulo_notas_edit, 1)
        layout.addLayout(fila_titulo)
        self.notas_edit = QPlainTextEdit()
        self.notas_edit.setPlainText(notas)
        self.notas_edit.setPlaceholderText("Alcance, exclusiones y condiciones que saldrán en el PDF…")
        self.notas_edit.setMinimumHeight(self.notas_edit.fontMetrics().lineSpacing() * 6 + 20)
        layout.addWidget(self.notas_edit)

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
            desc = QTableWidgetItem(texto_rico.a_texto_plano(l.descripcion))
            desc.setToolTip("Doble clic o F2 para editar el texto con formato" if self.editable else "")
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
        cods, imps = calculo.codigos(self.lineas), calculo.importes(self.lineas)
        for i, l in enumerate(self.lineas):
            self.tabla.item(i, COL_COD).setText(cods[i])
            if l.usa_apu:
                self.tabla.item(i, COL_PRECIO).setText(f"{l.precio:,.2f}")
            self.tabla.item(i, COL_IMPORTE).setText(_dinero(imps[i]))
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
        subtotal = calculo.calcular(self.lineas).subtotal
        for c, cargo in enumerate(self.cargos):
            m = self.tabla_cargos.item(c, CARGO_MONTO)
            if m is not None:
                m.setText(_dinero(cargo.monto(subtotal)))
        self._cargando = False
        self._actualizar_totales()

    def _actualizar_totales(self):
        t = calculo.calcular(self.lineas, self.cargos, self.tasa, self.cfg)
        filas = [f"Subtotal ítems: <b>{_dinero(t.subtotal)}</b>"]
        for cargo, monto in t.cargos:
            etiqueta = f"{cargo.concepto or 'Costo'} ({cargo.valor:g}%)" if cargo.tipo == "porcentaje" else (cargo.concepto or "Costo")
            filas.append(f"{etiqueta}: {_dinero(monto)}")
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

    def editar_descripcion(self, fila=None):
        """Abre el editor con formato de la descripción del ítem (o grupo) seleccionado."""
        i = self._fila_actual() if fila is None else fila
        if not (0 <= i < len(self.lineas)):
            return
        l = self.lineas[i]
        dlg = EditorTextoDialog(l.descripcion, f"Descripción · ítem {calculo.codigos(self.lineas)[i]}",
                                not self.editable, self)
        if self._ejecutar(dlg) and self.editable:
            l.descripcion = dlg.texto()
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
        dlg = ApuDialog(texto_rico.a_texto_plano(l.descripcion), l.unidad, l.apu or Apu(), self.cfg, self.coef_ind, self.editable, self)
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
            candidatos = [(l, self.lineas[i].descripcion) for l in self.lineas[i + 1:i + 1 + self._hijos(i)]]
        else:
            g = self._padre(i)
            candidatos = [(self.lineas[i], self.lineas[g].descripcion if self.lineas[i].nivel == 1 and g >= 0 else "")]
        candidatos = [(l, texto_rico.a_texto_plano(cat)) for l, cat in candidatos if not texto_rico.es_vacio(l.descripcion)]
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
        self._refrescar_derivados()

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
            vacia = texto_rico.es_vacio(l.descripcion) and (l.es_grupo and not self._hijos(i) or
                                           not l.es_grupo and l.precio == 0)
            if vacia:
                continue
            if texto_rico.es_vacio(l.descripcion):
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
        if self.empresa_combo.currentData() is not None:
            db.cambiar_empresa_cotizacion(self.cotizacion_id, self.empresa_combo.currentData(), conn)
        db.guardar_cotizacion(self.cotizacion_id, lineas, cargos, conn, tasa=self.tasa, cfg=self.cfg)
        db.guardar_notas(self.cotizacion_id, self.notas_edit.toPlainText().strip("\n"), conn)
        db.guardar_titulo_notas("cotizaciones", self.cotizacion_id, self.titulo_notas_edit.text(), conn)
        db.guardar_proyecto(self.cotizacion_id, self.proyecto_edit.text().strip(), conn)
        conn.close()
        return True
