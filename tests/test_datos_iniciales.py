from docx import Document

import pytest

from app import datos_iniciales, db, pdf, word


@pytest.fixture
def conn(tmp_path, monkeypatch):
    """Base vacía, como la de una instalación nueva."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "nueva.db")
    db.init_db()
    c = db.get_connection()
    yield c
    c.close()


def test_precarga_una_sola_vez(conn):
    assert datos_iniciales.precargar(conn) == 5
    assert datos_iniciales.precargar(conn) == 0
    numeros = [f["numero"] for f in conn.execute("SELECT numero FROM cotizaciones ORDER BY id")]
    assert numeros == ["COT-2026-0001", "COT-2026-0002", "COT-2026-0003", "COT-2026-0003-B"]
    assert conn.execute("SELECT numero, total FROM facturas").fetchone()["numero"] == "FAC-2026-0001"
    assert [e["nombre"] for e in db.listar_empresas(conn)].count("INARQS, S.A.") == 1
    assert all(e["logo"] for e in db.listar_empresas(conn))


def test_totales_y_estados(conn):
    datos_iniciales.precargar(conn)
    por = {c["numero"]: c for c in conn.execute("SELECT * FROM cotizaciones")}
    assert [round(por[n]["total"], 2) for n in sorted(por)] == [350.0, 650.0, 8775.76, 5856.0]
    assert por["COT-2026-0001"]["estado"] == "aprobada" and por["COT-2026-0003"]["estado"] == "enviada"
    fac = conn.execute("SELECT * FROM facturas").fetchone()
    assert fac["total"] == 350.0 and fac["titulo_notas"] == "Información de pago" and "Banco General" in fac["notas"]


def test_documentos_se_exportan(conn, tmp_path):
    datos_iniciales.precargar(conn)
    for cid in [c["id"] for c in conn.execute("SELECT id FROM cotizaciones")]:
        pdf.exportar_cotizacion(cid, str(tmp_path / f"{cid}.pdf"))
        word.exportar_cotizacion(cid, str(tmp_path / f"{cid}.docx"))
    fid = conn.execute("SELECT id FROM facturas").fetchone()["id"]
    pdf.exportar_factura(fid, str(tmp_path / "f.pdf"))
    word.exportar_factura(fid, str(tmp_path / "f.docx"))
    assert any(p.text == "Información de pago" for p in Document(str(tmp_path / "f.docx")).paragraphs)


def test_respeta_lo_existente_y_numera_despues(conn):
    datos_iniciales.precargar(conn)
    cid, numero = db.crear_cotizacion(conn.execute('SELECT id FROM clientes').fetchone()['id'], conn)
    assert numero == "COT-2026-0004"


def test_no_pisa_cotizaciones_existentes(conn):
    cid = db.guardar_cliente({"nombre": "ACME"}, conn)
    antes, _ = db.crear_cotizacion(cid, conn)
    conn.execute("UPDATE cotizaciones SET numero = 'COT-2026-0001' WHERE id = ?", (antes,))
    conn.commit()
    assert datos_iniciales.precargar(conn) == 3
    assert conn.execute("SELECT cliente_id FROM cotizaciones WHERE numero = 'COT-2026-0001'").fetchone()[0] == cid
    assert conn.execute("SELECT COUNT(*) FROM facturas").fetchone()[0] == 0     # su cotización origen es la del usuario
