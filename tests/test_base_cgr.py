import importlib.util
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from app import base_cgr, calculo, db, ui_biblioteca
from app.calculo import Apu, Concepto, Insumo, OBRA, SERVICIO


def cargar_generador():
    spec = importlib.util.spec_from_file_location(
        "generar_base_cgr", Path(__file__).resolve().parent.parent / "scripts" / "generar_base_cgr.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def datos():
    return base_cgr.cargar()


def como_concepto(d) -> Concepto:
    return Concepto(None, d["descripcion"], d["unidad"], OBRA, 0.0, d["categoria"], Apu(1.0, [Insumo(*i) for i in d["insumos"]]))


# ----------------------------------------------------------------- el archivo de datos empaquetado
def test_archivo_completo_y_consistente(datos):
    cs = datos["conceptos"]
    assert len(cs) == 1169
    assert [c["codigo"] for c in cs] == [str(n) for n in range(46, 46 + 1169)]      # páginas 46 a 1214, sin saltos
    assert all(c["descripcion"].strip() and c["unidad"] and c["categoria"] for c in cs)
    assert all(c["insumos"] for c in cs)
    assert "Contraloría" in datos["fuente"] or "CGR" in datos["fuente"]


def test_el_costo_calculado_coincide_con_el_publicado(datos):
    """Para cada actividad con análisis, la suma de sus insumos reproduce el costo unitario del PDF (±0.5 %)."""
    sin_analisis = []
    for c in datos["conceptos"]:
        calculado = calculo.costo_unitario(como_concepto(c).apu)
        if not c["analisis"]:
            sin_analisis.append(c["codigo"])
            assert len(c["insumos"]) == 1 and c["insumos"][0][5] == c["costo"]          # costo publicado en una fila
            continue
        assert calculado == pytest.approx(c["costo"], abs=max(0.05, c["costo"] * 0.005)), c["codigo"]
    assert sorted(sin_analisis, key=int) == ["736", "737", "837", "838", "839", "840", "868", "869", "877", "878", "896", "983"]


@pytest.mark.parametrize("codigo, costo, categoria, unidad", [
    ("46", 0.70, "ALBAÑILERÍA › LIMPIEZA, REPLANTEO, DEMOLICIÓN Y EXCAVACIÓN", "m²"),
    ("68", 199.88, "ALBAÑILERÍA › CONCRETOS", "m³"),
    ("81", 35.56, "ALBAÑILERÍA › MUROS DE BLOQUES", "m²"),
    ("119", 17.57, "ALBAÑILERÍA › PISOS", "m²"),
])
def test_actividades_de_referencia(datos, codigo, costo, categoria, unidad):
    c = next(x for x in datos["conceptos"] if x["codigo"] == codigo)
    assert (c["costo"], c["categoria"], c["unidad"]) == (costo, categoria, unidad)
    assert calculo.costo_unitario(como_concepto(c).apu) == pytest.approx(costo, abs=0.02)


def test_herramienta_es_porcentaje_de_la_mano_de_obra(datos):
    c = next(x for x in datos["conceptos"] if x["codigo"] == "81")
    herramienta = [i for i in c["insumos"] if i[6]]
    assert herramienta == [["auxiliar", "HERRAMIENTAS EN GENERAL", "%", 1.0, 0.035, 0.0, "mano_obra"]]
    categorias = {i[0] for i in c["insumos"]}
    assert categorias == {"material", "mano_obra", "auxiliar"}


def test_matrices_y_cuadrillas(datos):
    piso = next(x for x in datos["conceptos"] if x["codigo"] == "119")       # lleva «Matrices» (formaleta, grado final)
    assert any("FORMALETA" in i[1] for i in piso["insumos"])
    viga = next(x for x in datos["conceptos"] if x["codigo"] == "1148")      # FECE: cuadrilla con rendimiento
    cuadrilla = next(i for i in viga["insumos"] if "ENCOFRADO" in i[1])
    assert cuadrilla[3] == pytest.approx(1 / 1.515152, rel=1e-4)             # cantidad = 1 / rendimiento


def test_palabras_pegadas_corregidas(datos):
    textos = " ".join(c["descripcion"] for c in datos["conceptos"])
    for pegada in ("COMPACTADOMANUALMENTE", "ESPESORHASTA", "MATERIALEXISTENTE"):
        assert pegada not in textos


def test_las_once_disciplinas(datos):
    disciplinas = {c["categoria"].split(" › ")[0] for c in datos["conceptos"]}
    assert disciplinas == {"ALBAÑILERÍA", "TECHOS", "ACABADOS Y REMODELACIONES", "CARRETERAS",
                           "ACUEDUCTOS Y ALCANTARILLADOS", "PLOMERÍA", "ELECTRICIDAD", "ESTRUCTURAS METÁLICAS",
                           "PUERTAS Y VENTANAS", "VIGADUCTOS Y CI ELÉCTRICOS", "FECE"}


# ----------------------------------------------------------------- importación a la biblioteca
def test_importar_es_idempotente_y_respeta_lo_propio(conn):
    propio = db.guardar_concepto(Concepto(None, "Mi concepto", "uni", SERVICIO, 10.0, "Mis cosas"), conn)
    nuevos, actualizados, fuente = base_cgr.importar(conn)
    assert (nuevos, actualizados) == (1169, 0)
    assert conn.execute("SELECT COUNT(*) AS n FROM conceptos").fetchone()["n"] == 1170
    assert conn.execute("SELECT COUNT(*) AS n FROM concepto_insumos").fetchone()["n"] > 9000
    assert base_cgr.importar(conn)[:2] == (0, 1169)                 # segunda vez: solo actualiza
    assert conn.execute("SELECT COUNT(*) AS n FROM conceptos").fetchone()["n"] == 1170
    assert db.obtener_concepto(propio, conn).precio == 10.0 and db.obtener_concepto(propio, conn).fuente == ""
    c = next(x for x in db.listar_conceptos(conn) if x.codigo == "81")
    assert c.fuente == fuente and c.modalidad == OBRA and db.costo_directo(c) == pytest.approx(35.56, abs=0.02)


def test_reimportar_restaura_los_datos_originales(conn):
    base_cgr.importar(conn)
    c = next(x for x in db.listar_conceptos(conn) if x.codigo == "46")
    c.descripcion = "EDITADO POR EL USUARIO"
    db.guardar_concepto(c, conn)
    base_cgr.importar(conn)
    assert next(x for x in db.listar_conceptos(conn) if x.codigo == "46").descripcion == "LIMPIEZA MANUAL DE TERRENO PARA REPLANTEO"


def test_orden_y_filtros(conn):
    db.guardar_concepto(Concepto(None, "Zeta propio", "uni", SERVICIO, 1.0, "Zeta"), conn)
    base_cgr.importar(conn)
    todos = db.listar_conceptos(conn)
    assert todos[0].descripcion == "Zeta propio"                     # lo propio primero
    assert [c.codigo for c in todos[1:5]] == ["46", "47", "48", "49"]  # lo importado, en el orden de la fuente
    assert db.disciplinas_conceptos(conn)[0] == "ACABADOS Y REMODELACIONES" and "Zeta" in db.disciplinas_conceptos(conn)
    alb = db.listar_conceptos(conn, disciplina="ALBAÑILERÍA")
    assert len(alb) == 96 and all(c.categoria.startswith("ALBAÑILERÍA") for c in alb)
    assert {c.descripcion for c in db.listar_conceptos(conn, "muro de bloques de cemento de 4")} >= {
        "MURO DE BLOQUES DE CEMENTO DE 4\" RELLENO DE CONCRETO (SIN REFUERZO)"}
    assert [c.descripcion for c in db.listar_conceptos(conn, modalidad=SERVICIO)] == ["Zeta propio"]


def test_concepto_importado_se_inserta_en_una_cotizacion(conn):
    base_cgr.importar(conn)
    c = next(x for x in db.listar_conceptos(conn) if x.codigo == "81")
    l = db.linea_desde_concepto(c, 20.0)
    assert l.modalidad == OBRA and l.unidad == "m²" and len(l.apu.insumos) == 7
    t = db.guardar_cotizacion(1, [l], [], conn, cfg=calculo.ConfigApu(0, 0, 0, 0))
    assert t.subtotal == pytest.approx(round(20 * 35.56, 2), abs=0.5)


# ----------------------------------------------------------------- interfaz
def test_boton_importar_base(conn, qapp, monkeypatch):
    infos = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: infos.append(a[2])))
    tab = ui_biblioteca.BibliotecaTab()
    assert tab.tabla.rowCount() == 0 and "vacía" in tab.lbl_total.text()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.No))
    tab.importar_base()
    assert tab.tabla.rowCount() == 0 and not infos                    # cancelar no importa nada
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.Yes))
    tab.importar_base()
    assert tab.tabla.rowCount() == 1169 and "1,169" in infos[0] and "1,169 de 1,169" in tab.lbl_total.text()
    assert tab.disciplina.count() == 12                                # «Todas» + 11 disciplinas
    tab.disciplina.setCurrentIndex(tab.disciplina.findData("PLOMERÍA"))
    assert 0 < tab.tabla.rowCount() == 61
    tab.disciplina.setCurrentIndex(0)
    tab.busqueda.setText("pintura")
    assert 0 < tab.tabla.rowCount() < 1169
    assert tab.tabla.item(0, 4).text().startswith("B/. ")              # costo directo


# ----------------------------------------------------------------- generador (formatos del PDF)
BLOQUE_TUBERIA = """
### Página: 99 Unidad: m2
### Costo Unitario: 100.00
### EJEMPLO
| **C** | **Clave** | **Descripción** | **Unidad** | **Rendimiento** | **Cantidad** | **Costo Unitario** | **Total** |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| **Materiales** | CEMENTO | CEMENTO GRIS TIPO I | SACO | 1.0 | 2.000000 | 10.00 | 20.00 |
|  | BLQ 4 | BLOQUE DE 4" | und | 0.1 | 10.000000 | 1.00 | 10.00 |
**Total de Materiales** **30.00**
**Mano de Obra**
| MOA3-J | CALIFICADO | jor | 10.0 | 0.100000 | 90.00 | 9.00 |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| **Total de Mano de Obra** |  |  |  |  |  | **9.00** |
**Herramienta**
HERR HERRAMIENTAS EN GENERAL (%)mo 28.571429 0.050000 9.00 0.45
**Equipo**
CV CAMIÓN VOLQUETE DE 15 m3 (Incluye combustible) hr 75.000000 0.013333 30.00 0.40
| **Matrices**+ | F-PLWD | FORMALETA | m2 | 20.0 | 0.050000 | 17.00 | 0.85 |
| + | RCMC | RELLENO CON MATERIAL EXISTENTE | m2 | 1.0 | 1.000000 | 2.00 | 2.00 MANUALMENTE. |
"""


def test_generador_lee_los_distintos_formatos_de_fila():
    g = cargar_generador()
    b = g.parsear_bloque(BLOQUE_TUBERIA, 99)
    assert (b["pagina"], b["unidad"], b["titulo"]) == (99, "m2", "EJEMPLO")
    filas = [(i["seccion"], i["clave"], i["descripcion"], i["unidad"], i["cantidad"], i["costo"]) for i in b["insumos"]]
    assert filas == [
        ("material", "CEMENTO", "CEMENTO GRIS TIPO I", "SACO", 2.0, 10.0),
        ("material", "BLQ 4", 'BLOQUE DE 4"', "und", 10.0, 1.0),
        ("mano_obra", "MOA3-J", "CALIFICADO", "jor", 0.1, 90.0),
        ("auxiliar", "HERR", "HERRAMIENTAS EN GENERAL", "(%)mo", 0.05, 9.0),
        ("auxiliar", "CV", "CAMIÓN VOLQUETE DE 15 m3 (Incluye combustible)", "hr", 0.013333, 30.0),
        ("auxiliar", "F-PLWD", "FORMALETA", "m2", 0.05, 17.0),
        ("auxiliar", "RCMC", "RELLENO CON MATERIAL EXISTENTE MANUALMENTE.", "m2", 1.0, 2.0),
    ]
    insumos = g.a_insumos(b["insumos"])
    assert ["auxiliar", "HERRAMIENTAS EN GENERAL", "%", 1.0, 0.05, 0.0, "mano_obra"] in insumos
    assert g.coste(insumos) == pytest.approx(20 + 10 + 9 + 0.45 + 0.4 + 0.85 + 2.0)


def test_generador_deduce_la_pagina_perdida_y_el_indice():
    g = cargar_generador()
    sin_pagina = "\n### Unidad: m Costo Unitario: 2.04\n| MOA1 | AYUDANTE | hr | 1.0 | 1.0 | 8.00 | 8.00 |\n"
    assert g.parsear_bloque(sin_pagina, 838)["pagina"] == 838
    indice = (
        "| 46 | **P0 - BASE DE DATOS DE COSTOS DIRECTOSALBAÑILERÍALIMPIEZA, REPLANTEO, DEMOLICIÓN Y EXCAVACIÓN**"
        "LIMPIEZA MANUAL | m2 | 0.70 |\n| 47 | DEMOLICIÓN DE ACERAS**RELLENOS Y COMPACTACIÓN** | m2 | 6.90 |\n"
        "| 48 | RELLENO MANUAL | m3 | 6.62 |\n")
    filas = g.parsear_indice(indice)
    assert [(f["pagina"], f["descripcion"], f["capitulo"]) for f in filas] == [
        (46, "LIMPIEZA MANUAL", "LIMPIEZA, REPLANTEO, DEMOLICIÓN Y EXCAVACIÓN"),
        (47, "DEMOLICIÓN DE ACERAS", "LIMPIEZA, REPLANTEO, DEMOLICIÓN Y EXCAVACIÓN"),
        (48, "RELLENO MANUAL", "RELLENOS Y COMPACTACIÓN")]
    assert g.disciplina(46) == "ALBAÑILERÍA" and g.disciplina(700) == "PLOMERÍA" and g.disciplina(1214) == "FECE"
