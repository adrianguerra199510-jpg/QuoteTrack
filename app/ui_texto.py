"""Editor de texto con formato (negrita, cursiva, subrayado, viñetas y numeración) para la descripción de un ítem."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeySequence, QTextCharFormat, QTextListFormat
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QTextEdit, QToolButton, QVBoxLayout,
)
from PySide6.QtGui import QShortcut

from app import texto_rico
from app.texto_rico import Parrafo, Tramo


def documento_a_texto(doc) -> str:
    """Convierte un QTextDocument en el HTML mínimo de `texto_rico` (vacío si no hay texto)."""
    parrafos = []
    bloque = doc.begin()
    while bloque.isValid():
        lista = bloque.textList()
        tipo = "p"
        if lista is not None:
            tipo = "ol" if lista.format().style() in (
                QTextListFormat.ListDecimal, QTextListFormat.ListLowerAlpha, QTextListFormat.ListUpperAlpha,
                QTextListFormat.ListLowerRoman, QTextListFormat.ListUpperRoman) else "ul"
        tramos = []
        for it in bloque:
            frag = it.fragment()
            if frag.isValid():
                f = frag.charFormat()
                texto = frag.text().replace("\u2028", "\n").replace("\xa0", " ")
                tramos.append(Tramo(texto, f.fontWeight() >= QFont.Bold, f.fontItalic(), f.fontUnderline()))
        parrafos.append(Parrafo(tipo, tramos))
        bloque = bloque.next()
    while parrafos and parrafos[-1].tipo == "p" and not parrafos[-1].texto.strip():
        parrafos.pop()
    while parrafos and parrafos[0].tipo == "p" and not parrafos[0].texto.strip():
        parrafos.pop(0)
    res = texto_rico.serializar(parrafos)
    return "" if texto_rico.es_vacio(res) else res


class EditorTextoDialog(QDialog):
    """Ventana amplia y redimensionable, con barra de formato, para escribir descripciones largas."""

    def __init__(self, texto="", titulo="Descripción del ítem", solo_lectura=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.resize(760, 560)
        self.setSizeGripEnabled(True)
        layout = QVBoxLayout(self)

        barra = QHBoxLayout()
        barra.setSpacing(2)
        self.btn_negrita = self._boton("N", "Negrita (Ctrl+B)", self._negrita, checkable=True)
        self.btn_negrita.setStyleSheet("font-weight: bold;")
        self.btn_cursiva = self._boton("K", "Cursiva (Ctrl+I)", self._cursiva, checkable=True)
        self.btn_cursiva.setStyleSheet("font-style: italic;")
        self.btn_subrayado = self._boton("S", "Subrayado (Ctrl+U)", self._subrayado, checkable=True)
        self.btn_subrayado.setStyleSheet("text-decoration: underline;")
        self.btn_vinetas = self._boton("• Viñetas", "Lista con viñetas", lambda: self._lista(QTextListFormat.ListDisc), checkable=True)
        self.btn_numeros = self._boton("1. Numeración", "Lista numerada", lambda: self._lista(QTextListFormat.ListDecimal), checkable=True)
        self.btn_limpiar = self._boton("Quitar formato", "Quita negrita, cursiva, subrayado y listas de la selección", self._limpiar)
        for b in (self.btn_negrita, self.btn_cursiva, self.btn_subrayado, self.btn_vinetas, self.btn_numeros, self.btn_limpiar):
            barra.addWidget(b)
        barra.addStretch()
        layout.addLayout(barra)

        self.editor = QTextEdit()
        self.editor.setAcceptRichText(False)
        self.editor.setHtml(texto_rico.a_html(texto))
        self.editor.setReadOnly(solo_lectura)
        self.editor.cursorPositionChanged.connect(self._actualizar_botones)
        self.editor.currentCharFormatChanged.connect(lambda *_: self._actualizar_botones())
        layout.addWidget(self.editor, 1)
        if solo_lectura:
            for b in self.findChildren(QToolButton):
                b.setEnabled(False)
        for secuencia, accion in (("Ctrl+B", self._negrita), ("Ctrl+I", self._cursiva), ("Ctrl+U", self._subrayado)):
            QShortcut(QKeySequence(secuencia), self, activated=lambda a=accion: a(None))

        layout.addWidget(QLabel("Enter crea un párrafo nuevo · Shift+Enter, un salto de línea dentro del mismo párrafo."))
        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel if not solo_lectura else QDialogButtonBox.Close)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)
        self._actualizar_botones()

    def _boton(self, texto, ayuda, accion, checkable=False):
        b = QToolButton()
        b.setText(texto)
        b.setToolTip(ayuda)
        b.setCheckable(checkable)
        b.setMinimumWidth(30)
        b.setAutoRaise(False)
        b.clicked.connect(accion)
        return b

    def texto(self) -> str:
        return documento_a_texto(self.editor.document())

    # --- formato de caracteres
    def _aplicar(self, **kw):
        fmt = QTextCharFormat()
        if "negrita" in kw:
            fmt.setFontWeight(QFont.Bold if kw["negrita"] else QFont.Normal)
        if "cursiva" in kw:
            fmt.setFontItalic(kw["cursiva"])
        if "subrayado" in kw:
            fmt.setFontUnderline(kw["subrayado"])
        cur = self.editor.textCursor()
        if cur.hasSelection():
            cur.mergeCharFormat(fmt)
        self.editor.mergeCurrentCharFormat(fmt)
        self.editor.setFocus()

    def _negrita(self, _=None):
        self._aplicar(negrita=self.editor.fontWeight() < QFont.Bold)

    def _cursiva(self, _=None):
        self._aplicar(cursiva=not self.editor.fontItalic())

    def _subrayado(self, _=None):
        self._aplicar(subrayado=not self.editor.fontUnderline())

    # --- listas
    def _lista(self, estilo):
        cur = self.editor.textCursor()
        actual = cur.currentList()
        if actual is not None and actual.format().style() == estilo:
            bloque = cur.block()
            actual.remove(bloque)
            fmt = bloque.blockFormat()
            fmt.setIndent(0)
            cur.setBlockFormat(fmt)
        else:
            cur.createList(estilo)
        self.editor.setFocus()
        self._actualizar_botones()

    def _limpiar(self):
        cur = self.editor.textCursor()
        cur.mergeCharFormat(self._formato_normal())
        self.editor.mergeCurrentCharFormat(self._formato_normal())
        for bloque in self._bloques_seleccion(cur):
            lista = bloque.textList()
            if lista is not None:
                lista.remove(bloque)
        self.editor.setFocus()
        self._actualizar_botones()

    @staticmethod
    def _formato_normal():
        f = QTextCharFormat()
        f.setFontWeight(QFont.Normal)
        f.setFontItalic(False)
        f.setFontUnderline(False)
        return f

    @staticmethod
    def _bloques_seleccion(cur):
        doc = cur.document()
        b = doc.findBlock(cur.selectionStart())
        fin = doc.findBlock(cur.selectionEnd())
        res = []
        while b.isValid():
            res.append(b)
            if b == fin:
                break
            b = b.next()
        return res

    def _actualizar_botones(self):
        lista = self.editor.textCursor().currentList()
        estilo = lista.format().style() if lista is not None else None
        self.btn_negrita.setChecked(self.editor.fontWeight() >= QFont.Bold)
        self.btn_cursiva.setChecked(self.editor.fontItalic())
        self.btn_subrayado.setChecked(self.editor.fontUnderline())
        self.btn_vinetas.setChecked(estilo == QTextListFormat.ListDisc)
        self.btn_numeros.setChecked(estilo == QTextListFormat.ListDecimal)
