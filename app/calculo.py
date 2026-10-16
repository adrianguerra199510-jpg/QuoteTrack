"""Modelo y cálculo de cotizaciones: grupos, sub-ítems, ITBMS por línea y costos adicionales.

Estructura de las líneas (lista plana, en orden):
  - Línea de nivel 0 y tipo 'grupo': encabezado (p. ej. «Albañilería»); su importe es la suma de sus sub-ítems.
  - Línea de nivel 1: sub-ítem del grupo que la precede.
  - Línea de nivel 0 y tipo 'item': ítem independiente (sin grupo).
Los códigos se generan solos: 01, 01.1, 01.2, 02 …
"""
from dataclasses import dataclass, field

TIPOS_CARGO = ("porcentaje", "monto")


@dataclass
class Linea:
    tipo: str = "item"            # 'grupo' | 'item'
    nivel: int = 0                # 0 = principal, 1 = sub-ítem
    descripcion: str = ""
    cantidad: float = 1.0
    precio: float = 0.0
    aplica_itbms: bool = True

    @property
    def es_grupo(self) -> bool:
        return self.tipo == "grupo"

    @property
    def importe_propio(self) -> float:
        return 0.0 if self.es_grupo else round(self.cantidad * self.precio, 2)


@dataclass
class Cargo:
    """Costo adicional: administración, utilidad, imprevistos…"""
    concepto: str = ""
    tipo: str = "porcentaje"      # 'porcentaje' (sobre el subtotal de ítems) | 'monto' (fijo)
    valor: float = 0.0
    aplica_itbms: bool = True

    def monto(self, subtotal: float) -> float:
        base = subtotal * self.valor / 100 if self.tipo == "porcentaje" else self.valor
        return round(base, 2)


@dataclass
class Totales:
    subtotal: float = 0.0
    cargos: list = field(default_factory=list)   # [(Cargo, monto)]
    cargos_total: float = 0.0
    base_itbms: float = 0.0
    tasa: float = 0.0
    itbms: float = 0.0
    total: float = 0.0


def codigos(lineas) -> list[str]:
    """Código jerárquico de cada línea: '01' para principales, '01.1' para sub-ítems."""
    res, principal, sub = [], 0, 0
    for l in lineas:
        if l.nivel == 1 and principal:
            sub += 1
            res.append(f"{principal:02d}.{sub}")
        else:
            principal += 1
            sub = 0
            res.append(f"{principal:02d}")
    return res


def importes(lineas) -> list[float]:
    """Importe de cada línea; el de un grupo es la suma de sus sub-ítems."""
    res = [l.importe_propio for l in lineas]
    for i, l in enumerate(lineas):
        if l.es_grupo and l.nivel == 0:
            j, total = i + 1, 0.0
            while j < len(lineas) and lineas[j].nivel == 1:
                total += lineas[j].importe_propio
                j += 1
            res[i] = round(total, 2)
    return res


def calcular(lineas, cargos=(), tasa: float = 0.0) -> Totales:
    """Subtotal de ítems + costos adicionales + ITBMS (solo sobre lo marcado) = total.

    `tasa` es una fracción (0.07). Los grupos no suman por sí mismos (ya cuentan sus sub-ítems)."""
    subtotal = round(sum(l.importe_propio for l in lineas), 2)
    base = sum(l.importe_propio for l in lineas if l.aplica_itbms)
    montos = []
    for c in cargos:
        m = c.monto(subtotal)
        montos.append((c, m))
        if c.aplica_itbms:
            base += m
    cargos_total = round(sum(m for _c, m in montos), 2)
    base = round(base, 2)
    itbms = round(base * tasa, 2)
    return Totales(subtotal, montos, cargos_total, base, tasa, itbms,
                   round(subtotal + cargos_total + itbms, 2))


def desde_tuplas(items) -> list[Linea]:
    """Compatibilidad: [(descripcion, cantidad, precio), …] -> líneas independientes."""
    return [Linea("item", 0, d, c, p) for d, c, p in items]
