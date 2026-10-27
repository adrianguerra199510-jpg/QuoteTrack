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


# Bases elegibles para un costo adicional: las categorías del APU más los servicios de precio fijo
CATEGORIAS_BASE = {**CATEGORIAS, "servicio": "Servicios profesionales"}


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
    titulo: str = ""              # título corto del ítem (sale en negrita sobre su descripción)
    ajuste: float = 0.0           # costos adicionales diluidos en este ítem (lo fija `calcular`; no se guarda)

    @property
    def es_grupo(self) -> bool:
        return self.tipo == "grupo"

    @property
    def usa_apu(self) -> bool:
        return not self.es_grupo and self.modalidad == OBRA

    @property
    def importe_base(self) -> float:
        """Cantidad × precio, sin los costos adicionales diluidos."""
        return 0.0 if self.es_grupo else round(self.cantidad * self.precio, 2)

    @property
    def importe_propio(self) -> float:
        """Importe del ítem, incluyendo los costos adicionales que se diluyen en él."""
        return 0.0 if self.es_grupo else round(self.importe_base + self.ajuste, 2)

    @property
    def precio_mostrado(self) -> float:
        """Precio unitario con los costos diluidos incluidos (el que se imprime)."""
        if self.es_grupo or not self.ajuste or not self.cantidad:
            return self.precio
        return round(self.importe_propio / self.cantidad, 2)


@dataclass
class Cargo:
    """Costo adicional: administración, utilidad, imprevistos…"""
    concepto: str = ""
    tipo: str = "porcentaje"      # 'porcentaje' (sobre la base del cargo) | 'monto' (fijo)
    valor: float = 0.0
    aplica_itbms: bool = True
    base: str = ""                # categorías sobre las que actúa, separadas por coma (vacío = todo el subtotal)
    diluir: bool = False          # True: se reparte en el precio de los ítems; False: sale como línea aparte

    @property
    def categorias(self) -> list[str]:
        """Categorías elegidas ('material', 'mano_obra', 'auxiliar', 'subcontrato', 'servicio'); [] = todo."""
        return [x for x in (self.base or "").split(",") if x in CATEGORIAS_BASE]

    def monto(self, base: float) -> float:
        """Monto del cargo: el porcentaje de `base` (el valor sobre el que actúa) o el valor fijo."""
        valor = base * self.valor / 100 if self.tipo == "porcentaje" else self.valor
        return round(valor, 2)


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
    cargos: list = field(default_factory=list)   # [(Cargo, monto)] que salen como línea aparte
    cargos_total: float = 0.0
    diluidos: list = field(default_factory=list)  # [(Cargo, monto)] repartidos en el precio de los ítems
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


def ventas_por_categoria(l: Linea, cfg: ConfigApu, coef_indirectos: float = 0.0) -> dict:
    """Importe (venta) de un ítem repartido por categoría: las del APU (materiales, mano de obra…) o, para un
    servicio de precio fijo, 'servicio'. La suma es el importe base del ítem."""
    if l.es_grupo:
        return {}
    if not l.usa_apu:
        return {"servicio": l.importe_base}
    filas = desglose_apu(l.apu or Apu(), cfg, coef_indirectos)
    crudo = {cat: venta * l.cantidad for cat, _costo, _coef, venta in filas}
    suma = sum(crudo.values())
    factor = l.importe_base / suma if suma else 0.0          # ajusta el redondeo del precio unitario
    return {cat: v * factor for cat, v in crudo.items()}


def _repartir(total: float, pesos: list[float]) -> list[float]:
    """Reparte `total` en proporción a `pesos` con exactitud de centavos (método del mayor resto)."""
    suma = sum(pesos)
    centavos = round(total * 100)
    signo = 1 if centavos >= 0 else -1
    exactos = [abs(centavos) * p / suma for p in pesos]
    base = [int(x) for x in exactos]
    faltan = abs(centavos) - sum(base)
    for i in sorted(range(len(pesos)), key=lambda i: exactos[i] - base[i], reverse=True)[:faltan]:
        base[i] += 1
    return [signo * x / 100 for x in base]


def calcular(lineas, cargos=(), tasa: float = 0.0, cfg: ConfigApu | None = None) -> Totales:
    """Subtotal de ítems + costos adicionales + ITBMS (solo sobre lo marcado) = total.

    `tasa` es una fracción (0.07). Los grupos no suman por sí mismos (ya cuentan sus sub-ítems).
    Los ítems de «mano de obra y material» se valoran antes con su APU y `cfg`.

    Cada costo adicional actúa sobre la base que se elija (todo el subtotal o solo ciertas categorías: materiales,
    mano de obra…). Si está marcado para diluir, su monto se reparte en el importe de los ítems de esa base
    (`Linea.ajuste`) en lugar de salir como línea aparte; entonces el ITBMS lo sigue según cada ítem."""
    cfg = cfg or ConfigApu()
    directo, coef_ind = aplicar_apu(lineas, cfg)
    for l in lineas:
        l.ajuste = 0.0
    ventas = [ventas_por_categoria(l, cfg, coef_ind) for l in lineas]
    base_total = round(sum(l.importe_base for l in lineas), 2)
    montos, diluidos = [], []
    for c in cargos:
        cats = c.categorias
        base = round(sum(sum(v.get(k, 0.0) for k in cats) for v in ventas), 2) if cats else base_total
        m = c.monto(base)
        pesos = [(sum(v.get(k, 0.0) for k in cats) if cats else l.importe_base) if not l.es_grupo else 0.0
                 for l, v in zip(lineas, ventas)]
        if c.diluir and m and sum(pesos) <= 0:
            pesos = [0.0 if l.es_grupo else l.importe_base for l in lineas]       # sin base: se reparte en todos
        if c.diluir and m and sum(pesos) > 0:
            for l, parte in zip(lineas, _repartir(m, pesos)):
                l.ajuste = round(l.ajuste + parte, 2)
            diluidos.append((c, m))
        else:
            montos.append((c, m))
    subtotal = round(sum(l.importe_propio for l in lineas), 2)
    base_itbms = sum(l.importe_propio for l in lineas if l.aplica_itbms)
    for c, m in montos:
        if c.aplica_itbms:
            base_itbms += m
    cargos_total = round(sum(m for _c, m in montos), 2)
    base_itbms = round(base_itbms, 2)
    itbms = round(base_itbms * tasa, 2)
    return Totales(costo_directo=round(directo, 2), coef_indirectos=coef_ind, subtotal=subtotal, cargos=montos,
                   cargos_total=cargos_total, diluidos=diluidos, base_itbms=base_itbms, tasa=tasa, itbms=itbms,
                   total=round(subtotal + cargos_total + itbms, 2))


def nombre_base(cargo: Cargo) -> str:
    """Texto de la base de un costo adicional: «todo el subtotal» o las categorías elegidas."""
    cats = cargo.categorias
    return ", ".join(CATEGORIAS_BASE[k].lower() for k in cats) if cats else "todo el subtotal"


def resumen(lineas, cargos=(), tasa: float = 0.0, cfg: ConfigApu | None = None) -> list[tuple]:
    """Resumen de la cotización para mostrar: [(etiqueta, monto, estilo)] con estilo 'seccion', 'fila', 'subtotal',
    'total' o 'nota'. Separa los costos directos por categoría y los servicios, el margen incluido en los análisis
    (coeficientes de venta e indirectos), cada costo adicional (diluido o no), el ITBMS y el total."""
    cfg = cfg or ConfigApu()
    t = calcular(lineas, cargos, tasa, cfg)
    coef_ind = t.coef_indirectos
    costos = {k: 0.0 for k in CATEGORIAS}
    servicios = margen = indirectos = 0.0
    ventas = []
    for l in lineas:
        v = ventas_por_categoria(l, cfg, coef_ind)
        ventas.append(v)
        if l.es_grupo:
            continue
        if not l.usa_apu:
            servicios += l.importe_base
            continue
        filas = desglose_apu(l.apu or Apu(), cfg, coef_ind)
        crudo_venta = sum(venta for *_x, venta in filas) * l.cantidad
        factor = l.importe_base / crudo_venta if crudo_venta else 0.0
        for cat, costo, _coef, _venta in filas:
            costo_l = costo * l.cantidad * factor
            costos[cat] += costo_l
            ind = costo_l * (0.0 if cat == "material" else coef_ind)
            indirectos += ind
            margen += costo_l * cfg.coef(cat)
    base_total = round(sum(l.importe_base for l in lineas), 2)
    filas = [("Costos directos", None, "seccion")]
    for cat, nombre in CATEGORIAS.items():
        if costos[cat]:
            filas.append((nombre, round(costos[cat], 2), "fila"))
    if servicios:
        filas.append(("Servicios profesionales (precio fijo)", round(servicios, 2), "fila"))
    filas.append(("Costo directo total", round(sum(costos.values()) + servicios, 2), "subtotal"))
    if margen or indirectos:
        filas.append(("Margen incluido en los análisis de precio", None, "seccion"))
        if margen:
            filas.append(("Coeficientes de venta (utilidad y gastos del análisis)", round(margen, 2), "fila"))
        if indirectos:
            filas.append(("Costos indirectos de obra", round(indirectos, 2), "fila"))
    filas.append(("Subtotal de ítems (sin costos adicionales)", base_total, "subtotal"))
    if cargos:
        filas.append(("Costos adicionales", None, "seccion"))
        for c in cargos:
            cats = c.categorias
            base = round(sum(sum(v.get(k, 0.0) for k in cats) for v in ventas), 2) if cats else base_total
            monto = c.monto(base)
            etiqueta = (f"{c.concepto or 'Costo adicional'} ({c.valor:g}% sobre {nombre_base(c)}: B/. {base:,.2f})"
                        if c.tipo == "porcentaje" else f"{c.concepto or 'Costo adicional'} (monto fijo, base: {nombre_base(c)})")
            if any(c is d for d, _m in t.diluidos):
                etiqueta += " — diluido en los ítems"
            filas.append((etiqueta, monto, "fila"))
        filas.append(("Total costos adicionales", round(sum(m for _c, m in t.cargos) + sum(m for _c, m in t.diluidos), 2),
                      "subtotal"))
    filas.append(("Subtotal con costos adicionales", round(t.subtotal + t.cargos_total, 2), "subtotal"))
    filas.append((f"ITBMS ({tasa:.0%})" if tasa else "ITBMS", t.itbms, "fila"))
    filas.append(("TOTAL", t.total, "total"))
    return filas


def desde_tuplas(items) -> list[Linea]:
    """Compatibilidad: [(descripcion, cantidad, precio), …] -> líneas independientes."""
    return [Linea("item", 0, d, c, p) for d, c, p in items]
