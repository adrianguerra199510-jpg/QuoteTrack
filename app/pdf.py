"""Exportación de cotizaciones y facturas a PDF con reportlab."""
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from app import db


def _dinero(valor: float) -> str:
    return f"B/. {valor:,.2f}"


def _esc(texto: str) -> str:
    return (texto or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _encabezado(estilos, titulo, numero, fecha, cliente, extra=()):
    elementos = [
        Paragraph(titulo, estilos["Title"]),
        Paragraph(f"<b>Número:</b> {_esc(numero)}", estilos["Normal"]),
        Paragraph(f"<b>Fecha:</b> {_esc(fecha)}", estilos["Normal"]),
    ]
    for etiqueta, valor in extra:
        elementos.append(Paragraph(f"<b>{etiqueta}:</b> {_esc(valor)}", estilos["Normal"]))
    elementos += [
        Spacer(1, 0.5 * cm),
        Paragraph("Cliente", estilos["Heading3"]),
        Paragraph(_esc(cliente["nombre"]), estilos["Normal"]),
    ]
    if cliente["identificacion"]:
        elementos.append(Paragraph(f"RUC/Cédula: {_esc(cliente['identificacion'])}", estilos["Normal"]))
    if cliente["contacto"]:
        elementos.append(Paragraph(f"Contacto: {_esc(cliente['contacto'])}", estilos["Normal"]))
    elementos.append(Spacer(1, 0.7 * cm))
    return elementos


def _tabla_totales(subtotal, itbms, total):
    t = Table(
        [["Subtotal:", _dinero(subtotal)],
         [f"ITBMS ({db.ITBMS_RATE:.0%}):", _dinero(itbms)],
         ["Total:", _dinero(total)]],
        colWidths=[4 * cm, 4 * cm], hAlign="RIGHT",
    )
    t.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("LINEABOVE", (0, 2), (-1, 2), 0.8, colors.black),
    ]))
    return t


def exportar_cotizacion(cotizacion_id: int, ruta: str) -> None:
    conn = db.get_connection()
    try:
        cot = conn.execute("SELECT * FROM cotizaciones WHERE id = ?", (cotizacion_id,)).fetchone()
        if cot is None:
            raise ValueError("La cotización no existe.")
        cliente = conn.execute("SELECT * FROM clientes WHERE id = ?", (cot["cliente_id"],)).fetchone()
        items = db.obtener_items(cotizacion_id, conn)
    finally:
        conn.close()

    estilos = getSampleStyleSheet()
    doc = SimpleDocTemplate(ruta, pagesize=letter, title=f"Cotización {cot['numero']}",
                            leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm)
    elementos = _encabezado(estilos, "COTIZACIÓN", cot["numero"], cot["fecha"], cliente,
                            extra=[("Estado", cot["estado"])])

    filas = [["Descripción", "Cantidad", "Precio unitario", "Importe"]]
    for desc, cant, precio in items:
        filas.append([Paragraph(_esc(desc), estilos["Normal"]), f"{cant:g}", _dinero(precio), _dinero(cant * precio)])
    tabla = Table(filas, colWidths=[8 * cm, 2 * cm, 3.5 * cm, 3.5 * cm], repeatRows=1)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elementos += [tabla, Spacer(1, 0.5 * cm), _tabla_totales(cot["subtotal"], cot["itbms"], cot["total"])]
    if cot["notas"]:
        elementos += [Spacer(1, 0.7 * cm), Paragraph(f"<b>Notas:</b> {_esc(cot['notas'])}", estilos["Normal"])]
    doc.build(elementos)


def exportar_factura(factura_id: int, ruta: str) -> None:
    conn = db.get_connection()
    try:
        fac = conn.execute("SELECT * FROM facturas WHERE id = ?", (factura_id,)).fetchone()
        if fac is None:
            raise ValueError("La factura no existe.")
        cliente = conn.execute("SELECT * FROM clientes WHERE id = ?", (fac["cliente_id"],)).fetchone()
        cot = None
        if fac["cotizacion_id"]:
            cot = conn.execute("SELECT numero, subtotal, itbms FROM cotizaciones WHERE id = ?",
                               (fac["cotizacion_id"],)).fetchone()
    finally:
        conn.close()

    if cot:
        subtotal, itbms = cot["subtotal"], cot["itbms"]
    else:  # sin cotización de origen: se deriva del total
        subtotal = round(fac["total"] / (1 + db.ITBMS_RATE), 2)
        itbms = round(fac["total"] - subtotal, 2)

    extra = [("Estado de pago", fac["estado_pago"])]
    if fac["fecha_pago"]:
        extra.append(("Fecha de pago", fac["fecha_pago"]))
    if cot:
        extra.append(("Cotización de origen", cot["numero"]))

    estilos = getSampleStyleSheet()
    doc = SimpleDocTemplate(ruta, pagesize=letter, title=f"Factura {fac['numero']}",
                            leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm)
    elementos = _encabezado(estilos, "FACTURA", fac["numero"], fac["fecha"], cliente, extra=extra)
    elementos.append(_tabla_totales(subtotal, itbms, fac["total"]))
    doc.build(elementos)
