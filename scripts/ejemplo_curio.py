"""Crea una cotización de ejemplo (Torres Curio A y B). No se ejecuta automáticamente.

Uso (desde la raíz del proyecto):  python scripts/ejemplo_curio.py

No toca cotizaciones existentes: si ya hay una del proyecto "Torres Curio A y B", no hace nada.
El ejemplo se guarda exento de ITBMS (servicio profesional): total = subtotal.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db

PROYECTO = "Torres Curio A y B"
CLIENTE = "Anel"
ITEMS = [
    ("Torre A: Diseño estructural integral de la torre apartamental (10 niveles, 4,710.32 m² de "
     "construcción), incluyendo sistema de losas, columnas, muros de corte y cimentación, con planos "
     "y memoria de cálculo conforme al REP-2021 y ACI 318-19, garantizando seguridad sísmica, "
     "durabilidad y eficiencia constructiva.", 1, 23551.60),
    ("Torre B: Diseño estructural integral de la torre idéntica a la Torre A (4,710.32 m²), "
     "aprovechando el diseño de la Torre A. Incluye planos y memoria de cálculo conforme al "
     "REP-2021 y ACI 318-19.", 1, 9420.64),
]


def crear_ejemplo(conn):
    """Devuelve el número de la cotización creada, o None si ya existía el proyecto."""
    if conn.execute("SELECT 1 FROM cotizaciones WHERE proyecto = ?", (PROYECTO,)).fetchone():
        return None
    cliente = conn.execute("SELECT id FROM clientes WHERE nombre = ?", (CLIENTE,)).fetchone()
    if cliente:
        cliente_id = cliente["id"]
    else:
        cliente_id = conn.execute("INSERT INTO clientes (nombre) VALUES (?)", (CLIENTE,)).lastrowid
    numero = db.next_numero("COT", "cotizaciones", conn)
    cot_id = conn.execute(
        "INSERT INTO cotizaciones (numero, cliente_id, fecha, proyecto) VALUES (?, ?, ?, ?)",
        (numero, cliente_id, date.today().isoformat(), PROYECTO),
    ).lastrowid
    conn.commit()
    db.guardar_items(cot_id, ITEMS, conn)
    subtotal, _itbms, _total = db.calcular_totales(ITEMS, 0)  # exento de ITBMS
    conn.execute("UPDATE cotizaciones SET subtotal = ?, itbms = 0, total = ? WHERE id = ?",
                 (subtotal, subtotal, cot_id))
    db.guardar_notas(cot_id, db.obtener_plantilla_notas(conn), conn)
    return numero


def main():
    db.init_db()
    conn = db.get_connection()
    numero = crear_ejemplo(conn)
    conn.close()
    print(f"Cotización {numero} creada." if numero else f"Ya existe una cotización de «{PROYECTO}»; no se hizo nada.")


if __name__ == "__main__":
    main()
