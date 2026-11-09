"""Indicador «MCP conectado» de la barra lateral: un enchufe con un punto de color.

  gris   → no hay ningún servidor MCP conectado
  verde  → Claude está conectado por MCP (el tooltip dice si puede modificar datos)
  ámbar  → el MCP acaba de usarse (destello de unos segundos)

Cuando el MCP modifica datos (crea una cotización, cambia un estado…) emite `datos_modificados` para que la
aplicación refresque la pantalla sin que haya que cambiar de pestaña."""
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app import db, estilo, iconos, mcp_config, mcp_estado
from app.ui_comun import boton

DESCONECTADO = ("#5F73A6", "MCP desconectado")
CONECTADO = ("#22C55E", "MCP conectado")
ACTIVO = ("#F59E0B", "MCP activo")


class IndicadorMcp(QWidget):
    datos_modificados = Signal()
    clic = Signal()                       # el usuario pulsó el indicador: se abre «Conexión con Claude»

    def __init__(self, parent=None, intervalo_ms: int = 1500, db_path=None):
        super().__init__(parent)
        self._db_path = db_path
        self.setCursor(Qt.PointingHandCursor)
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
        if tooltip:
            self._detalle = tooltip
        self.setToolTip(getattr(self, "_detalle", "") + "\n\nClic para activar o desactivar el MCP.")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clic.emit()
        super().mousePressEvent(e)

    @property
    def conectado(self) -> bool:
        return bool(self.estado.get("conectado"))

    @property
    def texto(self) -> str:
        return self._texto.text()


class ConexionMcpDialog(QDialog):
    """«Conexión con Claude (MCP)»: activa o desactiva el MCP en Claude Desktop sin tocar archivos a mano."""

    def __init__(self, parent=None, rutas=None, db_path=None):
        super().__init__(parent)
        self.setWindowTitle("Conexión con Claude (MCP)")
        self.setMinimumWidth(680)
        self._rutas = list(rutas) if rutas is not None else mcp_config.rutas_destino()
        self._db_path = db_path
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(10)
        titulo = QLabel("Conexión con Claude (MCP)")
        titulo.setObjectName("seccion")
        lay.addWidget(titulo)
        intro = QLabel("El MCP deja que Claude consulte —y, si lo permites, cree— tus cotizaciones y facturas. "
                       "Al activarlo, Claude Desktop lo inicia solo y sin ventanas: no hace falta abrir "
                       "QuoteTrackMCP.exe.")
        intro.setObjectName("subtitulo")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.lbl_estado = QLabel()
        self.lbl_estado.setWordWrap(True)
        self.lbl_estado.setTextFormat(Qt.RichText)
        lay.addWidget(self.lbl_estado)
        self.lbl_vivo = QLabel()
        self.lbl_vivo.setObjectName("subtitulo")
        self.lbl_vivo.setWordWrap(True)
        lay.addWidget(self.lbl_vivo)
        self.chk_escritura = QCheckBox("Permitir que Claude cree y modifique cotizaciones y facturas (nunca borra)")
        self.chk_escritura.setChecked(True)
        lay.addWidget(self.chk_escritura)
        self.lbl_ruta = QLabel()
        self.lbl_ruta.setObjectName("subtitulo")
        self.lbl_ruta.setWordWrap(True)
        self.lbl_ruta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.lbl_ruta)
        self.lbl_resultado = QLabel()
        self.lbl_resultado.setWordWrap(True)
        self.lbl_resultado.setTextFormat(Qt.RichText)
        lay.addWidget(self.lbl_resultado)
        fila = QHBoxLayout()
        self.btn_activar = boton("Activar MCP", "plug", "primario")
        self.btn_activar.clicked.connect(self.activar)
        self.btn_desactivar = boton("Desactivar", "x-circle", "peligro")
        self.btn_desactivar.clicked.connect(self.desactivar)
        self.btn_copiar = boton("Copiar configuración", "copy",
                                tooltip="Para pegarla a mano en claude_desktop_config.json si prefieres hacerlo tú.")
        self.btn_copiar.clicked.connect(self.copiar)
        btn_cerrar = boton("Cerrar")
        btn_cerrar.clicked.connect(self.accept)
        for b in (self.btn_activar, self.btn_desactivar, self.btn_copiar):
            b.setMinimumWidth(b.sizeHint().width() + 24)
            fila.addWidget(b)
        fila.addStretch()
        fila.addWidget(btn_cerrar)
        lay.addLayout(fila)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._actualizar_vivo)
        self._timer.start(1500)
        self.refrescar()
        self.adjustSize()

    # ------------------------------------------------------------------------------------------------ estado
    def _estado(self) -> dict:
        try:
            estados = [mcp_config.estado(r) for r in self._rutas]
        except mcp_config.ErrorConfig as e:
            return {"error": str(e)}
        activos = [e for e in estados if e["activo"]]
        return (activos or estados or [{"activo": False, "escritura": False, "coincide": False, "comando": ""}])[0]

    def refrescar(self) -> None:
        e = self._estado()
        self.lbl_ruta.setText("Configuración de Claude Desktop:\n" + "\n".join(str(r) for r in self._rutas))
        if "error" in e:
            self.lbl_estado.setText(f"<span style='color:{estilo.ROJO}'><b>No pude leer la configuración.</b> "
                                    f"{e['error']}</span>")
            self.btn_activar.setEnabled(False)
            self.btn_desactivar.setEnabled(False)
            return
        self.btn_activar.setEnabled(True)
        self.btn_desactivar.setEnabled(e["activo"])
        if not e["activo"]:
            self.lbl_estado.setText("<b>Estado:</b> desactivado. Claude no puede ver QuoteTrack todavía.")
            self.btn_activar.setText("Activar MCP")
        else:
            modo = "lectura y escritura" if e["escritura"] else "solo lectura"
            if e["coincide"]:
                self.lbl_estado.setText(f"<b>Estado:</b> <span style='color:#16A34A'><b>activado</b></span> "
                                        f"en Claude Desktop ({modo}).")
                self.btn_activar.setText("Aplicar cambios")
            else:
                self.lbl_estado.setText(f"<b>Estado:</b> activado ({modo}), pero apunta a otra copia de QuoteTrack:"
                                        f"<br><small>{e['comando']}</small><br>Pulsa «Reparar» para usar esta.")
                self.btn_activar.setText("Reparar")
            self.chk_escritura.setChecked(e["escritura"])
        self._actualizar_vivo()

    def _actualizar_vivo(self) -> None:
        if mcp_estado.leer(self._db_path or db.DB_PATH)["conectado"]:
            self.lbl_vivo.setText("Ahora mismo: Claude está conectado.")
        else:
            self.lbl_vivo.setText("Ahora mismo: Claude no está conectado. Se conecta al abrir Claude Desktop "
                                  "(después de activar, ciérralo por completo y vuelve a abrirlo).")

    # ------------------------------------------------------------------------------------------------ acciones
    def _resultado(self, texto: str, error: bool = False) -> None:
        color = estilo.ROJO if error else "#16A34A"
        self.lbl_resultado.setText(f"<span style='color:{color}'>{texto}</span>")

    def activar(self) -> None:
        escritura = self.chk_escritura.isChecked()
        try:
            for r in self._rutas:
                mcp_config.activar(r, escritura)
        except mcp_config.ErrorConfig as e:
            self._resultado(str(e), error=True)
            return
        modo = "lectura y escritura" if escritura else "solo lectura"
        self.refrescar()
        self._resultado(f"<b>Listo: MCP activado ({modo}).</b> Cierra Claude Desktop por completo y ábrelo de nuevo "
                        "para que lo cargue.")

    def desactivar(self) -> None:
        try:
            quitado = any([mcp_config.desactivar(r) for r in self._rutas])
        except mcp_config.ErrorConfig as e:
            self._resultado(str(e), error=True)
            return
        self.refrescar()
        self._resultado("MCP desactivado. Reinicia Claude Desktop para que deje de verlo." if quitado
                        else "El MCP ya estaba desactivado.")

    def copiar(self) -> None:
        try:
            texto = mcp_config.fragmento_json(self.chk_escritura.isChecked())
        except mcp_config.ErrorConfig as e:
            self._resultado(str(e), error=True)
            return
        QApplication.clipboard().setText(texto)
        self._resultado("Configuración copiada. Pégala dentro de «mcpServers» en claude_desktop_config.json.")
