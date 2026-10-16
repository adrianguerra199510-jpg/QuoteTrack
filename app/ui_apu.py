"""Análisis de precio unitario (APU): editor de insumos por categoría, coeficientes e indirectos."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QMenu, QMessageBox, QTabWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from app import calculo, estilo, iconos
from app.calculo import Apu, ConfigApu, Indirecto, Insumo
from app.ui_comun import boton, parsear_numero, tabla_estandar

DESC, UD, REND, COEF, PRECIO, COSTE = range(6)
EDITAR = (QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed | QAbstractItemView.AnyKeyPressed)
ROJO = QBrush(QColor(estilo.ROJO))
NORMAL = QBrush(QColor(estilo.TEXTO))
SOLO_LECTURA = Qt.ItemIsEnabled | Qt.ItemIsSelectable


def dinero(v: float) -> str:
    return f"B/. {v:,.2f}"


def _celda_num(texto, editable=True, cursiva=False):
    it = QTableWidgetItem(texto)
    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if not editable:
        it.setFlags(SOLO_LECTURA)
    if cursiva:
        f = QFont()
        f.setItalic(True)
        it.setFont(f)
    return it


class ApuEditor(QWidget):
    """Pestañas Materiales / Mano de obra / Medios auxiliares / Subcontratos + resumen de costos y precio.

    Coste de cada fila = rendimiento × coeficiente × precio unitario (como en la hoja de cálculo).
    Trabaja sobre `apu` directamente; `cambiado` se emite tras cada modificación."""
    cambiado = Signal()

    def __init__(self, apu: Apu, cfg: ConfigApu, coef_indirectos: float = 0.0, editable: bool = True, parent=None):
        super().__init__(parent)
        self.apu, self.cfg, self.coef_ind, self.editable = apu, cfg, coef_indirectos, editable
        self._cargando = False
        self._invalidos = set()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        fila = QHBoxLayout()
        fila.addWidget(QLabel("Este análisis produce"))
        self.base_spin = QDoubleSpinBox()
        self.base_spin.setDecimals(3)
        self.base_spin.setRange(0.001, 1_000_000)
        self.base_spin.setValue(apu.base or 1.0)
        self.base_spin.setEnabled(editable)
        self.base_spin.valueChanged.connect(self._al_cambiar_base)
        fila.addWidget(self.base_spin)
        fila.addWidget(QLabel("unidad(es) del ítem (rendimiento base)"))
        fila.addStretch()
        lay.addLayout(fila)

        self.tabs = QTabWidget()
        self.tablas = {}
        for cat, nombre in calculo.CATEGORIAS.items():
            self.tabs.addTab(self._crear_pagina(cat), nombre)
        lay.addWidget(self.tabs, 1)

        self.resumen = QLabel()
        self.resumen.setObjectName("totales")
        self.resumen.setTextFormat(Qt.RichText)
        lay.addWidget(self.resumen)
        for cat in calculo.CATEGORIAS:
            self._render(cat)
        self._refrescar()

    # --------------------------------------------------------------- construcción
    def _crear_pagina(self, cat):
        pagina = QWidget()
        lay = QVBoxLayout(pagina)
        lay.setContentsMargins(0, 8, 0, 0)
        barra = QHBoxLayout()
        b_add = boton("Agregar insumo", "plus")
        b_ref = boton("% de otra categoría", "percent",
                      tooltip="Fila cuyo precio es el coste de otra categoría (p. ej. herramienta menor = 5 % de la mano de obra)")
        menu = QMenu(b_ref)
        for otra, nombre in calculo.CATEGORIAS.items():
            if otra != cat:
                menu.addAction(f"% de {nombre.lower()}", lambda c=cat, o=otra: self.agregar(c, ref=o))
        b_ref.setMenu(menu)
        b_del = boton("Quitar", "trash", "peligro")
        b_add.clicked.connect(lambda: self.agregar(cat))
        b_del.clicked.connect(lambda: self.quitar(cat))
        for b in (b_add, b_ref):
            barra.addWidget(b)
        barra.addStretch()
        barra.addWidget(b_del)
        if not self.editable:
            for b in (b_add, b_ref, b_del):
                b.setEnabled(False)
        lay.addLayout(barra)
        t = tabla_estandar(["Descripción", "Ud.", "Rendimiento", "Coeficiente", "Precio unitario", "Coste"], estirar=DESC)
        t.setEditTriggers(EDITAR if self.editable else QAbstractItemView.NoEditTriggers)
        h = t.horizontalHeader()
        for c, ancho in ((UD, 70), (REND, 120), (COEF, 115), (PRECIO, 140), (COSTE, 130)):
            h.setSectionResizeMode(c, QHeaderView.Fixed)
            t.setColumnWidth(c, ancho)
        t.itemChanged.connect(lambda it, c=cat: self._al_editar(c, it))
        self.tablas[cat] = t
        lay.addWidget(t, 1)
        return pagina

    def _de(self, cat):
        return [i for i in self.apu.insumos if i.categoria == cat]

    # --------------------------------------------------------------- render / refresco
    def _render(self, cat):
        self._cargando = True
        self._invalidos = {k for k in self._invalidos if k[0] != cat}
        t = self.tablas[cat]
        insumos = self._de(cat)
        t.setRowCount(len(insumos))
        for r, i in enumerate(insumos):
            ref = bool(i.ref_categoria)
            desc = QTableWidgetItem(i.descripcion)
            ud = QTableWidgetItem("%" if ref and not i.unidad else i.unidad)
            ud.setTextAlignment(Qt.AlignCenter)
            precio = _celda_num("", editable=False, cursiva=True) if ref else _celda_num(f"{i.precio:,.2f}")
            items = (desc, ud, _celda_num(f"{i.rendimiento:g}"), _celda_num(f"{i.coeficiente:g}"), precio,
                     _celda_num("", editable=False))
            if ref:
                precio.setToolTip(f"Coste de {calculo.CATEGORIAS[i.ref_categoria].lower()}")
            if not self.editable:
                for it in items:
                    it.setFlags(SOLO_LECTURA)
            for c, it in enumerate(items):
                t.setItem(r, c, it)
        self._cargando = False

    def _refrescar(self):
        """Recalcula costes de cada fila, títulos de pestañas y resumen (sin tocar lo que se está editando)."""
        self._cargando = True
        costos = calculo.costos_apu(self.apu)
        for n, (cat, nombre) in enumerate(calculo.CATEGORIAS.items()):
            t = self.tablas[cat]
            for r, i in enumerate(self._de(cat)):
                if r >= t.rowCount():
                    break
                if i.ref_categoria:
                    base = sum(x.rendimiento * x.coeficiente * x.precio for x in self.apu.insumos
                               if x.categoria == i.ref_categoria and not x.ref_categoria)
                    t.item(r, PRECIO).setText(f"{base:,.2f}")
                t.item(r, COSTE).setText(f"{calculo.costo_insumo(self.apu, i):,.2f}")
            self.tabs.setTabText(n, f"{nombre}  ·  {dinero(costos[cat])}")
        self._cargando = False
        filas = calculo.desglose_apu(self.apu, self.cfg, self.coef_ind)
        html = ["<table cellspacing='0' cellpadding='3' width='100%'>",
                "<tr><td><b>Por unidad del ítem</b></td><td align='right'><b>Costo</b></td>"
                "<td align='right'><b>Coeficiente</b></td><td align='right'><b>Venta</b></td></tr>"]
        for cat, costo, coef, venta in filas:
            html.append(f"<tr><td>{calculo.CATEGORIAS[cat]}</td><td align='right'>{dinero(costo)}</td>"
                        f"<td align='right'>{coef:.2%}</td><td align='right'>{dinero(venta)}</td></tr>")
        costo_t = sum(f[1] for f in filas)
        venta_t = calculo.precio_unitario(self.apu, self.cfg, self.coef_ind)
        html.append(f"<tr><td><b>Total</b></td><td align='right'><b>{dinero(costo_t)}</b></td><td></td>"
                    f"<td align='right'><span style='font-size:15px'><b>{dinero(venta_t)}</b></span></td></tr></table>")
        if self.coef_ind:
            html.append(f"<div style='color:{estilo.APAGADO}'>Incluye {self.coef_ind:.2%} de costos indirectos en "
                        "mano de obra, medios auxiliares y subcontratos.</div>")
        self.resumen.setText("".join(html))
        self.precio_venta = venta_t

    # --------------------------------------------------------------- acciones
    def _al_cambiar_base(self, valor):
        self.apu.base = valor
        self._refrescar()
        self.cambiado.emit()

    def agregar(self, cat, ref=""):
        if ref:
            nuevo = Insumo(cat, "Herramienta menor" if cat == "auxiliar" and ref == "mano_obra" else "", "%", 1.0,
                           0.05 if cat == "auxiliar" else 0.0, 0.0, ref)
        else:
            nuevo = Insumo(cat, "", "", 1.0, 1.0, 0.0)
        self.apu.insumos.append(nuevo)
        self._render(cat)
        self._refrescar()
        t = self.tablas[cat]
        t.setCurrentCell(t.rowCount() - 1, DESC)
        self.cambiado.emit()
        if self.editable and t.item(t.rowCount() - 1, DESC) is not None:
            t.editItem(t.item(t.rowCount() - 1, DESC))

    def quitar(self, cat):
        fila = self.tablas[cat].currentRow()
        insumos = self._de(cat)
        if 0 <= fila < len(insumos):
            self.apu.insumos.remove(insumos[fila])
            self._render(cat)
            self._refrescar()
            self.cambiado.emit()

    def _al_editar(self, cat, item):
        if self._cargando or not self.editable:
            return
        insumos = self._de(cat)
        r, c = item.row(), item.column()
        if r >= len(insumos):
            return
        i = insumos[r]
        if c == DESC:
            i.descripcion = item.text().strip()
        elif c == UD:
            i.unidad = item.text().strip()
        elif c in (REND, COEF, PRECIO):
            valor = parsear_numero(item.text())
            clave = (cat, r, c)
            if valor is None:
                self._invalidos.add(clave)
                item.setForeground(ROJO)
            else:
                self._invalidos.discard(clave)
                item.setForeground(NORMAL)
                setattr(i, {REND: "rendimiento", COEF: "coeficiente", PRECIO: "precio"}[c], valor)
                self._cargando = True
                item.setText(f"{valor:g}" if c != PRECIO else f"{valor:,.2f}")
                self._cargando = False
        self._refrescar()
        self.cambiado.emit()

    def validar(self) -> str | None:
        """Mensaje de error si hay números mal escritos o insumos sin descripción."""
        if self._invalidos:
            cat, fila, _col = sorted(self._invalidos)[0]
            return f"{calculo.CATEGORIAS[cat]}, fila {fila + 1}: hay un número no válido."
        for cat in calculo.CATEGORIAS:
            for n, i in enumerate(self._de(cat), 1):
                if not i.descripcion and (i.precio or i.ref_categoria):
                    return f"{calculo.CATEGORIAS[cat]}, fila {n}: falta la descripción."
        return None

    def limpiar_vacios(self):
        """Quita filas sin descripción y sin precio."""
        self.apu.insumos[:] = [i for i in self.apu.insumos if i.descripcion or i.precio or i.ref_categoria]


class ApuDialog(QDialog):
    """Análisis de precio unitario de un ítem de la cotización."""

    def __init__(self, descripcion, unidad, apu, cfg, coef_indirectos=0.0, editable=True, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Análisis de precio unitario" + ("" if editable else " (solo lectura)"))
        self.resize(900, 640)
        self.apu = apu.copia()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        titulo = QLabel(descripcion or "(ítem sin descripción)")
        titulo.setObjectName("seccion")
        titulo.setWordWrap(True)
        lay.addWidget(titulo)
        if unidad:
            sub = QLabel(f"Unidad: {unidad}")
            sub.setObjectName("subtitulo")
            lay.addWidget(sub)
        self.editor = ApuEditor(self.apu, cfg, coef_indirectos, editable)
        lay.addWidget(self.editor, 1)
        pie = QHBoxLayout()
        pie.addStretch()
        cancelar = boton("Cancelar" if editable else "Cerrar", "x")
        aceptar = boton("Aceptar", "check", "primario")
        cancelar.clicked.connect(self.reject)
        aceptar.clicked.connect(self._aceptar)
        pie.addWidget(cancelar)
        if editable:
            pie.addWidget(aceptar)
        lay.addLayout(pie)

    def _aceptar(self):
        error = self.editor.validar()
        if error:
            QMessageBox.warning(self, "Análisis de precio unitario", error)
            return
        self.editor.limpiar_vacios()
        self.accept()


class AjustesApuDialog(QDialog):
    """Coeficientes de venta por categoría e indirectos de la cotización (hojas RESUMEN e INDIRECTOS)."""
    I_CONCEPTO, I_CANT, I_PERIODO, I_COSTO, I_SUBTOTAL = range(5)

    def __init__(self, cfg: ConfigApu, costo_directo: float, editable=True, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Coeficientes e indirectos")
        self.resize(760, 640)
        self.cfg = ConfigApu(cfg.coef_material, cfg.coef_mano_obra, cfg.coef_auxiliar, cfg.coef_subcontrato,
                             [Indirecto(i.concepto, i.cantidad, i.periodo, i.costo) for i in cfg.indirectos])
        self.costo_directo = costo_directo
        self._cargando = False
        self._invalidos = set()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)

        t1 = QLabel("Coeficientes de venta (se suman al costo de cada categoría)")
        t1.setObjectName("seccion")
        lay.addWidget(t1)
        form = QFormLayout()
        self.spins = {}
        for cat, nombre in calculo.CATEGORIAS.items():
            sp = QDoubleSpinBox()
            sp.setRange(0, 1000)
            sp.setDecimals(2)
            sp.setSuffix(" %")
            sp.setValue(cfg.coef(cat) * 100)
            sp.setEnabled(editable)
            sp.valueChanged.connect(lambda *_: self._actualizar())
            self.spins[cat] = sp
            form.addRow(f"{nombre}:", sp)
        lay.addLayout(form)

        fila = QHBoxLayout()
        t2 = QLabel("Costos indirectos de obra")
        t2.setObjectName("seccion")
        fila.addWidget(t2)
        fila.addStretch()
        self.btn_add = boton("Agregar indirecto", "plus")
        self.btn_del = boton("Quitar", "trash", "peligro")
        self.btn_add.clicked.connect(self.agregar)
        self.btn_del.clicked.connect(self.quitar)
        fila.addWidget(self.btn_add)
        fila.addWidget(self.btn_del)
        lay.addLayout(fila)
        self.tabla = tabla_estandar(["Concepto", "Cantidad", "Meses / horas", "Costo", "Subtotal"], estirar=self.I_CONCEPTO)
        h = self.tabla.horizontalHeader()
        for c, ancho in ((self.I_CANT, 90), (self.I_PERIODO, 120), (self.I_COSTO, 110), (self.I_SUBTOTAL, 120)):
            h.setSectionResizeMode(c, QHeaderView.Fixed)
            self.tabla.setColumnWidth(c, ancho)
        self.tabla.setEditTriggers(EDITAR if editable else QAbstractItemView.NoEditTriggers)
        self.tabla.itemChanged.connect(self._al_editar)
        lay.addWidget(self.tabla, 1)
        if not editable:
            self.btn_add.setEnabled(False)
            self.btn_del.setEnabled(False)

        self.resumen = QLabel()
        self.resumen.setObjectName("totales")
        self.resumen.setTextFormat(Qt.RichText)
        lay.addWidget(self.resumen)

        pie = QHBoxLayout()
        pie.addStretch()
        cancelar = boton("Cancelar" if editable else "Cerrar", "x")
        aceptar = boton("Aceptar", "check", "primario")
        cancelar.clicked.connect(self.reject)
        aceptar.clicked.connect(self._aceptar)
        pie.addWidget(cancelar)
        if editable:
            pie.addWidget(aceptar)
        lay.addLayout(pie)
        self._render()

    def _render(self):
        self._cargando = True
        self.tabla.setRowCount(len(self.cfg.indirectos))
        for r, i in enumerate(self.cfg.indirectos):
            self.tabla.setItem(r, self.I_CONCEPTO, QTableWidgetItem(i.concepto))
            self.tabla.setItem(r, self.I_CANT, _celda_num(f"{i.cantidad:g}"))
            self.tabla.setItem(r, self.I_PERIODO, _celda_num(f"{i.periodo:g}"))
            self.tabla.setItem(r, self.I_COSTO, _celda_num(f"{i.costo:,.2f}"))
            self.tabla.setItem(r, self.I_SUBTOTAL, _celda_num("", editable=False))
        self._cargando = False
        self._actualizar()

    def _actualizar(self):
        for cat, sp in self.spins.items():
            setattr(self.cfg, f"coef_{cat}", sp.value() / 100)
        self._cargando = True
        for r, i in enumerate(self.cfg.indirectos):
            self.tabla.item(r, self.I_SUBTOTAL).setText(dinero(i.subtotal))
        self._cargando = False
        total = self.cfg.total_indirectos
        coef = total / self.costo_directo if self.costo_directo > 0 else 0.0
        self.coef_indirectos = coef
        self.resumen.setText(
            f"Total de indirectos: <b>{dinero(total)}</b> &nbsp;·&nbsp; Costo directo de los ítems con análisis: "
            f"<b>{dinero(self.costo_directo)}</b><br>Coeficiente de indirectos: <b>{coef:.2%}</b> "
            f"<span style='color:{estilo.APAGADO}'>(se suma a mano de obra, medios auxiliares y subcontratos)</span>")

    def agregar(self):
        self.cfg.indirectos.append(Indirecto())
        self._render()
        r = self.tabla.rowCount() - 1
        self.tabla.setCurrentCell(r, self.I_CONCEPTO)
        self.tabla.editItem(self.tabla.item(r, self.I_CONCEPTO))

    def quitar(self):
        r = self.tabla.currentRow()
        if 0 <= r < len(self.cfg.indirectos):
            del self.cfg.indirectos[r]
            self._render()

    def _al_editar(self, item):
        if self._cargando:
            return
        r, c = item.row(), item.column()
        if r >= len(self.cfg.indirectos):
            return
        i = self.cfg.indirectos[r]
        if c == self.I_CONCEPTO:
            i.concepto = item.text().strip()
        elif c in (self.I_CANT, self.I_PERIODO, self.I_COSTO):
            v = parsear_numero(item.text())
            if v is None:
                self._invalidos.add((r, c))
                item.setForeground(ROJO)
            else:
                self._invalidos.discard((r, c))
                item.setForeground(NORMAL)
                setattr(i, {self.I_CANT: "cantidad", self.I_PERIODO: "periodo", self.I_COSTO: "costo"}[c], v)
                self._cargando = True
                item.setText(f"{v:g}" if c != self.I_COSTO else f"{v:,.2f}")
                self._cargando = False
        self._actualizar()

    def _aceptar(self):
        if self._invalidos:
            QMessageBox.warning(self, "Indirectos", "Hay números no válidos en la tabla de indirectos.")
            return
        self.cfg.indirectos[:] = [i for i in self.cfg.indirectos if i.concepto or i.costo]
        self.accept()
