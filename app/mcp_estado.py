"""Estado de conexión del servidor MCP, compartido entre QuoteTrackMCP.exe y la aplicación (sin dependencias de Qt).

Cada servidor MCP en marcha escribe un «latido» —un pequeño JSON— en la carpeta `mcp_estado` junto a la base de datos,
y lo renueva cada par de segundos. La aplicación lee esa carpeta: si hay algún latido reciente, el MCP está conectado.
Si el servidor se cierra limpiamente borra su archivo; si lo matan, el latido queda viejo y deja de contar."""
import json
import os
import threading
import time
from pathlib import Path

INTERVALO = 2.0          # segundos entre latidos
CADUCIDAD = 7.0          # un latido más viejo que esto se considera caído
ACTIVIDAD_RECIENTE = 3.0  # «acaba de pasar algo» (para el destello del indicador)


def carpeta_estado(db_path) -> Path:
    return Path(db_path).resolve().parent / "mcp_estado"


class Latido:
    """Lado del servidor: mantiene vivo su archivo de estado mientras el proceso corre."""

    def __init__(self, db_path, escritura: bool, intervalo: float = INTERVALO):
        self.ruta = carpeta_estado(db_path) / f"{os.getpid()}.json"
        self.escritura = escritura
        self.intervalo = intervalo
        self.inicio = time.time()
        self.actividad = 0.0
        self.escribio = 0.0            # última herramienta que MODIFICÓ datos
        self.herramienta = ""
        self._parar = threading.Event()
        self._hilo = None

    def _contenido(self) -> dict:
        return {"pid": os.getpid(), "escritura": self.escritura, "inicio": self.inicio, "latido": time.time(),
                "actividad": self.actividad, "ultima_escritura": self.escribio, "herramienta": self.herramienta}

    def escribir(self) -> None:
        try:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.ruta.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._contenido()), encoding="utf-8")
            os.replace(tmp, self.ruta)           # reemplazo atómico: la app nunca lee un archivo a medias
        except OSError:
            pass                                 # el indicador es accesorio: nunca debe tumbar el servidor

    def registrar(self, herramienta: str, modifica: bool) -> None:
        self.actividad = time.time()
        self.herramienta = herramienta
        if modifica:
            self.escribio = self.actividad
        self.escribir()

    def iniciar(self) -> None:
        self.escribir()
        self._hilo = threading.Thread(target=self._bucle, name="latido-mcp", daemon=True)
        self._hilo.start()

    def _bucle(self) -> None:
        while not self._parar.wait(self.intervalo):
            self.escribir()

    def detener(self) -> None:
        self._parar.set()
        try:
            self.ruta.unlink()
        except OSError:
            pass


def leer(db_path, ahora: float | None = None) -> dict:
    """Lado de la aplicación. Devuelve {"conectado": bool, "escritura": bool, "actividad": float,
    "ultima_escritura": float, "herramienta": str, "servidores": int}. Limpia los latidos muertos."""
    ahora = time.time() if ahora is None else ahora
    vivos = []
    carpeta = carpeta_estado(db_path)
    try:
        archivos = list(carpeta.glob("*.json"))
    except OSError:
        archivos = []
    for f in archivos:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue                                  # a medio escribir u otro problema: se reintenta en el próximo ciclo
        if ahora - float(d.get("latido", 0)) <= CADUCIDAD:
            vivos.append(d)
        elif ahora - float(d.get("latido", 0)) > CADUCIDAD * 6:
            try:
                f.unlink()                            # servidor muerto hace rato: se limpia el archivo
            except OSError:
                pass
    reciente = max(vivos, key=lambda d: d.get("actividad", 0), default={})
    return {"conectado": bool(vivos), "servidores": len(vivos),
            "escritura": any(d.get("escritura") for d in vivos),
            "actividad": max((d.get("actividad", 0) for d in vivos), default=0.0),
            "ultima_escritura": max((d.get("ultima_escritura", 0) for d in vivos), default=0.0),
            "herramienta": reciente.get("herramienta", "")}
