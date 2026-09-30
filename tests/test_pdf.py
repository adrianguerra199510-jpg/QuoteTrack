import re

from app import db, pdf


def paginas(ruta):
    return len(re.findall(rb"/Type /Page\b", ruta.read_bytes()))


def contenido(ruta):
    return ruta.read_bytes().decode("latin-1")


def test_notas_bajo_el_total_con_titulo(conn, tmp_path, pdf_sin_comprimir):
    db.guardar_notas(1, "Primera condicion\nSegunda condicion", conn)
    ruta = tmp_path / "c.pdf"
    pdf.exportar_cotizacion(1, str(ruta))
    txt = contenido(ruta)
    assert "Alcance, exclusiones y condiciones" in txt
    assert "Primera condicion" in txt and "Segunda condicion" in txt
    # orden: total -> título de notas -> notas
    assert txt.index("Total:") < txt.index("Alcance, exclusiones") < txt.index("Primera condicion")
    # cada línea se dibuja por separado (respeta los saltos de línea)
    assert txt.index("Primera condicion") != txt.index("Segunda condicion")


def test_sin_notas_no_imprime_seccion(conn, tmp_path, pdf_sin_comprimir):
    ruta = tmp_path / "c.pdf"
    pdf.exportar_cotizacion(1, str(ruta))
    assert "Alcance, exclusiones" not in contenido(ruta)


def test_notas_largas_paginan(conn, tmp_path):
    db.guardar_notas(1, "\n".join(f"Condicion numero {i}" for i in range(150)), conn)
    ruta = tmp_path / "c.pdf"
    pdf.exportar_cotizacion(1, str(ruta))
    assert paginas(ruta) >= 2


def test_notas_cortas_una_pagina(conn, tmp_path):
    db.guardar_notas(1, "Una sola nota", conn)
    ruta = tmp_path / "c.pdf"
    pdf.exportar_cotizacion(1, str(ruta))
    assert paginas(ruta) == 1


def test_caracteres_especiales_en_notas(conn, tmp_path):
    db.guardar_notas(1, "Precio < 100 & <b>no negrita</b>", conn)
    pdf.exportar_cotizacion(1, str(tmp_path / "c.pdf"))  # no debe lanzar


def test_borrador_oculto_por_defecto(conn, tmp_path, pdf_sin_comprimir):
    ruta = tmp_path / "c.pdf"
    pdf.exportar_cotizacion(1, str(ruta))
    assert "borrador" not in contenido(ruta)


def test_borrador_visible_con_opcion(conn, tmp_path, pdf_sin_comprimir):
    ruta = tmp_path / "c.pdf"
    pdf.exportar_cotizacion(1, str(ruta), mostrar_estado=True)
    assert "borrador" in contenido(ruta)


def test_ningun_estado_se_imprime_por_defecto(conn, tmp_path, pdf_sin_comprimir):
    db.cambiar_estado_cotizacion(1, "enviada", conn)
    ruta = tmp_path / "c.pdf"
    pdf.exportar_cotizacion(1, str(ruta))
    assert "Estado" not in contenido(ruta) and "enviada" not in contenido(ruta)


def test_opcion_de_configuracion_muestra_estado(conn, tmp_path, pdf_sin_comprimir):
    db.guardar_config("mostrar_estado_pdf", "1", conn)
    ruta = tmp_path / "c.pdf"
    pdf.exportar_cotizacion(1, str(ruta))
    assert "Estado" in contenido(ruta) and "borrador" in contenido(ruta)


def test_factura_imprime_notas_copiadas(conn, tmp_path, pdf_sin_comprimir):
    db.guardar_notas(1, "Condicion de factura", conn)
    db.cambiar_estado_cotizacion(1, "enviada", conn)
    db.cambiar_estado_cotizacion(1, "aprobada", conn)
    db.generar_factura(1, conn)
    ruta = tmp_path / "f.pdf"
    pdf.exportar_factura(1, str(ruta))
    txt = contenido(ruta)
    assert "Alcance, exclusiones y condiciones" in txt and "Condicion de factura" in txt


def test_encabezado_sin_solapamiento():
    """El interlineado de las líneas del encabezado debe superar el tamaño de fuente."""
    est = pdf._estilos()
    for nombre in ("Title", "Normal", "Heading3", "Notas"):
        assert est[nombre].leading >= est[nombre].fontSize * 1.2, nombre


def test_encabezado_empresa_con_nombres_largos(conn, tmp_path):
    db.guardar_config("empresa_nombre", "INTEGRO " + "SOCIEDAD ANONIMA " * 4, conn)
    db.guardar_config("empresa_correo", "correo.muy.largo.sin.espacios." * 4 + "@ejemplo.com", conn)
    lineas = pdf._bloque_empresa(pdf._estilos(), conn)
    for p in lineas[:-1]:
        w, h = p.wrap(pdf.ANCHO_EMPRESA, 1000)
        assert w <= pdf.ANCHO_EMPRESA + 1
        assert h >= p.style.leading  # cada línea ocupa su propio interlineado: sin solapes
    pdf.exportar_cotizacion(1, str(tmp_path / "c.pdf"))


def test_itbms_exento_en_pdf(conn, tmp_path, pdf_sin_comprimir):
    db.guardar_config("itbms_tasa", "0", conn)
    db.guardar_items(1, [("x", 1, 100.0)], conn)
    ruta = tmp_path / "c.pdf"
    pdf.exportar_cotizacion(1, str(ruta))
    assert "ITBMS \\(exento\\)" in contenido(ruta)  # los paréntesis se escapan en el PDF


def test_descripcion_multilinea_y_viñetas(conn, tmp_path, pdf_sin_comprimir):
    db.guardar_items(1, [("Linea uno\nLinea dos " + "palabra " * 80, 1, 23551.60)], conn)
    db.guardar_notas(1, "• Primera viñeta\n- Segunda viñeta", conn)
    ruta = tmp_path / "c.pdf"
    pdf.exportar_cotizacion(1, str(ruta))
    txt = contenido(ruta)
    assert "B/. 23,551.60" in txt and "Linea uno" in txt and "Segunda vi" in txt


def test_encabezado_de_seccion_no_queda_solo_al_pie():
    from reportlab.platypus import Paragraph
    elementos = pdf._bloque_notas(pdf._estilos(), "ALCANCE\n• uno\n\nEXCLUSIONES\n• dos")
    secciones = [e for e in elementos if isinstance(e, Paragraph) and e.style.name == "NotasSeccion"]
    assert len(secciones) == 2 and all(e.style.keepWithNext for e in secciones)
