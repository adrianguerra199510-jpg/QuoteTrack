"""Piezas de interfaz compartidas: botones con icono, encabezados de página, filtros y utilidades."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QStyledItemDelegate, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app import estilo, iconos


def boton(texto, icono=None, variante=None, tooltip=None) -> QPushButton:
    """Botón con icono. variante: None (secundario), 'primario' o 'peligro'."""
    b = QPushButton(texto)
    if icono:
        color = "#FFFFFF" if variante == "primario" else estilo.ROJO if variante == "peligro" else estilo.AZUL_OSCURO
        b.setIcon(iconos.icono(icono, color, 18))
    if variante:
        b.setProperty("variante", variante)
    if tooltip:
        b.setToolTip(tooltip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def encabezado_pagina(titulo: str, subtitulo: str = "") -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 4)
    lay.setSpacing(2)
    t = QLabel(titulo)
    t.setObjectName("titulo")
    lay.addWidget(t)
    if subtitulo:
        s = QLabel(subtitulo)
        s.setObjectName("subtitulo")
        lay.addWidget(s)
    return w


def pagina(widget: QWidget) -> QVBoxLayout:
    """Marca el widget como página (fondo, márgenes) y devuelve su layout principal."""
    widget.setObjectName("pagina")
    lay = QVBoxLayout(widget)
    lay.setContentsMargins(24, 20, 24, 20)
    lay.setSpacing(12)
    return lay


def tabla_estandar(columnas, estirar=None) -> QTableWidget:
    t = QTableWidget(0, len(columnas))
    t.setHorizontalHeaderLabels(columnas)
    t.setSelectionBehavior(QTableWidget.SelectRows)
    t.setSelectionMode(QTableWidget.SingleSelection)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.setAlternatingRowColors(True)
    t.setShowGrid(False)
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(38)
    cab = t.horizontalHeader()
    cab.setHighlightSections(False)
    cab.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    cab.setSectionResizeMode(QHeaderView.ResizeToContents)
    cab.setMinimumSectionSize(60)
    if estirar is not None:
        t.horizontalHeader().setSectionResizeMode(estirar, QHeaderView.Stretch)
    return t


def anchos_fijos(tabla: QTableWidget, anchos: dict) -> None:
    """Columnas de ancho fijo (rápido con miles de filas; `ResizeToContents` se vuelve lentísimo)."""
    cab = tabla.horizontalHeader()
    for col, ancho in anchos.items():
        cab.setSectionResizeMode(col, QHeaderView.Fixed)
        tabla.setColumnWidth(col, ancho)


def celda_estado(texto: str) -> QTableWidgetItem:
    """Celda con el color del estado (borrador, aprobada, vencida…)."""
    from PySide6.QtGui import QBrush, QColor, QFont
    it = QTableWidgetItem(texto)
    fondo, color = estilo.COLOR_ESTADO.get(texto, ("#E2E8F0", "#475569"))
    it.setBackground(QBrush(QColor(fondo)))
    it.setForeground(QBrush(QColor(color)))
    f = QFont()
    f.setBold(True)
    it.setFont(f)
    it.setTextAlignment(Qt.AlignCenter)
    return it


def celda_dinero(valor: float) -> QTableWidgetItem:
    it = QTableWidgetItem(f"B/. {valor:,.2f}")
    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return it


def exportar_archivo(parent, funcion, registro_id, numero, extension, filtro, titulo, **opciones):
    """Pide la ruta de destino y exporta con `funcion` (pdf.exportar_* / word.exportar_*)."""
    ruta, _ = QFileDialog.getSaveFileName(parent, titulo, f"{numero}.{extension}", filtro)
    if not ruta:
        return
    try:
        funcion(registro_id, ruta, **opciones)
    except (ValueError, OSError) as e:
        QMessageBox.warning(parent, titulo, f"No se pudo exportar el archivo:\n{e}")
        return
    QMessageBox.information(parent, titulo, f"Archivo guardado en:\n{ruta}")


def exportar_pdf(parent, funcion, registro_id, numero, **opciones):
    exportar_archivo(parent, funcion, registro_id, numero, "pdf", "PDF (*.pdf)", "Exportar PDF", **opciones)


def exportar_word(parent, funcion, registro_id, numero, **opciones):
    exportar_archivo(parent, funcion, registro_id, numero, "docx", "Documento de Word (*.docx)", "Exportar Word",
                     **opciones)


class FiltroBar(QHBoxLayout):
    """Barra de búsqueda (cliente o número) + filtro por estado; llama a `al_cambiar` al modificarse."""

    def __init__(self, estados, al_cambiar):
        super().__init__()
        self.busqueda = QLineEdit()
        self.busqueda.setPlaceholderText("Buscar por cliente o número…")
        self.busqueda.setClearButtonEnabled(True)
        self.busqueda.addAction(iconos.icono("search", estilo.APAGADO, 16), QLineEdit.LeadingPosition)
        self.estado = QComboBox()
        self.estado.addItem("Todos los estados", None)
        for e in estados:
            self.estado.addItem(e, e)
        self.addWidget(self.busqueda, 1)
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


def parsear_numero(texto):
    """Acepta '23,551.60', '23551.60' y '23551,60'. Devuelve None si no es un número."""
    t = (texto or "").strip().replace(" ", "").replace("B/.", "")
    if not t:
        return 0.0
    if "," in t and "." in t:
        t = t.replace(",", "")
    elif "," in t:
        entero, _, dec = t.rpartition(",")
        t = t.replace(",", "") if len(dec) == 3 else f"{entero}.{dec}".replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


class DescripcionDelegate(QStyledItemDelegate):
    """Editor multilínea para la descripción de un ítem (Enter = salto de línea)."""

    def createEditor(self, parent, option, index):
        editor = QPlainTextEdit(parent)
        editor.setMinimumHeight(70)
        return editor

    def setEditorData(self, editor, index):
        editor.setPlainText(index.data(Qt.EditRole) or "")

    def setModelData(self, editor, model, index):
        model.setData(index, editor.toPlainText().strip(), Qt.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect.x(), option.rect.y(), option.rect.width(),
                           max(option.rect.height(), 80))


def permitir_maximizar(dlg) -> None:
    """Agrega los botones de maximizar y minimizar a un diálogo (y F11 para pantalla completa)."""
    dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint)
    dlg.setSizeGripEnabled(True)
    QShortcut(QKeySequence(Qt.Key_F11), dlg, activated=lambda: dlg.showNormal() if dlg.isFullScreen() else dlg.showFullScreen())
