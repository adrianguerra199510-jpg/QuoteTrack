"""Vista previa de una cotización o factura tal como saldrá en el PDF, con zoom y exportación directa."""
import tempfile
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QScrollArea, QVBoxLayout, QWidget

from app import estilo
from app.ui_comun import boton

ZOOMS = [50, 65, 80, 100, 125, 150, 200]
PX_POR_PUNTO = 96 / 72          # la página se muestra a tamaño real de pantalla (96 ppp) × zoom


class VistaPreviaDialog(QDialog):
    """`generar_pdf(ruta)` crea el PDF a mostrar; `al_exportar_pdf` / `al_exportar_word` (opcionales) se llaman con
    los botones de exportación (que abren su diálogo de «guardar como»)."""

    def __init__(self, generar_pdf, titulo="Vista previa", al_exportar_pdf=None, al_exportar_word=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.resize(940, 860)
        self._tmp = tempfile.TemporaryDirectory(prefix="quotetrack_")
        self.ruta = Path(self._tmp.name) / "vista_previa.pdf"
        self.zoom = 100
        self.paginas: list[QLabel] = []
        self.doc = None
        self.error = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)
        barra = QHBoxLayout()
        self.btn_menos = boton("", "zoom-out", tooltip="Reducir")
        self.lbl_zoom = QLabel("100 %")
        self.lbl_zoom.setMinimumWidth(52)
        self.lbl_zoom.setAlignment(Qt.AlignCenter)
        self.btn_mas = boton("", "zoom-in", tooltip="Ampliar")
        self.btn_ancho = boton("Ajustar al ancho", None)
        self.lbl_pagina = QLabel()
        self.lbl_pagina.setObjectName("subtitulo")
        for w in (self.btn_menos, self.lbl_zoom, self.btn_mas, self.btn_ancho):
            barra.addWidget(w)
        barra.addStretch()
        barra.addWidget(self.lbl_pagina)
        lay.addLayout(barra)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { background: #D5DAE3; border: 1px solid #C3CAD6; border-radius: 8px; }")
        self.contenedor = QWidget()
        self.contenedor.setStyleSheet("background: transparent;")
        self.vbox = QVBoxLayout(self.contenedor)
        self.vbox.setContentsMargins(20, 20, 20, 20)
        self.vbox.setSpacing(18)
        self.vbox.setAlignment(Qt.AlignHCenter)
        self.scroll.setWidget(self.contenedor)
        lay.addWidget(self.scroll, 1)

        pie = QHBoxLayout()
        nota = QLabel("Así se verá el PDF. El Word tiene el mismo contenido (editable).")
        nota.setObjectName("subtitulo")
        pie.addWidget(nota)
        pie.addStretch()
        self.btn_pdf = boton("Exportar PDF", "download", "primario")
        self.btn_word = boton("Exportar Word", "word")
        self.btn_cerrar = boton("Cerrar", "x")
        self.btn_pdf.setVisible(al_exportar_pdf is not None)
        self.btn_word.setVisible(al_exportar_word is not None)
        if al_exportar_pdf:
            self.btn_pdf.clicked.connect(al_exportar_pdf)
        if al_exportar_word:
            self.btn_word.clicked.connect(al_exportar_word)
        self.btn_cerrar.clicked.connect(self.accept)
        for b in (self.btn_pdf, self.btn_word, self.btn_cerrar):
            pie.addWidget(b)
        lay.addLayout(pie)

        self.btn_menos.clicked.connect(lambda: self._cambiar_zoom(-1))
        self.btn_mas.clicked.connect(lambda: self._cambiar_zoom(1))
        self.btn_ancho.clicked.connect(self.ajustar_al_ancho)
        self.scroll.verticalScrollBar().valueChanged.connect(lambda *_: self._actualizar_pagina())

        try:
            generar_pdf(str(self.ruta))
            self.doc = QPdfDocument(self)
            self.doc.load(str(self.ruta))
            if self.doc.pageCount() < 1:
                raise ValueError("El documento no tiene páginas.")
        except Exception as e:      # ValueError de datos, OSError, etc.
            self.error = str(e)
            aviso = QLabel(f"No se pudo generar la vista previa:\n{e}")
            aviso.setWordWrap(True)
            self.vbox.addWidget(aviso)
            for b in (self.btn_menos, self.btn_mas, self.btn_ancho):
                b.setEnabled(False)
            return
        self._dibujar()

    # ------------------------------------------------------------------ páginas
    def _dibujar(self):
        """(Re)crea las páginas al zoom actual, nítidas también en pantallas de alta densidad."""
        for lbl in self.paginas:
            self.vbox.removeWidget(lbl)
            lbl.deleteLater()
        self.paginas = []
        dpr = self.devicePixelRatioF()
        for i in range(self.doc.pageCount()):
            pt = self.doc.pagePointSize(i)
            ancho, alto = round(pt.width() * PX_POR_PUNTO * self.zoom / 100), round(pt.height() * PX_POR_PUNTO * self.zoom / 100)
            imagen = self.doc.render(i, QSize(round(ancho * dpr), round(alto * dpr)))
            pm = QPixmap.fromImage(imagen)
            pm.setDevicePixelRatio(dpr)
            lbl = QLabel()
            lbl.setPixmap(pm)
            lbl.setFixedSize(ancho, alto)
            lbl.setStyleSheet("background: white; border: 1px solid #AEB6C4;")
            self.vbox.addWidget(lbl, 0, Qt.AlignHCenter)
            self.paginas.append(lbl)
        self.lbl_zoom.setText(f"{self.zoom} %")
        self.btn_menos.setEnabled(self.zoom > ZOOMS[0])
        self.btn_mas.setEnabled(self.zoom < ZOOMS[-1])
        self._actualizar_pagina()

    def _actualizar_pagina(self):
        if not self.paginas:
            return
        # posiciones calculadas (margen 20 y separación 18), sin depender de que el layout ya se haya aplicado
        centro = self.scroll.verticalScrollBar().value() + self.scroll.viewport().height() // 3
        actual, y = 1, 20
        for n, lbl in enumerate(self.paginas, 1):
            if y <= centro:
                actual = n
            y += lbl.height() + 18
        self.lbl_pagina.setText(f"Página {actual} de {len(self.paginas)}")

    def _cambiar_zoom(self, paso):
        i = min(range(len(ZOOMS)), key=lambda k: abs(ZOOMS[k] - self.zoom))
        nuevo = ZOOMS[max(0, min(len(ZOOMS) - 1, i + paso))]
        if nuevo != self.zoom:
            self.zoom = nuevo
            self._dibujar()

    def ajustar_al_ancho(self):
        if self.doc is None:
            return
        disponible = self.scroll.viewport().width() - 60
        pagina = self.doc.pagePointSize(0).width() * PX_POR_PUNTO
        self.zoom = max(ZOOMS[0], min(ZOOMS[-1], int(disponible / pagina * 100)))
        self._dibujar()

    def done(self, r):
        if self.doc is not None:
            self.doc.close()     # libera el archivo (Windows no deja borrar un archivo abierto)
            self.doc = None
        super().done(r)
        self._tmp.cleanup()


def vista_previa(parent, tipo: str, registro_id: int, numero: str) -> VistaPreviaDialog:
    """Abre la vista previa de una cotización (`tipo='cotizacion'`) o factura (`'factura'`) con sus botones de exportar."""
    from app import pdf, word
    from app.ui_comun import exportar_pdf, exportar_word
    if tipo == "cotizacion":
        generar, f_pdf, f_word = pdf.exportar_cotizacion, pdf.exportar_cotizacion, word.exportar_cotizacion
    else:
        generar, f_pdf, f_word = pdf.exportar_factura, pdf.exportar_factura, word.exportar_factura
    dlg = VistaPreviaDialog(
        lambda ruta: generar(registro_id, ruta), f"Vista previa — {numero}",
        lambda: exportar_pdf(parent, f_pdf, registro_id, numero),
        lambda: exportar_word(parent, f_word, registro_id, numero), parent)
    dlg.exec()
    return dlg
