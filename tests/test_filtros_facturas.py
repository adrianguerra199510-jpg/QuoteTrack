import pytest
from PySide6.QtCore import QDate

from app import db, ui_main


@pytest.fixture
def tab(conn, qapp):
    """Tres facturas: ACME/INTEGRO (enero, pendiente), ACME/Empresa B (marzo, pagada), BETA/INTEGRO (mayo, vencida)."""
    b_emp = db.guardar_empresa({"nombre": "Empresa B"}, conn)
    beta = db.guardar_cliente({"nombre": "BETA SA"}, conn)
    for cot, cli, emp, fecha, estado in ((1, 1, None, "2026-01-10", "pendiente"), (2, 1, b_emp, "2026-03-10", "pagada"),
                                         (3, beta, None, "2026-05-10", "vencida")):
        if cot > 1:
            conn.execute("INSERT INTO cotizaciones (numero, cliente_id, fecha, estado) VALUES (?, ?, '2026-01-01', 'aprobada')",
                         (f"COT-2026-000{cot}", cli))
        conn.execute("UPDATE cotizaciones SET estado = 'aprobada', cliente_id = ? WHERE id = ?", (cli, cot))
        conn.execute("INSERT INTO facturas (numero, cotizacion_id, cliente_id, fecha, estado_pago, total, empresa_id) "
                     "VALUES (?, ?, ?, ?, ?, 100, ?)",
                     (f"FAC-2026-000{cot}", cot, cli, fecha, estado, emp or db.empresa_predeterminada_id(conn)))
    conn.commit()
    w = ui_main.MainWindow()
    t = w.facturas_tab
    t._ventana = w
    t.refrescar()
    return t


def numeros(t):
    return sorted(t.tabla.item(i, 0).text() for i in range(t.tabla.rowCount()))


def test_filtros_de_facturas(tab, conn):
    f = tab.filtro
    assert len(numeros(tab)) == 3
    f.cliente.setCurrentIndex(f.cliente.findText("BETA SA"))
    assert numeros(tab) == ["FAC-2026-0003"]
    f.limpiar()
    f.empresa.setCurrentIndex(f.empresa.findText("Empresa B"))
    assert numeros(tab) == ["FAC-2026-0002"]
    f.limpiar()
    f.desde.setDate(QDate(2026, 2, 1))
    f.hasta.setDate(QDate(2026, 4, 30))
    assert numeros(tab) == ["FAC-2026-0002"]
    f.hasta.setDate(f.hasta.minimumDate())                       # solo «desde»
    assert numeros(tab) == ["FAC-2026-0002", "FAC-2026-0003"]
    f.limpiar()
    f.estado.setCurrentIndex(f.estado.findData("vencida"))
    assert numeros(tab) == ["FAC-2026-0003"]
    f.limpiar()
    assert len(numeros(tab)) == 3 and f.desde.date() == f.desde.minimumDate()


def test_filtros_se_combinan(tab):
    f = tab.filtro
    f.cliente.setCurrentIndex(f.cliente.findText("ACME"))
    f.estado.setCurrentIndex(f.estado.findData("pagada"))
    assert numeros(tab) == ["FAC-2026-0002"]
    f.busqueda.setText("0001")
    assert numeros(tab) == []
