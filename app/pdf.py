"""Exportación de cotizaciones y facturas a PDF con reportlab."""
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Image, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from app import calculo, db, documento, texto_rico


def _dinero(valor: float) -> str:
    return f"B/. {valor:,.2f}"


def _esc(texto: str) -> str:
    return (texto or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _markup(tramos) -> str:
    """Marcado de reportlab (<b>, <i>, <u>) de los tramos de un párrafo."""
    out = ""
    for t in tramos:
        h = _esc(t.texto).replace("\n", "<br/>")
        for activo, e in ((t.subrayado, "u"), (t.cursiva, "i"), (t.negrita, "b")):
            if activo:
                h = f"<{e}>{h}</{e}>"
        out += h
    return out


def _parrafos_desc(texto, estilo, negrita=False, sufijo=""):
    """Descripción de un ítem (con formato) como lista de párrafos de reportlab, con viñetas y numeración."""
    parrafos = texto_rico.parsear(texto) or [texto_rico.Parrafo("p", [])]
    res = []
    for n, p in enumerate(parrafos):
        cuerpo = _markup(p.tramos) or "&nbsp;"
        if negrita:
            cuerpo = f"<b>{cuerpo}</b>"
        if n == len(parrafos) - 1:
            cuerpo += sufijo
        if p.tipo == "p":
            res.append(Paragraph(cuerpo, estilo))
        else:
            marca = "•" if p.tipo == "ul" else f"{p.numero}."
            st = ParagraphStyle("li", parent=estilo, leftIndent=estilo.leftIndent + 12, bulletIndent=estilo.leftIndent)
            res.append(Paragraph(cuerpo, st, bulletText=marca))
    return res


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
    estilos.add(ParagraphStyle("NotasViñeta2", parent=estilos["Notas"], leftIndent=28, bulletIndent=16))
    return estilos


def _bloque_notas(estilos, notas, titulo=""):
    """Notas bajo el total: un párrafo por línea (respeta saltos de línea y viñetas con sangría
    francesa). Platypus los reparte entre páginas sin partir palabras ni solapar con los totales."""
    if not (notas or "").strip():
        return []
    elementos = [
        Spacer(1, 0.8 * cm),
        Paragraph(_esc((titulo or "").strip() or db.TITULO_NOTAS), estilos["Heading3"]),
    ]
    for linea in notas.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        texto = linea.strip()
        sangrada = len(linea) - len(linea.lstrip()) >= 2          # viñeta de segundo nivel (empieza con espacios)
        if not texto:
            elementos.append(Spacer(1, 0.25 * cm))
        elif texto[0] in "•-" and len(texto) > 1 and texto[1] in " \t":
            elementos.append(Paragraph(_esc(texto[1:].strip()), estilos["NotasViñeta2" if sangrada else "NotasViñeta"],
                                       bulletText="–" if sangrada else "•"))
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
    filas = [[etiqueta, _dinero(monto)] for etiqueta, monto, _total in documento.etiquetas_totales(t)]
    tabla = Table(filas, colWidths=[7 * cm, 3.8 * cm], hAlign="RIGHT")
    tabla.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, len(filas) - 1), (-1, len(filas) - 1), "Helvetica-Bold"),
        ("LINEABOVE", (0, len(filas) - 1), (-1, len(filas) - 1), 0.8, colors.black),
    ]))
    return tabla


def _bloque_etapa(estilos, doc_datos):
    """Facturas por etapas: concepto y resumen de lo facturado de la cotización."""
    elementos = []
    if doc_datos.concepto:
        elementos += [Paragraph(f"<b>Concepto:</b> {_esc(doc_datos.concepto)}", estilos["Normal"]), Spacer(1, 0.4 * cm)]
    if doc_datos.resumen:
        filas = [[etiqueta, _dinero(monto)] for etiqueta, monto, _ultimo in doc_datos.resumen]
        t = Table(filas, colWidths=[7 * cm, 3.8 * cm], hAlign="RIGHT")
        t.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#444444")),
            ("FONTNAME", (0, len(filas) - 1), (-1, len(filas) - 1), "Helvetica-Bold"),
        ]))
        elementos += [t, Spacer(1, 0.4 * cm)]
    return elementos


def _tabla_items(estilos, lineas, tasa):
    """Tabla de ítems con código jerárquico (01, 01.1…); los grupos van en negrita con su subtotal."""
    cods, imps = calculo.codigos(lineas), calculo.importes(lineas)
    hay_exentos = tasa > 0 and any(not l.es_grupo and not l.aplica_itbms for l in lineas)
    filas = [["Ítem", "Descripción", "Ud.", "Cantidad", "Precio unitario", "Importe"]]
    estilo_sub = ParagraphStyle("sub", parent=estilos["Normal"], leftIndent=8)
    grupos = []
    for i, l in enumerate(lineas):
        if l.es_grupo:
            grupos.append(len(filas))
            filas.append([cods[i], _parrafos_desc(texto_rico.con_titulo(l.titulo, l.descripcion), estilos["Normal"], negrita=True), "", "", "", _dinero(imps[i])])
            continue
        sufijo = ' <font size="7" color="#666666">(exento de ITBMS)</font>' if hay_exentos and not l.aplica_itbms else ""
        estilo = estilo_sub if l.nivel == 1 else estilos["Normal"]
        filas.append([cods[i], _parrafos_desc(texto_rico.con_titulo(l.titulo, l.descripcion), estilo, sufijo=sufijo), l.unidad, f"{l.cantidad:g}", _dinero(l.precio_mostrado), _dinero(imps[i])])
    tabla = Table(filas, colWidths=[1.4 * cm, 6.5 * cm, 1.4 * cm, 1.8 * cm, 3.2 * cm, 3.2 * cm], repeatRows=1)
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (2, 0), (2, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    for r in grupos:
        estilo += [("BACKGROUND", (0, r), (-1, r), colors.whitesmoke), ("FONTNAME", (0, r), (-1, r), "Helvetica-Bold")]
    tabla.setStyle(TableStyle(estilo))
    return tabla


def _construir(doc_datos: documento.Documento, ruta: str) -> None:
    estilos = _estilos()
    pdf = SimpleDocTemplate(ruta, pagesize=letter, title=f"{doc_datos.titulo.title()} {doc_datos.numero}",
                            leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm)
    elementos = _bloque_empresa(estilos, doc_datos.empresa) + _encabezado(
        estilos, doc_datos.titulo, doc_datos.numero, doc_datos.fecha, doc_datos.cliente, extra=doc_datos.extra)
    if doc_datos.lineas is not None:
        elementos += [_tabla_items(estilos, doc_datos.lineas, doc_datos.totales.tasa), Spacer(1, 0.5 * cm)]
    elementos += _bloque_etapa(estilos, doc_datos)
    elementos.append(_tabla_totales(doc_datos.totales))
    elementos += _bloque_notas(estilos, doc_datos.notas, doc_datos.titulo_notas)
    pdf.build(elementos)


def exportar_cotizacion(cotizacion_id: int, ruta: str, mostrar_estado: bool | None = None) -> None:
    """`mostrar_estado=None` usa la opción de Configuración (desactivada por defecto)."""
    _construir(documento.de_cotizacion(cotizacion_id, mostrar_estado), ruta)


def exportar_factura(factura_id: int, ruta: str, mostrar_estado: bool | None = None) -> None:
    _construir(documento.de_factura(factura_id, mostrar_estado), ruta)
