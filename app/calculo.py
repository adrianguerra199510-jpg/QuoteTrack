"""Modelo y cálculo de cotizaciones: grupos, sub-ítems, ITBMS por línea y costos adicionales.

Estructura de las líneas (lista plana, en orden):
  - Línea de nivel 0 y tipo 'grupo': encabezado (p. ej. «Albañilería»); su importe es la suma de sus sub-ítems.
  - Línea de nivel 1: sub-ítem del grupo que la precede.
  - Línea de nivel 0 y tipo 'item': ítem independiente (sin grupo).
Los códigos se generan solos: 01, 01.1, 01.2, 02 …
"""
from dataclasses import dataclass, field, replace

TIPOS_CARGO = ("porcentaje", "monto")

# Modalidad de un ítem: precio fijo (servicio profesional) o análisis de precio unitario (APU)
SERVICIO, OBRA = "servicio", "obra"
MODALIDADES = {SERVICIO: "Servicio profesional", OBRA: "Mano de obra y material"}
# Categorías de insumos de un APU, en el orden en que se presentan
CATEGORIAS = {
    "material": "Materiales",
    "mano_obra": "Mano de obra",
    "auxiliar": "Medios auxiliares",
    "subcontrato": "Subcontratos",
}


@dataclass
class Insumo:
    """Una fila de un análisis de precio unitario. Coste = rendimiento × coeficiente × precio.

    Si `ref_categoria` está indicada, el precio es el coste de esa categoría (p. ej. «herramienta menor»
    = 5 % del coste de la mano de obra: rendimiento 1, coeficiente 0.05, ref_categoria 'mano_obra')."""
    categoria: str = "material"
    descripcion: str = ""
    unidad: str = ""
    rendimiento: float = 1.0
    coeficiente: float = 1.0
    precio: float = 0.0
    ref_categoria: str = ""


@dataclass
class Apu:
    """Análisis de precio unitario: insumos necesarios para producir `base` unidades del ítem."""
    base: float = 1.0
    insumos: list = field(default_factory=list)

    def copia(self) -> "Apu":
        return Apu(self.base, [replace(i) for i in self.insumos])


@dataclass
class Indirecto:
    """Costo indirecto de obra (alquiler de patio, grúa, salarios de administración…)."""
    concepto: str = ""
    cantidad: float = 1.0
    periodo: float = 1.0      # meses u horas
    costo: float = 0.0

    @property
    def subtotal(self) -> float:
        return round(self.cantidad * self.periodo * self.costo, 2)


@dataclass
class ConfigApu:
    """Coeficientes de venta (fracciones: 0.15 = 15 %) por categoría e indirectos de la cotización.

    El coeficiente de indirectos (total de indirectos / costo directo) se suma a mano de obra,
    medios auxiliares y subcontratos, no a materiales (como en la hoja de cálculo original)."""
    coef_material: float = 0.15
    coef_mano_obra: float = 0.15
    coef_auxiliar: float = 0.15
    coef_subcontrato: float = 0.15
    indirectos: list = field(default_factory=list)

    def coef(self, categoria: str) -> float:
        return getattr(self, f"coef_{categoria}")

    @property
    def total_indirectos(self) -> float:
        return round(sum(i.subtotal for i in self.indirectos), 2)


@dataclass
class Linea:
    tipo: str = "item"            # 'grupo' | 'item'
    nivel: int = 0                # 0 = principal, 1 = sub-ítem
    descripcion: str = ""
    cantidad: float = 1.0
    precio: float = 0.0
    aplica_itbms: bool = True
    unidad: str = ""
    modalidad: str = SERVICIO     # SERVICIO: precio manual · OBRA: precio calculado por el APU
    apu: Apu | None = None

    @property
    def es_grupo(self) -> bool:
        return self.tipo == "grupo"

    @property
    def usa_apu(self) -> bool:
        return not self.es_grupo and self.modalidad == OBRA

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
class Concepto:
    """Concepto reutilizable de la biblioteca (un servicio con precio fijo o un ítem con APU)."""
    id: int | None = None
    descripcion: str = ""
    unidad: str = ""
    modalidad: str = SERVICIO
    precio: float = 0.0
    categoria: str = ""
    apu: Apu | None = None
    codigo: str = ""       # identificador dentro de su fuente (p. ej. la página de la base de la Contraloría)
    fuente: str = ""       # vacío = creado por el usuario
    biblioteca_id: int | None = None    # biblioteca a la que pertenece (None = la predeterminada al guardar)
    orden: int = 0         # posición dentro de su biblioteca (0 = por categoría y descripción)


@dataclass
class Totales:
    costo_directo: float = 0.0      # costo (sin coeficientes) de los ítems con APU
    coef_indirectos: float = 0.0
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


def costos_apu(apu: Apu) -> dict:
    """Coste de cada categoría del APU (suma de rendimiento × coeficiente × precio de sus insumos)."""
    base = {c: 0.0 for c in CATEGORIAS}
    for i in apu.insumos:
        if not i.ref_categoria:
            base[i.categoria] = base.get(i.categoria, 0.0) + i.rendimiento * i.coeficiente * i.precio
    costos = dict(base)
    for i in apu.insumos:
        if i.ref_categoria:
            costos[i.categoria] = costos.get(i.categoria, 0.0) + i.rendimiento * i.coeficiente * base.get(i.ref_categoria, 0.0)
    return costos


def costo_insumo(apu: Apu, insumo: Insumo) -> float:
    """Coste de una fila (resuelve la referencia a otra categoría, si la tiene)."""
    if insumo.ref_categoria:
        precio = sum(i.rendimiento * i.coeficiente * i.precio for i in apu.insumos
                     if i.categoria == insumo.ref_categoria and not i.ref_categoria)
    else:
        precio = insumo.precio
    return insumo.rendimiento * insumo.coeficiente * precio


def costo_unitario(apu: Apu) -> float:
    return sum(costos_apu(apu).values()) / (apu.base or 1.0)


def precio_unitario(apu: Apu, cfg: ConfigApu, coef_indirectos: float = 0.0) -> float:
    """Precio de venta unitario: coste de cada categoría × (1 + su coeficiente) / cantidad base."""
    total = 0.0
    for cat, coste in costos_apu(apu).items():
        total += coste * (1 + cfg.coef(cat) + (0.0 if cat == "material" else coef_indirectos))
    return round(total / (apu.base or 1.0), 2)


def desglose_apu(apu: Apu, cfg: ConfigApu, coef_indirectos: float = 0.0) -> list[tuple]:
    """Por categoría y por unidad del ítem: (categoría, costo, coeficiente aplicado, venta)."""
    base = apu.base or 1.0
    filas = []
    for cat, coste in costos_apu(apu).items():
        coef = cfg.coef(cat) + (0.0 if cat == "material" else coef_indirectos)
        filas.append((cat, coste / base, coef, coste * (1 + coef) / base))
    return filas


def coeficiente_indirectos(lineas, cfg: ConfigApu) -> tuple[float, float]:
    """(costo directo de los ítems con APU, total de indirectos / costo directo)."""
    directo = sum(l.cantidad * costo_unitario(l.apu or Apu()) for l in lineas if l.usa_apu)
    return directo, (cfg.total_indirectos / directo if directo > 0 else 0.0)


def aplicar_apu(lineas, cfg: ConfigApu) -> tuple[float, float]:
    """Fija el precio de cada ítem con APU a partir de su análisis (modifica las líneas).
    Devuelve (costo directo, coeficiente de indirectos)."""
    directo, coef_ind = coeficiente_indirectos(lineas, cfg)
    for l in lineas:
        if l.usa_apu:
            l.precio = precio_unitario(l.apu or Apu(), cfg, coef_ind)
    return directo, coef_ind


def calcular(lineas, cargos=(), tasa: float = 0.0, cfg: ConfigApu | None = None) -> Totales:
    """Subtotal de ítems + costos adicionales + ITBMS (solo sobre lo marcado) = total.

    `tasa` es una fracción (0.07). Los grupos no suman por sí mismos (ya cuentan sus sub-ítems).
    Los ítems de «mano de obra y material» se valoran antes con su APU y `cfg`."""
    directo, coef_ind = aplicar_apu(lineas, cfg or ConfigApu())
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
    return Totales(costo_directo=round(directo, 2), coef_indirectos=coef_ind, subtotal=subtotal, cargos=montos,
                   cargos_total=cargos_total, base_itbms=base, tasa=tasa, itbms=itbms,
                   total=round(subtotal + cargos_total + itbms, 2))


def desde_tuplas(items) -> list[Linea]:
    """Compatibilidad: [(descripcion, cantidad, precio), …] -> líneas independientes."""
    return [Linea("item", 0, d, c, p) for d, c, p in items]
