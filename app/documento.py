"""Datos de una cotización o factura listos para imprimir; los comparten las exportaciones a PDF y a Word."""
from dataclasses import dataclass, field

from app import calculo, db


@dataclass
class Documento:
    titulo: str                      # «COTIZACIÓN» / «FACTURA»
    numero: str
    fecha: str
    cliente: object                  # fila de clientes
    empresa: object                  # fila de empresas (o None)
    extra: list = field(default_factory=list)      # [(etiqueta, valor)] bajo la fecha
    lineas: list | None = None       # solo cotizaciones (la factura muestra únicamente los totales)
    totales: calculo.Totales = None
    notas: str = ""

    @property
    def nombre_archivo(self) -> str:
        return self.numero


def de_cotizacion(cotizacion_id: int, mostrar_estado: bool | None = None) -> Documento:
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
    extra = []
    if cot["proyecto"]:
        extra.append(("Proyecto", cot["proyecto"]))
    if mostrar_estado:
        extra.append(("Estado", cot["estado"]))
    return Documento("COTIZACIÓN", cot["numero"], cot["fecha"], cliente, empresa, extra, lineas, totales, cot["notas"])


def de_factura(factura_id: int, mostrar_estado: bool | None = None) -> Documento:
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
    return Documento("FACTURA", fac["numero"], fac["fecha"], cliente, empresa, extra, None, totales, fac["notas"])


def etiquetas_totales(t: calculo.Totales) -> list[tuple[str, float, bool]]:
    """Filas de la tabla de totales: (etiqueta, monto, es_total)."""
    filas = [("Subtotal:", t.subtotal, False)]
    for cargo, monto in t.cargos:
        filas.append((f"{cargo.concepto} ({cargo.valor:g}%):" if cargo.tipo == "porcentaje" else f"{cargo.concepto}:",
                      monto, False))
    if t.itbms == 0:
        etiqueta = "ITBMS (exento):"
    else:
        etiqueta = f"ITBMS ({t.tasa:.0%}):" if t.tasa else "ITBMS:"
    filas += [(etiqueta, t.itbms, False), ("Total:", t.total, True)]
    return filas
