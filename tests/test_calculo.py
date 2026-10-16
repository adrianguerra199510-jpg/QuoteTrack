import pytest

from app import calculo
from app.calculo import Cargo, Linea


@pytest.fixture
def obra():
    return [
        Linea("grupo", 0, "Albañilería"),
        Linea("item", 1, "Muro de bloque de 6", 10, 20.0),          # 200
        Linea("item", 1, "Muro de bloque de 4", 5, 10.0, False),    # 50, exento
        Linea("grupo", 0, "Pintura"),
        Linea("item", 1, "Pintura interior", 1, 100.0),             # 100
        Linea("item", 0, "Limpieza final", 1, 100.0),               # 100, independiente
    ]


def test_codigos_jerarquicos(obra):
    assert calculo.codigos(obra) == ["01", "01.1", "01.2", "02", "02.1", "03"]


def test_importe_de_grupo_es_la_suma_de_sus_subitems(obra):
    assert calculo.importes(obra) == [250.0, 200.0, 50.0, 100.0, 100.0, 100.0]


def test_subtotal_no_cuenta_dos_veces_los_grupos(obra):
    assert calculo.calcular(obra).subtotal == 450.0


def test_itbms_solo_sobre_lineas_marcadas(obra):
    t = calculo.calcular(obra, tasa=0.07)
    assert t.base_itbms == 400.0           # 450 menos el muro exento de 50
    assert t.itbms == 28.0
    assert t.total == 478.0


def test_itbms_individual_vs_todos(obra):
    for l in obra:
        l.aplica_itbms = True
    assert calculo.calcular(obra, tasa=0.07).itbms == 31.5
    for l in obra:
        l.aplica_itbms = False
    assert calculo.calcular(obra, tasa=0.07).itbms == 0


def test_costos_adicionales_porcentaje_y_monto(obra):
    cargos = [Cargo("Administración", "porcentaje", 10), Cargo("Imprevistos", "monto", 25.0, False)]
    t = calculo.calcular(obra, cargos, 0.07)
    assert [m for _c, m in t.cargos] == [45.0, 25.0]
    assert t.cargos_total == 70.0
    assert t.base_itbms == 445.0           # 400 de ítems gravados + 45 de administración
    assert t.itbms == 31.15
    assert t.total == round(450 + 70 + 31.15, 2)


def test_sin_tasa_no_hay_itbms(obra):
    t = calculo.calcular(obra, [Cargo("Utilidad", "porcentaje", 5)], 0)
    assert t.itbms == 0 and t.total == 450 + 22.5


def test_desde_tuplas_compatibilidad():
    t = calculo.calcular(calculo.desde_tuplas([("a", 2, 50.0), ("b", 1, 25.5)]), tasa=0.07)
    assert (t.subtotal, t.itbms, t.total) == (125.5, 8.79, 134.29)
