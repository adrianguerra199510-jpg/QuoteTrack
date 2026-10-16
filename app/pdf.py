"""Exportación de cotizaciones y facturas a PDF con reportlab."""
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Image, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from app import calculo, db


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
ANCHO_UTIL = 17.5 * cm


def _lineas_empresa(estilos, empresa):
    """Nombre, subtítulo, RUC, dirección, teléfono y correo de la empresa, alineados a la derecha, cada
    uno en su línea con interlineado propio. Si una línea es más ancha que el bloque, se reduce la
    fuente (y si aun así no cabe, se parte en varias líneas) para que nunca se desborde ni se solape."""
    datos = [
        (empresa["nombre"], "Helvetica-Bold", 16),
        (empresa["subtitulo"], "Helvetica", 10),
        (f"RUC: {empresa['ruc']}" if empresa["ruc"] else "", "Helvetica", 9),
        (empresa["direccion"], "Helvetica", 9),
        (f"Tel.: {empresa['telefono']}" if empresa["telefono"] else "", "Helvetica", 9),
        (empresa["correo"], "Helvetica", 9),
    ]
    elementos = []
    for texto, fuente, tam in datos:
        texto = (texto or "").strip()
        if not texto:
            continue
        while tam > 6 and stringWidth(texto, fuente, tam) > ANCHO_EMPRESA:
            tam -= 0.5
        estilo = ParagraphStyle(f"emp{len(elementos)}", parent=estilos["Normal"], fontName=fuente,
                                fontSize=tam, leading=tam * 1.4, alignment=TA_RIGHT, spaceAfter=3)
        elementos.append(Paragraph(_esc(texto), estilo))
    return elementos


def _logo(empresa, alto_max=2.4 * cm, ancho_max=6 * cm):
    datos = empresa["logo"]
    if not datos:
        return ""
    try:
        img = Image(io.BytesIO(datos))
        escala = min(ancho_max / img.imageWidth, alto_max / img.imageHeight)
        img.drawWidth, img.drawHeight = img.imageWidth * escala, img.imageHeight * escala
        img.hAlign = "LEFT"
        return img
    except Exception:  # logo corrupto: se imprime sin logo
        return ""


def _bloque_empresa(estilos, empresa):
    """Encabezado: logo a la izquierda (si hay) y datos de la empresa a la derecha."""
    if empresa is None:
        return []
    t = Table([[_logo(empresa), _lineas_empresa(estilos, empresa)]],
              colWidths=[ANCHO_UTIL - ANCHO_EMPRESA, ANCHO_EMPRESA])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return [t, Spacer(1, 0.3 * cm)]


def _tabla_totales(t):
    """Subtotal, costos adicionales, ITBMS y total a partir de un `calculo.Totales`."""
    filas = [["Subtotal:", _dinero(t.subtotal)]]
    for cargo, monto in t.cargos:
        etiqueta = f"{cargo.concepto} ({cargo.valor:g}%):" if cargo.tipo == "porcentaje" else f"{cargo.concepto}:"
        filas.append([etiqueta, _dinero(monto)])
    if t.itbms == 0:
        etiqueta_itbms = "ITBMS (exento):"
    else:
        etiqueta_itbms = f"ITBMS ({t.tasa:.0%}):" if t.tasa else "ITBMS:"
    filas += [[etiqueta_itbms, _dinero(t.itbms)], ["Total:", _dinero(t.total)]]
    tabla = Table(filas, colWidths=[7 * cm, 3.8 * cm], hAlign="RIGHT")
    tabla.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, len(filas) - 1), (-1, len(filas) - 1), "Helvetica-Bold"),
        ("LINEABOVE", (0, len(filas) - 1), (-1, len(filas) - 1), 0.8, colors.black),
    ]))
    return tabla


def _tabla_items(estilos, lineas, tasa):
    """Tabla de ítems con código jerárquico (01, 01.1…); los grupos van en negrita con su subtotal."""
    cods, imps = calculo.codigos(lineas), calculo.importes(lineas)
    hay_exentos = tasa > 0 and any(not l.es_grupo and not l.aplica_itbms for l in lineas)
    filas = [["Ítem", "Descripción", "Cantidad", "Precio unitario", "Importe"]]
    estilo_sub = ParagraphStyle("sub", parent=estilos["Normal"], leftIndent=8)
    grupos = []
    for i, l in enumerate(lineas):
        desc = _esc(l.descripcion).replace("\n", "<br/>")
        if l.es_grupo:
            grupos.append(len(filas))
            filas.append([cods[i], Paragraph(f"<b>{desc}</b>", estilos["Normal"]), "", "", _dinero(imps[i])])
            continue
        if hay_exentos and not l.aplica_itbms:
            desc += ' <font size="7" color="#666666">(exento de ITBMS)</font>'
        estilo = estilo_sub if l.nivel == 1 else estilos["Normal"]
        filas.append([cods[i], Paragraph(desc, estilo), f"{l.cantidad:g}", _dinero(l.precio), _dinero(imps[i])])
    tabla = Table(filas, colWidths=[1.5 * cm, 7.4 * cm, 1.8 * cm, 3.4 * cm, 3.4 * cm], repeatRows=1)
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    for r in grupos:
        estilo += [("BACKGROUND", (0, r), (-1, r), colors.whitesmoke), ("FONTNAME", (0, r), (-1, r), "Helvetica-Bold")]
    tabla.setStyle(TableStyle(estilo))
    return tabla


def exportar_cotizacion(cotizacion_id: int, ruta: str, mostrar_estado: bool | None = None) -> None:
    """`mostrar_estado=None` usa la opción de Configuración (desactivada por defecto)."""
    conn = db.get_connection()
    try:
        cot = conn.execute("SELECT * FROM cotizaciones WHERE id = ?", (cotizacion_id,)).fetchone()
        if cot is None:
            raise ValueError("La cotización no existe.")
        cliente = conn.execute("SELECT * FROM clientes WHERE id = ?", (cot["cliente_id"],)).fetchone()
        lineas = db.obtener_lineas(cotizacion_id, conn)
        totales = db.totales_cotizacion(cotizacion_id, conn)
        if mostrar_estado is None:
            mostrar_estado = db.mostrar_estado_pdf(conn)
        empresa = db.empresa_de_cotizacion(cotizacion_id, conn)
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
    elementos = _bloque_empresa(estilos, empresa) + _encabezado(
        estilos, "COTIZACIÓN", cot["numero"], cot["fecha"], cliente, extra=extra)
    elementos += [_tabla_items(estilos, lineas, totales.tasa), Spacer(1, 0.5 * cm), _tabla_totales(totales)]
    elementos += _bloque_notas(estilos, cot["notas"])
    doc.build(elementos)


def exportar_factura(factura_id: int, ruta: str, mostrar_estado: bool | None = None) -> None:
    conn = db.get_connection()
    try:
        fac = conn.execute("SELECT * FROM facturas WHERE id = ?", (factura_id,)).fetchone()
        if fac is None:
            raise ValueError("La factura no existe.")
        cliente = conn.execute("SELECT * FROM clientes WHERE id = ?", (fac["cliente_id"],)).fetchone()
        empresa = db.empresa_de_factura(factura_id, conn)
        cot = None
        if fac["cotizacion_id"]:
            cot = conn.execute("SELECT numero FROM cotizaciones WHERE id = ?", (fac["cotizacion_id"],)).fetchone()
            totales = db.totales_cotizacion(fac["cotizacion_id"], conn)
        else:  # sin cotización de origen: se deriva del total con la tasa de la empresa
            tasa = (empresa["itbms_tasa"] / 100) if empresa else 0.0
            subtotal = round(fac["total"] / (1 + tasa), 2)
            totales = calculo.Totales(subtotal=subtotal, tasa=tasa, itbms=round(fac["total"] - subtotal, 2),
                                      total=fac["total"])
        if mostrar_estado is None:
            mostrar_estado = db.mostrar_estado_pdf(conn)
    finally:
        conn.close()

    extra = [("Estado de pago", fac["estado_pago"])] if mostrar_estado else []
    if fac["fecha_pago"]:
        extra.append(("Fecha de pago", fac["fecha_pago"]))
    if cot:
        extra.append(("Cotización de origen", cot["numero"]))

    estilos = _estilos()
    doc = SimpleDocTemplate(ruta, pagesize=letter, title=f"Factura {fac['numero']}",
                            leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm)
    elementos = _bloque_empresa(estilos, empresa) + _encabezado(
        estilos, "FACTURA", fac["numero"], fac["fecha"], cliente, extra=extra)
    elementos.append(_tabla_totales(totales))
    elementos += _bloque_notas(estilos, fac["notas"])
    doc.build(elementos)
