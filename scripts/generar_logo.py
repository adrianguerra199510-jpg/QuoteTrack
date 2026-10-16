"""Genera assets/logo.png, assets/icon.png y assets/icon.ico a partir de assets/logo.svg.

Uso (desde la raíz):  python scripts/generar_logo.py
"""
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

RAIZ = Path(__file__).resolve().parent.parent
ASSETS = RAIZ / "assets"


def renderizar(renderer: QSvgRenderer, lado: int) -> QImage:
    img = QImage(lado, lado, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p)
    p.end()
    return img


def a_png(img: QImage) -> bytes:
    datos = QByteArray()
    buf = QBuffer(datos)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(datos)


def escribir_ico(ruta: Path, pngs: dict[int, bytes]) -> None:
    """ICO con imágenes PNG incrustadas (válido desde Windows Vista)."""
    cabecera = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entradas, cuerpo = b"", b""
    for lado, datos in sorted(pngs.items()):
        entradas += struct.pack("<BBBBHHII", lado % 256, lado % 256, 0, 0, 1, 32, len(datos), offset)
        cuerpo += datos
        offset += len(datos)
    ruta.write_bytes(cabecera + entradas + cuerpo)


def main():
    app = QGuiApplication(sys.argv)  # noqa: F841 (necesario para QtGui)
    renderer = QSvgRenderer(str(ASSETS / "logo.svg"))
    (ASSETS / "logo.png").write_bytes(a_png(renderizar(renderer, 512)))
    (ASSETS / "icon.png").write_bytes(a_png(renderizar(renderer, 256)))
    escribir_ico(ASSETS / "icon.ico", {n: a_png(renderizar(renderer, n)) for n in (16, 24, 32, 48, 64, 128, 256)})
    print("Generados:", ", ".join(p.name for p in sorted(ASSETS.glob("*")) if p.suffix != ".svg"))


if __name__ == "__main__":
    main()
