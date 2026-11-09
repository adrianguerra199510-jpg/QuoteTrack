"""Indicador «MCP conectado» de la barra lateral: un enchufe con un punto de color.

  gris   → no hay ningún servidor MCP conectado
  verde  → Claude está conectado por MCP (el tooltip dice si puede modificar datos)
  ámbar  → el MCP acaba de usarse (destello de unos segundos)

Cuando el MCP modifica datos (crea una cotización, cambia un estado…) emite `datos_modificados` para que la
aplicación refresque la pantalla sin que haya que cambiar de pestaña."""
import time

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from app import db, iconos, mcp_estado

DESCONECTADO = ("#5F73A6", "MCP desconectado")
CONECTADO = ("#22C55E", "MCP conectado")
ACTIVO = ("#F59E0B", "MCP activo")


class IndicadorMcp(QWidget):
    datos_modificados = Signal()

    def __init__(self, parent=None, intervalo_ms: int = 1500, db_path=None):
        super().__init__(parent)
        self._db_path = db_path
        self._ultima_escritura = None            # None = aún no se ha leído nada (no se refresca por lo que ya estaba)
        self.estado = {"conectado": False}
        self.setObjectName("indicadorMcp")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 4, 12, 4)
        lay.setSpacing(8)
        self._punto = QLabel()
        self._punto.setFixedSize(10, 10)
        self._icono = QLabel()
        self._texto = QLabel()
        self._texto.setObjectName("marcaSub")
        lay.addWidget(self._punto)
        lay.addWidget(self._icono)
        lay.addWidget(self._texto)
        lay.addStretch()
        self._pintar(DESCONECTADO)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.actualizar)
        self._timer.start(intervalo_ms)
        self.actualizar()

    # ------------------------------------------------------------------------------------------------ estado
    def actualizar(self, ahora: float | None = None, estado: dict | None = None) -> None:
        """Lee el latido del MCP (o usa `estado`, para pruebas) y repinta el indicador."""
        ahora = time.time() if ahora is None else ahora
        est = estado if estado is not None else mcp_estado.leer(self._db_path or db.DB_PATH, ahora)
        self.estado = est
        if not est["conectado"]:
            self._pintar(DESCONECTADO, "No hay ningún servidor MCP conectado.\n"
                                       "Claude se conecta a QuoteTrack a través de QuoteTrackMCP.exe.")
        else:
            modo = "puede crear y modificar datos" if est["escritura"] else "solo lectura"
            detalle = f"Claude está conectado por MCP ({modo})."
            reciente = ahora - est.get("actividad", 0) <= mcp_estado.ACTIVIDAD_RECIENTE
            if reciente:
                detalle += f"\nÚltima acción: {est.get('herramienta') or '—'}"
            self._pintar(ACTIVO if reciente else CONECTADO, detalle)
        escribio = est.get("ultima_escritura", 0)
        if self._ultima_escritura is None:
            self._ultima_escritura = escribio
        elif escribio > self._ultima_escritura:
            self._ultima_escritura = escribio
            self.datos_modificados.emit()

    def _pintar(self, estado, tooltip: str | None = None) -> None:
        color, texto = estado
        self._punto.setStyleSheet(f"background: {color}; border-radius: 5px;")
        self._icono.setPixmap(iconos.pixmap("plug", color if color != DESCONECTADO[0] else "#8FA6D8", 16, 2.0))
        self._texto.setText(texto)
        self._texto.setStyleSheet(f"color: {'#E5ECFF' if color != DESCONECTADO[0] else '#8FA6D8'}; font-size: 11px;")
        tooltip = tooltip or self.toolTip()
        self.setToolTip(tooltip)

    @property
    def conectado(self) -> bool:
        return bool(self.estado.get("conectado"))

    @property
    def texto(self) -> str:
        return self._texto.text()
