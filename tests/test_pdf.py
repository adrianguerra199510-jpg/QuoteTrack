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
    pdf.exportar_cotizacion(1, str(ruta), mostrar_borrador=True)
    assert "borrador" in contenido(ruta)


def test_otros_estados_se_siguen_imprimiendo(conn, tmp_path, pdf_sin_comprimir):
    db.cambiar_estado_cotizacion(1, "enviada", conn)
    ruta = tmp_path / "c.pdf"
    pdf.exportar_cotizacion(1, str(ruta))
    assert "enviada" in contenido(ruta)


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
