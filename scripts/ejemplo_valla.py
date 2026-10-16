"""Reproduce la hoja «VALLA MARIANO» (análisis de precio unitario) como ejemplo. No se ejecuta sola.

Uso (desde la raíz del proyecto):  python scripts/ejemplo_valla.py

Crea dos conceptos en la biblioteca (estructura principal y pantalla, con su análisis de precio unitario) y una
cotización que los usa, con los coeficientes e indirectos de la hoja. Resultado esperado: subtotal B/. 65,159.30,
ITBMS 7 % B/. 4,561.15, total B/. 69,720.45. No modifica nada existente: si el proyecto ya existe, no hace nada.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import calculo, db
from app.calculo import Apu, Concepto, ConfigApu, Indirecto, Insumo, Linea

PROYECTO = "Fabricación valla Mariano Rivera"
CLIENTE = "Mariano Rivera"


def _mano_obra(dias):
    return [Insumo("mano_obra", "Calificado", "día", dias, 5, 89.87),
            Insumo("mano_obra", "Ayudante", "día", dias, 5, 62.95),
            Insumo("mano_obra", "Capataz", "día", dias, 1, round(89.97 * 1.2, 3))]


def _auxiliares(soldadura, oxigeno, acetileno):
    return [Insumo("auxiliar", "Soldadura", "kg", soldadura, 1, 6.5),
            Insumo("auxiliar", "Oxígeno", "uni", oxigeno, 1, 70),
            Insumo("auxiliar", "Acetileno", "uni", acetileno, 1, 250),
            Insumo("auxiliar", "Otros (10 % de la mano de obra)", "%", 1, 0.1, 0, ref_categoria="mano_obra"),
            Insumo("auxiliar", "Contenedor", "mes", 1, 1, 250),
            Insumo("auxiliar", "Baños", "mes", 1, 1, 300)]


CONCEPTOS = [
    Concepto(None, "Fabricación e instalación de estructura principal (columnas, vigas y crucetas apernadas, "
                   "prefabricada)", "uni", calculo.OBRA, 0.0, "Estructura metálica", Apu(1.0, (
        _mano_obra(26) + _auxiliares(200, 25, 10) + [
            Insumo("subcontrato", "Corte de platos", "kg", 300, 1, 8),
            Insumo("subcontrato", "Limpieza final", "uni", 3, 1, 100),
            Insumo("subcontrato", "Estudio de ultrasonido", "uni", 2, 1, 1500)]))),
    Concepto(None, "Fabricación e instalación de pantalla", "uni", calculo.OBRA, 0.0, "Estructura metálica", Apu(1.0, (
        _mano_obra(10) + _auxiliares(80, 5, 3) + [Insumo("subcontrato", "Corte de platos", "uni", 100, 1, 8)]))),
]
INDIRECTOS = [Indirecto("Alquiler de patio", 1, 1, 500), Indirecto("Luz de patio", 1, 1, 200),
              Indirecto("Hora de grúa", 2, 8, 60), Indirecto("Transporte", 3, 1, 400),
              Indirecto("Salario administración: José", 1, 2, 800), Indirecto("Salario administración: Adriel", 1, 2, 1000),
              Indirecto("Salario administración: Leitza", 1, 2, 1000)]
NOTAS = ("• Tiempo estimado de entrega: 45 días laborables.\n• No incluye compra ni logística de materiales.\n"
         "• No incluye costos de grúa.\n• La construcción de fundaciones y sus derivados no está dentro del alcance.")


def crear_ejemplo(conn):
    """Devuelve el número de la cotización creada, o None si ya existía el proyecto."""
    if conn.execute("SELECT 1 FROM cotizaciones WHERE proyecto = ?", (PROYECTO,)).fetchone():
        return None
    for c in CONCEPTOS:
        if db.buscar_concepto(c.descripcion, c.unidad, conn) is None:
            db.guardar_concepto(Concepto(None, c.descripcion, c.unidad, c.modalidad, c.precio, c.categoria,
                                         c.apu.copia()), conn)
    cliente = conn.execute("SELECT id FROM clientes WHERE nombre = ?", (CLIENTE,)).fetchone()
    cliente_id = cliente["id"] if cliente else conn.execute(
        "INSERT INTO clientes (nombre) VALUES (?)", (CLIENTE,)).lastrowid
    cot_id, numero = db.crear_cotizacion(cliente_id, conn)
    lineas = [db.linea_desde_concepto(c, 1.0) for c in CONCEPTOS]
    cfg = ConfigApu(0.15, 0.15, 0.15, 0.15, [Indirecto(i.concepto, i.cantidad, i.periodo, i.costo) for i in INDIRECTOS])
    db.guardar_cotizacion(cot_id, lineas, [], conn, cfg=cfg)
    db.guardar_proyecto(cot_id, PROYECTO, conn)
    db.guardar_notas(cot_id, NOTAS, conn)
    return numero


def main():
    db.init_db()
    conn = db.get_connection()
    numero = crear_ejemplo(conn)
    conn.close()
    print(f"Cotización {numero} creada." if numero else f"Ya existe una cotización de «{PROYECTO}»; no se hizo nada.")


if __name__ == "__main__":
    main()
