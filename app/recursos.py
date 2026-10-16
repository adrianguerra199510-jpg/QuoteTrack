"""Rutas a recursos (logo, iconos) tanto en desarrollo como dentro del ejecutable de PyInstaller."""
import sys
from pathlib import Path


def ruta_recurso(relativa: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relativa
