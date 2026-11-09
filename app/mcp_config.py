"""Activar o desactivar el servidor MCP de QuoteTrack en Claude Desktop, desde la propia aplicación (sin Qt).

Claude Desktop lee sus servidores MCP de `claude_desktop_config.json` (clave `mcpServers`). Aquí se localiza ese archivo
—en la instalación de la Microsoft Store o en la clásica—, se añade o retira SOLO la entrada «quotetrack» y se deja
todo lo demás tal cual. Antes del primer cambio se guarda una copia (`claude_desktop_config.json.bak-quotetrack`).
Los cambios solo los ve Claude Desktop al reiniciarse por completo."""
import json
import os
import shutil
import sys
from pathlib import Path

NOMBRE = "quotetrack"
ARCHIVO = "claude_desktop_config.json"
RESPALDO = ".bak-quotetrack"


class ErrorConfig(Exception):
    """Problema legible para el usuario (archivo dañado, sin permisos, MCP no encontrado…)."""


# ----------------------------------------------------------------------------- dónde está la configuración
def rutas_config() -> list[Path]:
    """Rutas posibles del archivo de configuración de Claude Desktop (existan o no)."""
    rutas = []
    local, roaming = os.environ.get("LOCALAPPDATA"), os.environ.get("APPDATA")
    if local:                                    # instalación de la Microsoft Store (MSIX): el Roaming está virtualizado
        paquetes = Path(local) / "Packages"
        if paquetes.is_dir():
            for d in sorted(paquetes.glob("Claude_*")):
                rutas.append(d / "LocalCache" / "Roaming" / "Claude" / ARCHIVO)
    if roaming:                                  # instalación clásica
        rutas.append(Path(roaming) / "Claude" / ARCHIVO)
    return rutas


def rutas_destino() -> list[Path]:
    """Archivo(s) donde aplicar el cambio: los que ya existen; si no hay ninguno, el de la carpeta de Claude que exista;
    y, como último recurso, la ruta clásica (se crea)."""
    candidatas = rutas_config()
    for criterio in (lambda p: p.exists(), lambda p: p.parent.is_dir()):
        elegidas = [p for p in candidatas if criterio(p)]
        if elegidas:
            return elegidas
    return candidatas[-1:] or [Path.home() / "AppData" / "Roaming" / "Claude" / ARCHIVO]


# ----------------------------------------------------------------------------- qué se registra
def comando_mcp(escritura: bool) -> tuple[str, list[str]]:
    """Comando y argumentos con que Claude Desktop debe lanzar el MCP de ESTA instalación."""
    extra = ["--escritura"] if escritura else []
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve().parent / "QuoteTrackMCP.exe"
        if not exe.exists():
            raise ErrorConfig(f"No encuentro QuoteTrackMCP.exe junto a la aplicación ({exe.parent}).")
        return str(exe), extra
    raiz = Path(__file__).resolve().parent.parent       # en desarrollo: Python + el script de entrada
    return sys.executable, [str(raiz / "quotetrack_mcp.py"), *extra]


def entrada(escritura: bool) -> dict:
    comando, args = comando_mcp(escritura)
    return {"command": comando, "args": args}


def fragmento_json(escritura: bool) -> str:
    """Texto listo para pegar dentro de `mcpServers` si el usuario prefiere hacerlo a mano."""
    return json.dumps({NOMBRE: entrada(escritura)}, indent=2, ensure_ascii=False)


# ----------------------------------------------------------------------------- leer y escribir con cuidado
def _leer(ruta: Path) -> dict:
    if not ruta.exists():
        return {}
    texto = ruta.read_text(encoding="utf-8-sig")        # -sig: tolera el BOM que dejan algunos editores de Windows
    if not texto.strip():
        return {}
    try:
        datos = json.loads(texto)
    except ValueError as e:
        raise ErrorConfig(f"El archivo de configuración de Claude no es un JSON válido ({e}). "
                          f"No lo toqué: {ruta}") from e
    if not isinstance(datos, dict):
        raise ErrorConfig(f"El archivo de configuración de Claude tiene un formato inesperado: {ruta}")
    return datos


def _servidores(datos: dict, ruta: Path) -> dict:
    servidores = datos.setdefault("mcpServers", {})
    if not isinstance(servidores, dict):
        raise ErrorConfig(f"«mcpServers» tiene un formato inesperado en {ruta}")
    return servidores


def _guardar(ruta: Path, datos: dict) -> None:
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        respaldo = ruta.with_name(ruta.name + RESPALDO)
        if ruta.exists() and not respaldo.exists():     # solo la primera vez: conserva la configuración original
            shutil.copy2(ruta, respaldo)
        tmp = ruta.with_name(ruta.name + ".tmp")
        tmp.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")   # UTF-8 sin BOM
        os.replace(tmp, ruta)
    except OSError as e:
        raise ErrorConfig(f"No pude escribir la configuración de Claude ({e}). ¿Está abierta en otro programa?") from e


def _mismo_comando(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a or "")) == os.path.normcase(os.path.normpath(b or ""))


def estado(ruta: Path) -> dict:
    """{"activo", "escritura", "coincide", "comando"}: coincide=False si apunta a otra copia de QuoteTrack."""
    actual = _leer(ruta).get("mcpServers", {})
    reg = actual.get(NOMBRE) if isinstance(actual, dict) else None
    if not isinstance(reg, dict):
        return {"activo": False, "escritura": False, "coincide": False, "comando": ""}
    args = reg.get("args") or []
    try:
        esperado, _ = comando_mcp(False)
    except ErrorConfig:
        esperado = ""
    return {"activo": True, "escritura": "--escritura" in args,
            "coincide": _mismo_comando(reg.get("command", ""), esperado), "comando": reg.get("command", "")}


def activar(ruta: Path, escritura: bool) -> None:
    datos = _leer(ruta)
    _servidores(datos, ruta)[NOMBRE] = entrada(escritura)
    _guardar(ruta, datos)


def desactivar(ruta: Path) -> bool:
    """Quita la entrada de QuoteTrack. Devuelve False si no estaba."""
    datos = _leer(ruta)
    servidores = _servidores(datos, ruta)
    if NOMBRE not in servidores:
        return False
    del servidores[NOMBRE]
    _guardar(ruta, datos)
    return True
