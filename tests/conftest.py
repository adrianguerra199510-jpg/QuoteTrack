import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app import db


@pytest.fixture
def conn(tmp_path, monkeypatch):
    """Base de datos temporal con un cliente (id=1) y una cotización borrador (id=1) con un item."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    c = db.get_connection()
    c.execute("INSERT INTO clientes (nombre, identificacion) VALUES ('ACME', '8-123-456')")
    c.execute("INSERT INTO cotizaciones (numero, cliente_id, fecha) VALUES ('COT-2026-0001', 1, '2026-01-15')")
    c.commit()
    db.guardar_items(1, [("Servicio", 2, 100.0)], c)
    yield c
    c.close()


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def pdf_sin_comprimir(monkeypatch):
    """Desactiva la compresión de reportlab para poder buscar texto en los bytes del PDF."""
    from reportlab import rl_config
    monkeypatch.setattr(rl_config, "pageCompression", 0)
