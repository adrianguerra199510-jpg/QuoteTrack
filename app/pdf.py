"""Exportación de cotizaciones y facturas a PDF con reportlab."""
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from app import db


def _dinero(valor: float) -> str:
    return f"B/. {valor:,.2f}"


def _esc(texto: str) -> str:
    return (texto or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _estilos():
    """Estilos base con interlineado explícito para que las líneas del encabezado no se solapen."""
    estilos = getSampleStyleSheet()
    estilos["Title"].leading = 32
    estilos["Title"].spaceAfter = 12
    estilos["Normal"].leading = 15
    estilos["Normal"].spaceAfter = 2
    estilos["Heading3"].leading = 18
    estilos["Heading3"].spaceBefore = 6
    estilos["Heading3"].spaceAfter = 4
    estilos["Heading3"].keepWithNext = 1
    estilos.add(ParagraphStyle("Notas", parent=estilos["Normal"], leading=14, spaceAfter=0))
    estilos.add(ParagraphStyle("NotasSeccion", parent=estilos["Notas"], keepWithNext=1))
    estilos.add(ParagraphStyle("NotasViñeta", parent=estilos["Notas"], leftIndent=14, bulletIndent=2))
    return estilos


def _bloque_notas(estilos, notas):
    """Notas bajo el total: un párrafo por línea (respeta saltos de línea y viñetas con sangría
    francesa). Platypus los reparte entre páginas sin partir palabras ni solapar con los totales."""
    if not (notas or "").strip():
        return []
    elementos = [
        Spacer(1, 0.8 * cm),
        Paragraph("Alcance, exclusiones y condiciones", estilos["Heading3"]),
    ]
    for linea in notas.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        texto = linea.strip()
        if not texto:
            elementos.append(Spacer(1, 0.25 * cm))
        elif texto[0] in "•-" and len(texto) > 1 and texto[1] in " \t":
            elementos.append(Paragraph(_esc(texto[1:].strip()), estilos["NotasViñeta"], bulletText="•"))
        elif texto.isupper():  # encabezado de sección (ALCANCE, EXCLUSIONES…): no se deja solo al pie
            elementos.append(Paragraph(f"<b>{_esc(texto)}</b>", estilos["NotasSeccion"]))
        else:
            elementos.append(Paragraph(_esc(texto), estilos["Notas"]))
    return elementos


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


ANCHO_EMPRESA = 9 * cm


def _bloque_empresa(estilos, conn):
    """Nombre, subtítulo y correo alineados a la derecha, cada uno en su línea con interlineado
    propio. Si una línea es más ancha que el bloque, se reduce la fuente para que no se desborde."""
    lineas = [
        (db.obtener_opcion("empresa_nombre", conn).strip(), "Helvetica-Bold", 16),
        (db.obtener_opcion("empresa_subtitulo", conn).strip(), "Helvetica", 10),
        (db.obtener_opcion("empresa_correo", conn).strip(), "Helvetica", 9),
    ]
    elementos = []
    for texto, fuente, tam in lineas:
        if not texto:
            continue
        while tam > 6 and stringWidth(texto, fuente, tam) > ANCHO_EMPRESA:
            tam -= 0.5
        estilo = ParagraphStyle(f"emp{len(elementos)}", parent=estilos["Normal"], fontName=fuente,
                                fontSize=tam, leading=tam * 1.4, alignment=TA_RIGHT, spaceAfter=3)
        elementos.append(Paragraph(_esc(texto), estilo))
    if elementos:
        elementos.append(Spacer(1, 0.3 * cm))
    return elementos


def _tabla_totales(subtotal, itbms, total):
    etiqueta_itbms = "ITBMS (exento):" if itbms == 0 else f"ITBMS ({itbms / subtotal:.0%}):" if subtotal else "ITBMS:"
    t = Table(
        [["Subtotal:", _dinero(subtotal)],
         [etiqueta_itbms, _dinero(itbms)],
         ["Total:", _dinero(total)]],
        colWidths=[4 * cm, 4 * cm], hAlign="RIGHT",
    )
    t.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("LINEABOVE", (0, 2), (-1, 2), 0.8, colors.black),
    ]))
    return t


def exportar_cotizacion(cotizacion_id: int, ruta: str, mostrar_estado: bool | None = None) -> None:
    """`mostrar_estado=None` usa la opción de Configuración (desactivada por defecto)."""
    conn = db.get_connection()
    try:
        cot = conn.execute("SELECT * FROM cotizaciones WHERE id = ?", (cotizacion_id,)).fetchone()
        if cot is None:
            raise ValueError("La cotización no existe.")
        cliente = conn.execute("SELECT * FROM clientes WHERE id = ?", (cot["cliente_id"],)).fetchone()
        items = db.obtener_items(cotizacion_id, conn)
        if mostrar_estado is None:
            mostrar_estado = db.mostrar_estado_pdf(conn)
        empresa = _bloque_empresa(_estilos(), conn)
    finally:
        conn.close()

    estilos = _estilos()
    doc = SimpleDocTemplate(ruta, pagesize=letter, title=f"Cotización {cot['numero']}",
                            leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm)
    extra = []
    if cot["proyecto"]:
        extra.append(("Proyecto", cot["proyecto"]))
    if mostrar_estado:
        extra.append(("Estado", cot["estado"]))
    elementos = empresa + _encabezado(estilos, "COTIZACIÓN", cot["numero"], cot["fecha"], cliente, extra=extra)

    filas = [["Descripción", "Cantidad", "Precio unitario", "Importe"]]
    for desc, cant, precio in items:
        filas.append([Paragraph(_esc(desc).replace("\n", "<br/>"), estilos["Normal"]), f"{cant:g}", _dinero(precio), _dinero(cant * precio)])
    tabla = Table(filas, colWidths=[8 * cm, 2 * cm, 3.5 * cm, 3.5 * cm], repeatRows=1)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elementos += [tabla, Spacer(1, 0.5 * cm), _tabla_totales(cot["subtotal"], cot["itbms"], cot["total"])]
    elementos += _bloque_notas(estilos, cot["notas"])
    doc.build(elementos)


def exportar_factura(factura_id: int, ruta: str, mostrar_estado: bool | None = None) -> None:
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
        if mostrar_estado is None:
            mostrar_estado = db.mostrar_estado_pdf(conn)
        tasa = db.obtener_tasa_itbms(conn)
        empresa = _bloque_empresa(_estilos(), conn)
    finally:
        conn.close()

    if cot:
        subtotal, itbms = cot["subtotal"], cot["itbms"]
    else:  # sin cotización de origen: se deriva del total
        subtotal = round(fac["total"] / (1 + tasa), 2)
        itbms = round(fac["total"] - subtotal, 2)

    extra = [("Estado de pago", fac["estado_pago"])] if mostrar_estado else []
    if fac["fecha_pago"]:
        extra.append(("Fecha de pago", fac["fecha_pago"]))
    if cot:
        extra.append(("Cotización de origen", cot["numero"]))

    estilos = _estilos()
    doc = SimpleDocTemplate(ruta, pagesize=letter, title=f"Factura {fac['numero']}",
                            leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm)
    elementos = empresa + _encabezado(estilos, "FACTURA", fac["numero"], fac["fecha"], cliente, extra=extra)
    elementos.append(_tabla_totales(subtotal, itbms, fac["total"]))
    elementos += _bloque_notas(estilos, fac["notas"])
    doc.build(elementos)
