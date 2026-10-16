"""Tema visual de QuoteTrack (hoja de estilos Qt)."""
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

AZUL = "#1D4ED8"
AZUL_OSCURO = "#1E40AF"
AZUL_CLARO = "#EEF2FF"
MARINO = "#0B1F4D"
TURQUESA = "#0D9488"
FONDO = "#F3F6FB"
BORDE = "#D9E0EC"
TEXTO = "#1E293B"
APAGADO = "#64748B"
ROJO = "#DC2626"
VERDE = "#16A34A"
AMBAR = "#D97706"

# Colores (fondo, texto) de las "etiquetas" de estado en las tablas
COLOR_ESTADO = {
    "borrador": ("#E2E8F0", "#475569"),
    "enviada": ("#DBEAFE", "#1D4ED8"),
    "aprobada": ("#DCFCE7", "#15803D"),
    "rechazada": ("#FEE2E2", "#B91C1C"),
    "pendiente": ("#FEF3C7", "#B45309"),
    "pagada": ("#DCFCE7", "#15803D"),
    "vencida": ("#FEE2E2", "#B91C1C"),
}

QSS = f"""
* {{ font-size: 13px; color: {TEXTO}; }}
QMainWindow, QDialog, QWidget#pagina {{ background: {FONDO}; }}
QLabel {{ background: transparent; }}
QLabel#titulo {{ font-size: 22px; font-weight: 700; color: {MARINO}; }}
QLabel#subtitulo {{ color: {APAGADO}; }}
QLabel#seccion {{ font-size: 14px; font-weight: 700; color: {MARINO}; }}
QLabel#totales {{ background: white; border: 1px solid {BORDE}; border-radius: 10px; padding: 10px 14px; }}

QLineEdit, QPlainTextEdit, QDateEdit, QComboBox {{
    background: white; border: 1px solid {BORDE}; border-radius: 8px; padding: 6px 10px;
    selection-background-color: {AZUL}; selection-color: white;
}}
QPlainTextEdit {{ padding: 8px 10px; }}
QLineEdit:focus, QPlainTextEdit:focus, QDateEdit:focus, QComboBox:focus {{ border: 1px solid {AZUL}; }}
QLineEdit:read-only, QPlainTextEdit:read-only {{ background: #F1F5F9; color: {APAGADO}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox QAbstractItemView {{
    background: white; border: 1px solid {BORDE}; selection-background-color: {AZUL_CLARO};
    selection-color: {AZUL_OSCURO}; outline: 0;
}}

QPushButton {{
    background: white; border: 1px solid {BORDE}; border-radius: 8px; padding: 7px 14px; font-weight: 600;
}}
QPushButton:hover {{ background: {AZUL_CLARO}; border-color: #BFD0F5; }}
QPushButton:pressed {{ background: #DDE6FB; }}
QPushButton:disabled {{ color: #A7B0BE; background: #F1F5F9; border-color: #E5EAF2; }}
QPushButton[variante="primario"] {{ background: {AZUL}; border-color: {AZUL}; color: white; }}
QPushButton[variante="primario"]:hover {{ background: {AZUL_OSCURO}; border-color: {AZUL_OSCURO}; }}
QPushButton[variante="primario"]:disabled {{ background: #9DB4EE; border-color: #9DB4EE; color: white; }}
QPushButton[variante="peligro"] {{ color: {ROJO}; }}
QPushButton[variante="peligro"]:hover {{ background: #FEF2F2; border-color: #FECACA; }}

QTableWidget {{
    background: white; alternate-background-color: #F8FAFD; border: 1px solid {BORDE}; border-radius: 10px;
    gridline-color: transparent; selection-background-color: #DBE7FE; selection-color: {TEXTO};
}}
QTableWidget::item {{ padding: 0px 8px; }}
QTableWidget::item:selected {{ background: #DBE7FE; color: {TEXTO}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: #EDF1F8; color: {APAGADO}; font-weight: 700; border: none;
    border-bottom: 1px solid {BORDE}; padding: 8px 10px;
}}
QTableCornerButton::section {{ background: #EDF1F8; border: none; }}

QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid #94A3B8; border-radius: 4px; background: white; }}
QCheckBox::indicator:checked {{ background: {AZUL}; border-color: {AZUL}; }}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #C5CEDD; border-radius: 4px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: #A9B5CB; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #C5CEDD; border-radius: 4px; min-width: 28px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}

QListWidget#nav {{ background: {MARINO}; border: none; outline: 0; padding: 6px 10px; }}
QListWidget#nav::item {{
    color: #C7D4F2; padding: 11px 14px; margin: 2px 0; border-radius: 9px;
}}
QListWidget#nav::item:hover {{ background: #16306B; color: white; }}
QListWidget#nav::item:selected {{ background: {AZUL}; color: white; }}
QWidget#barraLateral {{ background: {MARINO}; }}
QLabel#marca {{ color: white; font-size: 18px; font-weight: 700; }}
QLabel#marcaSub {{ color: #8FA6D8; font-size: 11px; }}
QToolTip {{ background: {MARINO}; color: white; border: none; padding: 5px 8px; }}
QMessageBox {{ background: white; }}
"""


def aplicar(app: QApplication) -> None:
    app.setStyle("Fusion")
    fuente = QFont("Segoe UI", 10)
    fuente.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(fuente)
    paleta = QPalette()
    paleta.setColor(QPalette.Window, QColor(FONDO))
    paleta.setColor(QPalette.Base, QColor("white"))
    paleta.setColor(QPalette.Highlight, QColor(AZUL))
    paleta.setColor(QPalette.HighlightedText, QColor("white"))
    app.setPalette(paleta)
    app.setStyleSheet(QSS)
