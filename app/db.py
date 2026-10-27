"""
Capa de acceso a datos para QuoteTrack.
Usa SQLite (archivo local quotetrack.db) para clientes, cotizaciones y facturas.
"""
import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path
from datetime import date

from app import calculo, texto_rico
from app.calculo import Apu, Cargo, ConfigApu, Concepto, Indirecto, Insumo, Linea

def _ruta_db() -> Path:
    """En desarrollo la base vive junto al código. En el ejecutable se guarda en la carpeta de datos del usuario
    (%APPDATA%\\QuoteTrack), para que no se pierda al descomprimir una versión nueva; si había una base junto
    al ejecutable (versiones anteriores) se copia la primera vez."""
    local = Path(__file__).resolve().parent.parent / "quotetrack.db"
    if not getattr(sys, "frozen", False):
        return local
    base = Path(os.environ.get("APPDATA") or Path.home() / ".local" / "share") / "QuoteTrack"
    destino = base / "quotetrack.db"
    try:
        base.mkdir(parents=True, exist_ok=True)
        junto_al_exe = Path(sys.executable).resolve().parent / "quotetrack.db"
        if not destino.exists() and junto_al_exe.exists():
            shutil.copy2(junto_al_exe, destino)
    except OSError:
        return Path(sys.executable).resolve().parent / "quotetrack.db"
    return destino


DB_PATH = _ruta_db()

SCHEMA = """
CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    identificacion TEXT,
    contacto TEXT
);

CREATE TABLE IF NOT EXISTS cotizaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    fecha TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'borrador',  -- borrador, enviada, aprobada, rechazada
    subtotal REAL NOT NULL DEFAULT 0,
    itbms REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL DEFAULT 0,
    notas TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS cotizacion_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cotizacion_id INTEGER NOT NULL REFERENCES cotizaciones(id) ON DELETE CASCADE,
    descripcion TEXT NOT NULL,
    cantidad REAL NOT NULL DEFAULT 1,
    precio_unitario REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS facturas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    cotizacion_id INTEGER REFERENCES cotizaciones(id),
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    fecha TEXT NOT NULL,
    estado_pago TEXT NOT NULL DEFAULT 'pendiente',  -- pendiente, pagada, vencida
    total REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS configuracion (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS empresas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    subtitulo TEXT NOT NULL DEFAULT '',
    correo TEXT NOT NULL DEFAULT '',
    telefono TEXT NOT NULL DEFAULT '',
    direccion TEXT NOT NULL DEFAULT '',
    ruc TEXT NOT NULL DEFAULT '',
    itbms_tasa REAL NOT NULL DEFAULT 7,      -- en %, 0 = exento
    logo BLOB,
    predeterminada INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cotizacion_cargos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cotizacion_id INTEGER NOT NULL REFERENCES cotizaciones(id) ON DELETE CASCADE,
    concepto TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'porcentaje',  -- porcentaje | monto
    valor REAL NOT NULL DEFAULT 0,
    aplica_itbms INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS apu_insumos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES cotizacion_items(id) ON DELETE CASCADE,
    categoria TEXT NOT NULL,                 -- material | mano_obra | auxiliar | subcontrato
    descripcion TEXT NOT NULL DEFAULT '',
    unidad TEXT NOT NULL DEFAULT '',
    rendimiento REAL NOT NULL DEFAULT 1,
    coeficiente REAL NOT NULL DEFAULT 1,
    precio REAL NOT NULL DEFAULT 0,
    ref_categoria TEXT NOT NULL DEFAULT ''   -- si se indica, el precio es el coste de esa categoría
);

CREATE TABLE IF NOT EXISTS cotizacion_indirectos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cotizacion_id INTEGER NOT NULL REFERENCES cotizaciones(id) ON DELETE CASCADE,
    concepto TEXT NOT NULL DEFAULT '',
    cantidad REAL NOT NULL DEFAULT 1,
    periodo REAL NOT NULL DEFAULT 1,
    costo REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS conceptos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    descripcion TEXT NOT NULL,
    unidad TEXT NOT NULL DEFAULT '',
    modalidad TEXT NOT NULL DEFAULT 'servicio',   -- servicio | obra
    precio REAL NOT NULL DEFAULT 0,               -- precio unitario del servicio profesional
    categoria TEXT NOT NULL DEFAULT '',
    apu_base REAL NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS bibliotecas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE COLLATE NOCASE,
    descripcion TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS concepto_insumos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concepto_id INTEGER NOT NULL REFERENCES conceptos(id) ON DELETE CASCADE,
    categoria TEXT NOT NULL,
    descripcion TEXT NOT NULL DEFAULT '',
    unidad TEXT NOT NULL DEFAULT '',
    rendimiento REAL NOT NULL DEFAULT 1,
    coeficiente REAL NOT NULL DEFAULT 1,
    precio REAL NOT NULL DEFAULT 0,
    ref_categoria TEXT NOT NULL DEFAULT ''
);

"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def _agregar_columna(conn: sqlite3.Connection, tabla: str, columna: str, definicion: str) -> None:
    if columna not in [c["name"] for c in conn.execute(f"PRAGMA table_info({tabla})")]:
        conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {definicion}")


def _migrar_empresa_inicial(conn: sqlite3.Connection) -> None:
    """Si no hay empresas, crea la predeterminada con los datos de la configuración anterior
    (nombre/subtítulo/correo/tasa de ITBMS) y se la asigna a lo que ya existía."""
    if conn.execute("SELECT 1 FROM empresas LIMIT 1").fetchone() is None:
        def cfg(clave, defecto):
            fila = conn.execute("SELECT valor FROM configuracion WHERE clave = ?", (clave,)).fetchone()
            return fila["valor"] if fila else defecto
        try:
            tasa = max(0.0, float(cfg("itbms_tasa", "7").replace(",", ".")))
        except ValueError:
            tasa = 7.0
        conn.execute(
            "INSERT INTO empresas (nombre, subtitulo, correo, itbms_tasa, predeterminada) VALUES (?, ?, ?, ?, 1)",
            (cfg("empresa_nombre", "INTEGRO SA"), cfg("empresa_subtitulo", "INGENIERIA ESTRUCTURAL"),
             cfg("empresa_correo", ""), tasa),
        )
    predeterminada = conn.execute(
        "SELECT id FROM empresas ORDER BY predeterminada DESC, id LIMIT 1").fetchone()["id"]
    conn.execute("UPDATE cotizaciones SET empresa_id = ? WHERE empresa_id IS NULL", (predeterminada,))
    conn.execute("UPDATE facturas SET empresa_id = ? WHERE empresa_id IS NULL", (predeterminada,))


BIBLIOTECA_INICIAL = "Mi biblioteca"


def _migrar_bibliotecas(conn: sqlite3.Connection) -> None:
    """Garantiza una biblioteca propia y reparte los conceptos existentes: los creados por el usuario van a «Mi
    biblioteca» y los importados de una fuente a una biblioteca con el nombre de esa fuente."""
    if conn.execute("SELECT 1 FROM bibliotecas LIMIT 1").fetchone() is None:
        conn.execute("INSERT INTO bibliotecas (nombre) VALUES (?)", (BIBLIOTECA_INICIAL,))
    propia = conn.execute("SELECT MIN(id) AS id FROM bibliotecas").fetchone()["id"]
    for f in conn.execute("SELECT DISTINCT fuente FROM conceptos WHERE biblioteca_id IS NULL AND fuente <> ''").fetchall():
        fila = conn.execute("SELECT id FROM bibliotecas WHERE nombre = ?", (f["fuente"],)).fetchone()
        bid = fila["id"] if fila else conn.execute("INSERT INTO bibliotecas (nombre) VALUES (?)", (f["fuente"],)).lastrowid
        conn.execute("UPDATE conceptos SET biblioteca_id = ? WHERE biblioteca_id IS NULL AND fuente = ?", (bid, f["fuente"]))
    conn.execute("UPDATE conceptos SET biblioteca_id = ? WHERE biblioteca_id IS NULL", (propia,))
    conn.execute("UPDATE conceptos SET orden = CAST(codigo AS INTEGER) WHERE orden = 0 AND codigo <> ''")


def init_db() -> None:
    conn = get_connection()
    conn.executescript(SCHEMA)
    # Migración: bases creadas antes de existir la fecha de pago
    columnas = [c["name"] for c in conn.execute("PRAGMA table_info(facturas)")]
    if "fecha_pago" not in columnas:
        conn.execute("ALTER TABLE facturas ADD COLUMN fecha_pago TEXT")
    # Migración: notas / términos y condiciones (vacío por defecto en registros existentes)
    if "notas" not in columnas:
        conn.execute("ALTER TABLE facturas ADD COLUMN notas TEXT NOT NULL DEFAULT ''")
    conn.execute("UPDATE cotizaciones SET notas = '' WHERE notas IS NULL")
    _agregar_columna(conn, "cotizaciones", "titulo_notas", "TEXT NOT NULL DEFAULT ''")
    _agregar_columna(conn, "facturas", "titulo_notas", "TEXT NOT NULL DEFAULT ''")
    _agregar_columna(conn, "cotizaciones", "proyecto", "TEXT NOT NULL DEFAULT ''")
    # Migración: empresas, costos adicionales, grupos/sub-ítems e ITBMS por línea
    _agregar_columna(conn, "cotizaciones", "empresa_id", "INTEGER REFERENCES empresas(id)")
    _agregar_columna(conn, "cotizaciones", "cargos", "REAL NOT NULL DEFAULT 0")
    _agregar_columna(conn, "cotizaciones", "itbms_tasa", "REAL")  # NULL = cotización anterior a este campo
    _agregar_columna(conn, "facturas", "empresa_id", "INTEGER REFERENCES empresas(id)")
    _agregar_columna(conn, "cotizacion_items", "tipo", "TEXT NOT NULL DEFAULT 'item'")
    _agregar_columna(conn, "cotizacion_items", "nivel", "INTEGER NOT NULL DEFAULT 0")
    _agregar_columna(conn, "cotizacion_items", "aplica_itbms", "INTEGER NOT NULL DEFAULT 1")
    # Migración: unidad, modalidad (servicio / mano de obra y material) y análisis de precio unitario
    _agregar_columna(conn, "cotizacion_items", "unidad", "TEXT NOT NULL DEFAULT ''")
    _agregar_columna(conn, "cotizacion_items", "modalidad", "TEXT NOT NULL DEFAULT 'servicio'")
    _agregar_columna(conn, "cotizacion_items", "apu_base", "REAL NOT NULL DEFAULT 1")
    _agregar_columna(conn, "cotizacion_items", "titulo", "TEXT NOT NULL DEFAULT ''")
    # Facturas por etapas: una cotización puede tener varias facturas (abonos), cada una con su concepto y porcentaje
    conn.execute("DROP INDEX IF EXISTS idx_facturas_cotizacion")
    _agregar_columna(conn, "facturas", "concepto", "TEXT NOT NULL DEFAULT ''")
    _agregar_columna(conn, "facturas", "porcentaje", "REAL")       # % del total de la cotización (NULL = factura anterior)
    for cat in calculo.CATEGORIAS:
        _agregar_columna(conn, "cotizaciones", f"apu_coef_{cat}", "REAL")   # en %, NULL = valor por defecto
    # Migración: origen de los conceptos de la biblioteca (bases de datos de costos importadas)
    _agregar_columna(conn, "conceptos", "codigo", "TEXT NOT NULL DEFAULT ''")
    _agregar_columna(conn, "conceptos", "fuente", "TEXT NOT NULL DEFAULT ''")
    # Migración: varias bibliotecas de conceptos
    _agregar_columna(conn, "conceptos", "biblioteca_id", "INTEGER REFERENCES bibliotecas(id)")
    _agregar_columna(conn, "conceptos", "orden", "INTEGER NOT NULL DEFAULT 0")
    _migrar_bibliotecas(conn)
    _migrar_empresa_inicial(conn)
    conn.commit()
    conn.close()


def next_numero(prefijo: str, tabla: str, conn: sqlite3.Connection) -> str:
    """Genera un número consecutivo tipo COT-2026-0001 / FAC-2026-0001 (sigue al mayor existente, aunque
    haya números con sufijo como COT-2026-0003-B)."""
    anio = date.today().year
    cabecera = f"{prefijo}-{anio}-"
    mayor = 0
    for fila in conn.execute(f"SELECT numero FROM {tabla} WHERE numero LIKE ?", (cabecera + "%",)):
        m = re.match(r"(\d+)", fila["numero"][len(cabecera):])
        if m:
            mayor = max(mayor, int(m.group(1)))
    return f"{cabecera}{mayor + 1:04d}"


ITBMS_RATE = 0.07  # ITBMS Panamá 7% (tasa por defecto de una empresa nueva)


def _insumos_de(filas) -> list[Insumo]:
    return [Insumo(f["categoria"], f["descripcion"], f["unidad"], f["rendimiento"], f["coeficiente"],
                   f["precio"], f["ref_categoria"]) for f in filas]


def obtener_lineas(cotizacion_id: int, conn: sqlite3.Connection) -> list[Linea]:
    filas = conn.execute(
        "SELECT id, tipo, nivel, descripcion, cantidad, precio_unitario, aplica_itbms, unidad, modalidad, apu_base, titulo "
        "FROM cotizacion_items WHERE cotizacion_id = ? ORDER BY id",
        (cotizacion_id,),
    ).fetchall()
    lineas = []
    for f in filas:
        apu = None
        if f["modalidad"] == calculo.OBRA:
            apu = Apu(f["apu_base"], _insumos_de(conn.execute(
                "SELECT * FROM apu_insumos WHERE item_id = ? ORDER BY id", (f["id"],)).fetchall()))
        lineas.append(Linea(f["tipo"], f["nivel"], f["descripcion"], f["cantidad"], f["precio_unitario"],
                            bool(f["aplica_itbms"]), f["unidad"], f["modalidad"], apu, f["titulo"] or ""))
    return lineas


def obtener_cargos(cotizacion_id: int, conn: sqlite3.Connection) -> list[Cargo]:
    filas = conn.execute(
        "SELECT concepto, tipo, valor, aplica_itbms FROM cotizacion_cargos WHERE cotizacion_id = ? ORDER BY id",
        (cotizacion_id,),
    ).fetchall()
    return [Cargo(f["concepto"], f["tipo"], f["valor"], bool(f["aplica_itbms"])) for f in filas]


def obtener_items(cotizacion_id: int, conn: sqlite3.Connection) -> list[tuple[str, float, float]]:
    """Solo los ítems (sin encabezados de grupo) como (descripción, cantidad, precio)."""
    return [(texto_rico.a_texto_plano(texto_rico.con_titulo(l.titulo, l.descripcion)), l.cantidad, l.precio) for l in obtener_lineas(cotizacion_id, conn) if not l.es_grupo]


def tasa_de_cotizacion(cotizacion_id: int, conn: sqlite3.Connection) -> float:
    """Tasa de ITBMS (fracción) vigente al guardar la cotización; para cotizaciones antiguas se deduce."""
    fila = conn.execute(
        "SELECT itbms_tasa, itbms, subtotal, cargos FROM cotizaciones WHERE id = ?", (cotizacion_id,),
    ).fetchone()
    if fila is None:
        return 0.0
    if fila["itbms_tasa"] is not None:
        return fila["itbms_tasa"]
    if fila["itbms"] == 0:
        return 0.0
    base = fila["subtotal"] + fila["cargos"]
    return round(fila["itbms"] / base, 4) if base else ITBMS_RATE


def totales_cotizacion(cotizacion_id: int, conn: sqlite3.Connection) -> calculo.Totales:
    return calculo.calcular(obtener_lineas(cotizacion_id, conn), obtener_cargos(cotizacion_id, conn),
                            tasa_de_cotizacion(cotizacion_id, conn), obtener_config_apu(cotizacion_id, conn))


def coef_apu_defecto(conn: sqlite3.Connection) -> ConfigApu:
    """Coeficientes de venta por defecto (Configuración); sin indirectos."""
    valores = {}
    for cat in calculo.CATEGORIAS:
        try:
            valores[f"coef_{cat}"] = float(obtener_config(f"apu_coef_{cat}", conn, "15").replace(",", ".")) / 100
        except ValueError:
            valores[f"coef_{cat}"] = 0.15
    return ConfigApu(**valores)


def guardar_coef_apu_defecto(porcentajes: dict, conn: sqlite3.Connection) -> None:
    """`porcentajes`: {'material': 15, 'mano_obra': 15, …} (en %)."""
    for cat in calculo.CATEGORIAS:
        if cat in porcentajes:
            guardar_config(f"apu_coef_{cat}", str(float(porcentajes[cat])), conn)


def obtener_config_apu(cotizacion_id: int, conn: sqlite3.Connection) -> ConfigApu:
    """Coeficientes e indirectos de la cotización (los que no tenga fijados toman el valor por defecto)."""
    cfg = coef_apu_defecto(conn)
    fila = conn.execute("SELECT * FROM cotizaciones WHERE id = ?", (cotizacion_id,)).fetchone()
    if fila is not None:
        for cat in calculo.CATEGORIAS:
            if fila[f"apu_coef_{cat}"] is not None:
                setattr(cfg, f"coef_{cat}", fila[f"apu_coef_{cat}"] / 100)
    cfg.indirectos = [Indirecto(f["concepto"], f["cantidad"], f["periodo"], f["costo"]) for f in conn.execute(
        "SELECT * FROM cotizacion_indirectos WHERE cotizacion_id = ? ORDER BY id", (cotizacion_id,))]
    return cfg


def guardar_cotizacion(cotizacion_id: int, lineas, cargos, conn: sqlite3.Connection,
                       tasa: float | None = None, cfg: ConfigApu | None = None) -> calculo.Totales:
    """Reemplaza líneas (con sus análisis de precio), costos adicionales y, si se indica, los coeficientes
    e indirectos del APU; actualiza los totales. `tasa` (fracción) por defecto es la de la empresa."""
    lineas, cargos = list(lineas), list(cargos)
    if tasa is None:
        empresa = empresa_de_cotizacion(cotizacion_id, conn)
        tasa = empresa["itbms_tasa"] / 100 if empresa else 0.0
    if cfg is None:
        cfg = obtener_config_apu(cotizacion_id, conn)
    else:
        conn.execute(
            "UPDATE cotizaciones SET " + ", ".join(f"apu_coef_{c} = ?" for c in calculo.CATEGORIAS) + " WHERE id = ?",
            (*[cfg.coef(c) * 100 for c in calculo.CATEGORIAS], cotizacion_id))
        conn.execute("DELETE FROM cotizacion_indirectos WHERE cotizacion_id = ?", (cotizacion_id,))
        conn.executemany(
            "INSERT INTO cotizacion_indirectos (cotizacion_id, concepto, cantidad, periodo, costo) VALUES (?, ?, ?, ?, ?)",
            [(cotizacion_id, i.concepto, i.cantidad, i.periodo, i.costo) for i in cfg.indirectos])
    t = calculo.calcular(lineas, cargos, tasa, cfg)        # fija el precio de los ítems con APU
    conn.execute("DELETE FROM cotizacion_items WHERE cotizacion_id = ?", (cotizacion_id,))
    for l in lineas:
        cur = conn.execute(
            "INSERT INTO cotizacion_items (cotizacion_id, descripcion, cantidad, precio_unitario, tipo, nivel, "
            "aplica_itbms, unidad, modalidad, apu_base, titulo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cotizacion_id, l.descripcion, l.cantidad, l.precio, l.tipo, l.nivel, int(l.aplica_itbms),
             l.unidad, l.modalidad, l.apu.base if l.apu else 1.0, l.titulo or ""))
        if l.usa_apu and l.apu:
            conn.executemany(
                "INSERT INTO apu_insumos (item_id, categoria, descripcion, unidad, rendimiento, coeficiente, precio, "
                "ref_categoria) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(cur.lastrowid, i.categoria, i.descripcion, i.unidad, i.rendimiento, i.coeficiente, i.precio,
                  i.ref_categoria) for i in l.apu.insumos])
    conn.execute("DELETE FROM cotizacion_cargos WHERE cotizacion_id = ?", (cotizacion_id,))
    conn.executemany(
        "INSERT INTO cotizacion_cargos (cotizacion_id, concepto, tipo, valor, aplica_itbms) VALUES (?, ?, ?, ?, ?)",
        [(cotizacion_id, c.concepto, c.tipo, c.valor, int(c.aplica_itbms)) for c in cargos],
    )
    conn.execute(
        "UPDATE cotizaciones SET subtotal = ?, cargos = ?, itbms = ?, total = ?, itbms_tasa = ? WHERE id = ?",
        (t.subtotal, t.cargos_total, t.itbms, t.total, tasa, cotizacion_id),
    )
    conn.commit()
    return t


def guardar_items(cotizacion_id: int, items, conn: sqlite3.Connection) -> tuple[float, float, float]:
    """Compatibilidad: guarda [(descripción, cantidad, precio), …] como ítems independientes
    (conserva los costos adicionales existentes) y devuelve (subtotal, itbms, total)."""
    t = guardar_cotizacion(cotizacion_id, calculo.desde_tuplas(items), obtener_cargos(cotizacion_id, conn), conn)
    return t.subtotal, t.itbms, t.total


def crear_cotizacion(cliente_id: int, conn: sqlite3.Connection, empresa_id: int | None = None) -> tuple[int, str]:
    """Crea una cotización en borrador y devuelve (id, número)."""
    if empresa_id is None:
        empresa_id = empresa_predeterminada_id(conn)
    numero = next_numero("COT", "cotizaciones", conn)
    cur = conn.execute(
        "INSERT INTO cotizaciones (numero, cliente_id, fecha, estado, empresa_id) VALUES (?, ?, ?, 'borrador', ?)",
        (numero, cliente_id, date.today().isoformat(), empresa_id),
    )
    defecto = coef_apu_defecto(conn)      # la cotización conserva los coeficientes vigentes al crearla
    conn.execute(
        "UPDATE cotizaciones SET " + ", ".join(f"apu_coef_{c} = ?" for c in calculo.CATEGORIAS) + " WHERE id = ?",
        (*[defecto.coef(c) * 100 for c in calculo.CATEGORIAS], cur.lastrowid))
    conn.commit()
    return cur.lastrowid, numero


def duplicar_cotizacion(cotizacion_id: int, conn: sqlite3.Connection) -> tuple[int, str]:
    """Crea una cotización nueva en borrador con los mismos datos, ítems (con sus análisis), costos adicionales,
    coeficientes, indirectos y notas. Devuelve (id, número)."""
    cot = conn.execute("SELECT * FROM cotizaciones WHERE id = ?", (cotizacion_id,)).fetchone()
    if cot is None:
        raise ValueError("La cotización no existe.")
    nuevo, numero = crear_cotizacion(cot["cliente_id"], conn, cot["empresa_id"])
    guardar_cotizacion(nuevo, obtener_lineas(cotizacion_id, conn), obtener_cargos(cotizacion_id, conn), conn,
                       tasa=tasa_de_cotizacion(cotizacion_id, conn), cfg=obtener_config_apu(cotizacion_id, conn))
    conn.execute("UPDATE cotizaciones SET notas = ?, proyecto = ? WHERE id = ?",
                 (cot["notas"] or "", cot["proyecto"] or "", nuevo))
    conn.commit()
    return nuevo, numero


def cambiar_cliente_cotizacion(cotizacion_id: int, cliente_id: int, conn: sqlite3.Connection) -> None:
    """Cambia el cliente de una cotización; solo se permite mientras está en borrador."""
    cot = conn.execute("SELECT estado FROM cotizaciones WHERE id = ?", (cotizacion_id,)).fetchone()
    if cot is None:
        raise ValueError("La cotización no existe.")
    if cot["estado"] != "borrador":
        raise ValueError("Solo se puede cambiar el cliente de una cotización en borrador.")
    if conn.execute("SELECT 1 FROM clientes WHERE id = ?", (cliente_id,)).fetchone() is None:
        raise ValueError("El cliente no existe.")
    conn.execute("UPDATE cotizaciones SET cliente_id = ? WHERE id = ?", (cliente_id, cotizacion_id))
    conn.commit()


def eliminar_cotizacion(cotizacion_id: int, conn: sqlite3.Connection) -> str:
    """Elimina la cotización con sus ítems, costos e indirectos; devuelve su número. No permite eliminar una
    que ya tiene factura (la factura conserva el vínculo con su cotización de origen)."""
    cot = conn.execute("SELECT numero FROM cotizaciones WHERE id = ?", (cotizacion_id,)).fetchone()
    if cot is None:
        raise ValueError("La cotización no existe.")
    fac = conn.execute("SELECT numero FROM facturas WHERE cotizacion_id = ?", (cotizacion_id,)).fetchone()
    if fac:
        raise ValueError(f"No se puede eliminar: ya tiene la factura {fac['numero']}.")
    conn.execute("DELETE FROM cotizaciones WHERE id = ?", (cotizacion_id,))     # ítems, costos e indirectos en cascada
    conn.commit()
    return cot["numero"]


def cambiar_empresa_cotizacion(cotizacion_id: int, empresa_id: int, conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE cotizaciones SET empresa_id = ? WHERE id = ?", (empresa_id, cotizacion_id))
    conn.commit()


# ---------- Empresas ----------

CAMPOS_EMPRESA = ("nombre", "subtitulo", "correo", "telefono", "direccion", "ruc", "itbms_tasa", "logo")


def listar_empresas(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM empresas ORDER BY predeterminada DESC, nombre").fetchall()


def obtener_empresa(empresa_id: int | None, conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM empresas WHERE id = ?", (empresa_id,)).fetchone()


def empresa_predeterminada_id(conn: sqlite3.Connection) -> int | None:
    fila = conn.execute("SELECT id FROM empresas ORDER BY predeterminada DESC, id LIMIT 1").fetchone()
    return fila["id"] if fila else None


def empresa_de_cotizacion(cotizacion_id: int, conn: sqlite3.Connection) -> sqlite3.Row | None:
    """Empresa de la cotización (o la predeterminada si no tiene asignada)."""
    fila = conn.execute("SELECT empresa_id FROM cotizaciones WHERE id = ?", (cotizacion_id,)).fetchone()
    empresa = obtener_empresa(fila["empresa_id"], conn) if fila and fila["empresa_id"] else None
    return empresa or obtener_empresa(empresa_predeterminada_id(conn), conn)


def empresa_de_factura(factura_id: int, conn: sqlite3.Connection) -> sqlite3.Row | None:
    fila = conn.execute("SELECT empresa_id FROM facturas WHERE id = ?", (factura_id,)).fetchone()
    empresa = obtener_empresa(fila["empresa_id"], conn) if fila and fila["empresa_id"] else None
    return empresa or obtener_empresa(empresa_predeterminada_id(conn), conn)


def guardar_empresa(datos: dict, conn: sqlite3.Connection, empresa_id: int | None = None) -> int:
    """Crea (o actualiza si se da `empresa_id`) una empresa. Lanza ValueError si faltan datos."""
    nombre = (datos.get("nombre") or "").strip()
    if not nombre:
        raise ValueError("El nombre de la empresa es obligatorio.")
    tasa = float(datos.get("itbms_tasa", 7) or 0)
    if tasa < 0:
        raise ValueError("La tasa de ITBMS no puede ser negativa.")
    valores = [nombre if c == "nombre" else tasa if c == "itbms_tasa" else
               datos.get(c) if c == "logo" else (datos.get(c) or "").strip() for c in CAMPOS_EMPRESA]
    if empresa_id is None:
        primera = conn.execute("SELECT 1 FROM empresas LIMIT 1").fetchone() is None
        cur = conn.execute(
            f"INSERT INTO empresas ({', '.join(CAMPOS_EMPRESA)}, predeterminada) "
            f"VALUES ({', '.join('?' * len(CAMPOS_EMPRESA))}, ?)",
            (*valores, int(primera)),
        )
        empresa_id = cur.lastrowid
    else:
        conn.execute(f"UPDATE empresas SET {', '.join(c + ' = ?' for c in CAMPOS_EMPRESA)} WHERE id = ?",
                     (*valores, empresa_id))
    conn.commit()
    return empresa_id


def establecer_empresa_predeterminada(empresa_id: int, conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE empresas SET predeterminada = (id = ?)", (empresa_id,))
    conn.commit()


def eliminar_empresa(empresa_id: int, conn: sqlite3.Connection) -> None:
    """No permite borrar la última empresa ni una con cotizaciones o facturas."""
    if conn.execute("SELECT COUNT(*) AS n FROM empresas").fetchone()["n"] <= 1:
        raise ValueError("Debe existir al menos una empresa.")
    usos = conn.execute(
        "SELECT (SELECT COUNT(*) FROM cotizaciones WHERE empresa_id = ?) + "
        "(SELECT COUNT(*) FROM facturas WHERE empresa_id = ?) AS n", (empresa_id, empresa_id)).fetchone()["n"]
    if usos:
        raise ValueError(f"No se puede eliminar: tiene {usos} cotización(es)/factura(s) asociadas.")
    era_predeterminada = conn.execute("SELECT predeterminada FROM empresas WHERE id = ?", (empresa_id,)).fetchone()
    conn.execute("DELETE FROM empresas WHERE id = ?", (empresa_id,))
    if era_predeterminada and era_predeterminada["predeterminada"]:
        conn.execute("UPDATE empresas SET predeterminada = 1 WHERE id = (SELECT MIN(id) FROM empresas)")
    conn.commit()


TRANSICIONES_COTIZACION = {
    "borrador": ["enviada"],
    "enviada": ["aprobada", "rechazada"],
    "aprobada": [],
    "rechazada": [],
}


def cambiar_estado_cotizacion(cotizacion_id: int, nuevo: str, conn: sqlite3.Connection) -> None:
    """Valida la transición de estado y la aplica. Lanza ValueError si no es válida."""
    fila = conn.execute(
        "SELECT estado, (SELECT COUNT(*) FROM cotizacion_items WHERE cotizacion_id = ?) AS n_items "
        "FROM cotizaciones WHERE id = ?",
        (cotizacion_id, cotizacion_id),
    ).fetchone()
    if fila is None:
        raise ValueError("La cotización no existe.")
    if nuevo not in TRANSICIONES_COTIZACION.get(fila["estado"], []):
        raise ValueError(f"No se puede pasar de '{fila['estado']}' a '{nuevo}'.")
    if nuevo == "enviada" and fila["n_items"] == 0:
        raise ValueError("Agrega al menos una línea antes de enviar la cotización.")
    conn.execute("UPDATE cotizaciones SET estado = ? WHERE id = ?", (nuevo, cotizacion_id))
    conn.commit()


def resumen_facturacion(cotizacion_id: int, conn: sqlite3.Connection) -> dict:
    """Total de la cotización, lo ya facturado, el saldo por facturar y la cantidad de facturas emitidas."""
    cot = conn.execute("SELECT total FROM cotizaciones WHERE id = ?", (cotizacion_id,)).fetchone()
    if cot is None:
        raise ValueError("La cotización no existe.")
    fila = conn.execute("SELECT COALESCE(SUM(total), 0) AS t, COUNT(*) AS n FROM facturas WHERE cotizacion_id = ?",
                        (cotizacion_id,)).fetchone()
    facturado = round(fila["t"], 2)
    return {"total": cot["total"], "facturado": facturado, "saldo": round(cot["total"] - facturado, 2), "facturas": fila["n"]}


def generar_factura(cotizacion_id: int, conn: sqlite3.Connection, porcentaje: float | None = None,
                    monto: float | None = None, concepto: str | None = None) -> str:
    """Crea una factura de una cotización aprobada y devuelve su número.

    Sin `porcentaje` ni `monto` factura todo el saldo pendiente. `porcentaje` es la parte del total de la
    cotización (p. ej. 30 para un abono del 30%); `monto` es el importe exacto. Una cotización puede tener
    varias facturas mientras no se supere el 100%. Lanza ValueError si no está aprobada, si no queda saldo o
    si el importe es inválido o excede el saldo."""
    cot = conn.execute("SELECT * FROM cotizaciones WHERE id = ?", (cotizacion_id,)).fetchone()
    if cot is None:
        raise ValueError("La cotización no existe.")
    if cot["estado"] != "aprobada":
        raise ValueError("Solo se puede facturar una cotización aprobada.")
    r = resumen_facturacion(cotizacion_id, conn)
    if r["total"] <= 0:
        raise ValueError("La cotización no tiene un total que facturar.")
    if r["saldo"] <= 0.005:
        raise ValueError("Esta cotización ya está facturada por completo.")
    if monto is None and porcentaje is None:
        monto = r["saldo"]
    elif monto is None:
        if not 0 < porcentaje <= 100:
            raise ValueError("El porcentaje debe estar entre 0 y 100.")
        monto = round(r["total"] * porcentaje / 100, 2)
    if monto <= 0:
        raise ValueError("El monto de la factura debe ser mayor que cero.")
    if monto > r["saldo"] + 0.005:
        raise ValueError(f"El monto excede el saldo por facturar (B/. {r['saldo']:,.2f}).")
    if abs(monto - r["saldo"]) <= 0.01:
        monto = r["saldo"]                         # la última factura toma el saldo exacto (sin centavos sueltos)
    monto = round(monto, 2)
    pct = round(monto / r["total"] * 100, 4)
    if concepto is None:
        if r["facturas"] == 0 and monto == r["saldo"]:
            concepto = ""                          # factura única por el total, como antes
        elif monto == r["saldo"]:
            concepto = "Saldo final"
        else:
            concepto = f"Abono {r['facturas'] + 1} ({pct:g}%)"
    numero = next_numero("FAC", "facturas", conn)
    conn.execute(
        "INSERT INTO facturas (numero, cotizacion_id, cliente_id, fecha, estado_pago, total, notas, empresa_id, "
        "titulo_notas, concepto, porcentaje) VALUES (?, ?, ?, ?, 'pendiente', ?, ?, ?, ?, ?, ?)",
        (numero, cotizacion_id, cot["cliente_id"], date.today().isoformat(), monto,
         notas_de_factura(cot, monto, r["total"], round(r["saldo"] - monto, 2), r["facturas"] > 0, conn),
         cot["empresa_id"], obtener_config("titulo_notas_factura", conn, TITULO_NOTAS_FACTURA), concepto.strip(), pct),
    )
    conn.commit()
    return numero


def eliminar_factura(factura_id: int, conn: sqlite3.Connection) -> str:
    """Elimina una factura (la que se hizo mal) y devuelve su número. El importe vuelve al saldo por facturar de
    su cotización, que se puede facturar de nuevo."""
    fila = conn.execute("SELECT numero FROM facturas WHERE id = ?", (factura_id,)).fetchone()
    if fila is None:
        raise ValueError("La factura no existe.")
    conn.execute("DELETE FROM facturas WHERE id = ?", (factura_id,))
    conn.commit()
    return fila["numero"]


def marcar_factura_pagada(factura_id: int, fecha_pago: str, conn: sqlite3.Connection) -> None:
    fila = conn.execute("SELECT estado_pago FROM facturas WHERE id = ?", (factura_id,)).fetchone()
    if fila is None:
        raise ValueError("La factura no existe.")
    if fila["estado_pago"] == "pagada":
        raise ValueError("La factura ya está pagada.")
    conn.execute(
        "UPDATE facturas SET estado_pago = 'pagada', fecha_pago = ? WHERE id = ?",
        (fecha_pago, factura_id),
    )
    conn.commit()


def marcar_factura_vencida(factura_id: int, conn: sqlite3.Connection) -> None:
    fila = conn.execute("SELECT estado_pago FROM facturas WHERE id = ?", (factura_id,)).fetchone()
    if fila is None:
        raise ValueError("La factura no existe.")
    if fila["estado_pago"] != "pendiente":
        raise ValueError("Solo una factura pendiente puede marcarse como vencida.")
    conn.execute("UPDATE facturas SET estado_pago = 'vencida' WHERE id = ?", (factura_id,))
    conn.commit()


PLANTILLA_NOTAS_INICIAL = """ALCANCE
• Diseño estructural integral: modelo y análisis, memoria de cálculo y planos estructurales, conforme al REP-2021 y ACI 318-19.
• El precio corresponde a las áreas de construcción indicadas en el alcance.

EXCLUSIONES
• Estudio geotécnico y recomendaciones de cimentación.
• Cimentación profunda (pilotes), que se cotiza por separado si aplica.
• Planos de taller.
• Inspección en obra y supervisión.
• Diseño de instalaciones (eléctrico, mecánico, sanitario) y fachadas especiales.

REVISIONES
• Se incluye un máximo de dos (2) rondas de revisión por entregable. Las revisiones adicionales o cambios de alcance se cobran por hora o mediante adenda.

FORMA DE PAGO
• 30% al inicio del proyecto.
• 40% a la entrega de planos.
• 30% a la aprobación final.

VALIDEZ DE LA OFERTA
• Esta cotización tiene una validez de 30 días calendario a partir de la fecha de emisión.

OBSERVACIONES
• Si la estructura o cimentación de alguna torre difiere de la torre tipo, el precio de esa torre se reajustará."""

TITULO_NOTAS_FACTURA = "Términos de pago"

PLANTILLA_FACTURA_INICIAL = """{descripcion_pago} Este pago deberá realizarse en un plazo máximo de 3 días hábiles a partir de la fecha de emisión de esta factura a través de cualquiera de las siguientes opciones:

• ACH / Transferencia Bancaria:
   • Banco: Banco General
   • Tipo de Cuenta: Cuenta de Ahorros
   • Número de Cuenta: 0439995725053
   • Titular: JOSE ADRIAN GUERRA ESPINOSA
• Yappy:
   • Número: 6867-4104 (JOSE ADRIAN GUERRA ESPINOSA)

Una vez recibido y verificado el importe, {cierre}"""

# Valores por defecto de la configuración (clave -> valor)
CONFIG_DEFECTOS = {
    "mostrar_estado_pdf": "0",
}


# ---------- Biblioteca de conceptos ----------

def _guardar_insumos(conn, tabla, col, id_, insumos):
    conn.execute(f"DELETE FROM {tabla} WHERE {col} = ?", (id_,))
    conn.executemany(
        f"INSERT INTO {tabla} ({col}, categoria, descripcion, unidad, rendimiento, coeficiente, precio, ref_categoria) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(id_, i.categoria, i.descripcion, i.unidad, i.rendimiento, i.coeficiente, i.precio, i.ref_categoria)
         for i in insumos])


def _concepto(fila, conn) -> Concepto:
    apu = None
    if fila["modalidad"] == calculo.OBRA:
        apu = Apu(fila["apu_base"], _insumos_de(conn.execute(
            "SELECT * FROM concepto_insumos WHERE concepto_id = ? ORDER BY id", (fila["id"],)).fetchall()))
    return Concepto(fila["id"], fila["descripcion"], fila["unidad"], fila["modalidad"], fila["precio"],
                    fila["categoria"], apu, fila["codigo"], fila["fuente"], fila["biblioteca_id"], fila["orden"])


def guardar_concepto(c: Concepto, conn: sqlite3.Connection) -> int:
    """Crea (o actualiza, si `c.id`) un concepto de la biblioteca. Lanza ValueError si no es válido."""
    descripcion = (c.descripcion or "").strip()
    if not descripcion:
        raise ValueError("La descripción del concepto es obligatoria.")
    if c.modalidad not in calculo.MODALIDADES:
        raise ValueError("Modalidad no válida.")
    base = c.apu.base if c.apu else 1.0
    if base <= 0:
        raise ValueError("La cantidad base del análisis debe ser mayor que cero.")
    biblioteca = c.biblioteca_id or biblioteca_por_defecto(conn)
    valores = (descripcion, (c.unidad or "").strip(), c.modalidad, 0.0 if c.modalidad == calculo.OBRA else c.precio,
               (c.categoria or "").strip(), base, c.codigo or "", c.fuente or "", biblioteca, c.orden or 0)
    if c.id is None:
        cid = conn.execute("INSERT INTO conceptos (descripcion, unidad, modalidad, precio, categoria, apu_base, codigo, "
                           "fuente, biblioteca_id, orden) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", valores).lastrowid
    else:
        cid = c.id
        conn.execute("UPDATE conceptos SET descripcion = ?, unidad = ?, modalidad = ?, precio = ?, categoria = ?, "
                     "apu_base = ?, codigo = ?, fuente = ?, biblioteca_id = ?, orden = ? WHERE id = ?", (*valores, cid))
    _guardar_insumos(conn, "concepto_insumos", "concepto_id", cid,
                     c.apu.insumos if c.apu and c.modalidad == calculo.OBRA else [])
    conn.commit()
    return cid


def obtener_concepto(concepto_id: int, conn: sqlite3.Connection) -> Concepto | None:
    fila = conn.execute("SELECT * FROM conceptos WHERE id = ?", (concepto_id,)).fetchone()
    return _concepto(fila, conn) if fila else None


ORDEN_CONCEPTOS = "ORDER BY c.biblioteca_id, (c.orden <> 0), c.orden, c.categoria, c.descripcion"


def listar_conceptos(conn: sqlite3.Connection, texto: str = "", modalidad: str | None = None,
                     disciplina: str | None = None, biblioteca_id: int | None = None) -> list[Concepto]:
    """Conceptos de una biblioteca (o de todas si `biblioteca_id` es None): primero los que no tienen posición fija
    (por categoría), luego los importados en el orden de su fuente. `disciplina` filtra por el primer nivel de la
    categoría («ALBAÑILERÍA › CONCRETOS» -> «ALBAÑILERÍA»)."""
    condiciones, params = [], []
    if texto.strip():
        condiciones.append("(c.descripcion LIKE ? OR c.categoria LIKE ?)")
        params += [f"%{texto.strip()}%"] * 2
    if modalidad:
        condiciones.append("c.modalidad = ?")
        params.append(modalidad)
    if disciplina:
        condiciones.append("(c.categoria = ? OR c.categoria LIKE ?)")
        params += [disciplina, f"{disciplina} › %"]
    if biblioteca_id is not None:
        condiciones.append("c.biblioteca_id = ?")
        params.append(biblioteca_id)
    where = "WHERE " + " AND ".join(condiciones) if condiciones else ""
    filas = conn.execute(f"SELECT c.* FROM conceptos c {where} {ORDEN_CONCEPTOS}", params).fetchall()
    insumos = {}
    for f in conn.execute(f"SELECT ci.* FROM concepto_insumos ci JOIN conceptos c ON c.id = ci.concepto_id {where} "
                          "ORDER BY ci.id", params):
        insumos.setdefault(f["concepto_id"], []).append(f)
    resultado = []
    for f in filas:
        apu = None
        if f["modalidad"] == calculo.OBRA:
            apu = Apu(f["apu_base"], _insumos_de(insumos.get(f["id"], [])))
        resultado.append(Concepto(f["id"], f["descripcion"], f["unidad"], f["modalidad"], f["precio"], f["categoria"],
                                  apu, f["codigo"], f["fuente"], f["biblioteca_id"], f["orden"]))
    return resultado


def disciplinas_conceptos(conn: sqlite3.Connection, biblioteca_id: int | None = None) -> list[str]:
    """Primer nivel de las categorías de una biblioteca (o de todas), sin repetir (para el filtro)."""
    if biblioteca_id is None:
        filas = conn.execute("SELECT DISTINCT categoria FROM conceptos")
    else:
        filas = conn.execute("SELECT DISTINCT categoria FROM conceptos WHERE biblioteca_id = ?", (biblioteca_id,))
    cats = {(f["categoria"] or "").split(" › ")[0] for f in filas}
    return sorted(c for c in cats if c)


# ---------- Bibliotecas (colecciones de conceptos) ----------

def listar_bibliotecas(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Bibliotecas con su número de conceptos (`n`), en el orden en que se crearon."""
    return conn.execute(
        "SELECT b.*, (SELECT COUNT(*) FROM conceptos c WHERE c.biblioteca_id = b.id) AS n FROM bibliotecas b ORDER BY b.id"
    ).fetchall()


def biblioteca_por_defecto(conn: sqlite3.Connection) -> int:
    """La primera biblioteca (la propia del usuario); se crea si por algún motivo no existe ninguna."""
    fila = conn.execute("SELECT MIN(id) AS id FROM bibliotecas").fetchone()
    if fila["id"] is None:
        return conn.execute("INSERT INTO bibliotecas (nombre) VALUES (?)", (BIBLIOTECA_INICIAL,)).lastrowid
    return fila["id"]


def _nombre_valido(nombre: str, conn: sqlite3.Connection, excepto_id: int | None = None) -> str:
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("El nombre de la biblioteca es obligatorio.")
    otra = conn.execute("SELECT id FROM bibliotecas WHERE nombre = ?", (nombre,)).fetchone()
    if otra and otra["id"] != excepto_id:
        raise ValueError(f"Ya existe una biblioteca llamada «{nombre}».")
    return nombre


def crear_biblioteca(nombre: str, conn: sqlite3.Connection, descripcion: str = "") -> int:
    nombre = _nombre_valido(nombre, conn)
    bid = conn.execute("INSERT INTO bibliotecas (nombre, descripcion) VALUES (?, ?)", (nombre, descripcion)).lastrowid
    conn.commit()
    return bid


def renombrar_biblioteca(biblioteca_id: int, nombre: str, conn: sqlite3.Connection) -> None:
    nombre = _nombre_valido(nombre, conn, biblioteca_id)
    conn.execute("UPDATE bibliotecas SET nombre = ? WHERE id = ?", (nombre, biblioteca_id))
    conn.commit()


def duplicar_biblioteca(biblioteca_id: int, conn: sqlite3.Connection, nombre: str | None = None) -> int:
    """Copia la biblioteca con todos sus conceptos y análisis. La copia es independiente: no se vuelve a sincronizar
    con la fuente original (se conserva el orden, pero no el código ni la fuente)."""
    origen = conn.execute("SELECT * FROM bibliotecas WHERE id = ?", (biblioteca_id,)).fetchone()
    if origen is None:
        raise ValueError("La biblioteca no existe.")
    if nombre is None:
        nombre, n = f"{origen['nombre']} (copia)", 2
        while conn.execute("SELECT 1 FROM bibliotecas WHERE nombre = ?", (nombre,)).fetchone():
            nombre, n = f"{origen['nombre']} (copia {n})", n + 1
    nuevo = conn.execute("INSERT INTO bibliotecas (nombre, descripcion) VALUES (?, ?)",
                         (_nombre_valido(nombre, conn), origen["descripcion"])).lastrowid
    for c in conn.execute("SELECT * FROM conceptos WHERE biblioteca_id = ? ORDER BY id", (biblioteca_id,)).fetchall():
        cid = conn.execute(
            "INSERT INTO conceptos (descripcion, unidad, modalidad, precio, categoria, apu_base, codigo, fuente, "
            "biblioteca_id, orden) VALUES (?, ?, ?, ?, ?, ?, '', '', ?, ?)",
            (c["descripcion"], c["unidad"], c["modalidad"], c["precio"], c["categoria"], c["apu_base"], nuevo,
             c["orden"])).lastrowid
        conn.execute(
            "INSERT INTO concepto_insumos (concepto_id, categoria, descripcion, unidad, rendimiento, coeficiente, "
            "precio, ref_categoria) SELECT ?, categoria, descripcion, unidad, rendimiento, coeficiente, precio, "
            "ref_categoria FROM concepto_insumos WHERE concepto_id = ? ORDER BY id", (cid, c["id"]))
    conn.commit()
    return nuevo


def eliminar_biblioteca(biblioteca_id: int, conn: sqlite3.Connection) -> int:
    """Elimina la biblioteca y sus conceptos; devuelve cuántos conceptos se eliminaron. Debe quedar al menos una.
    Las cotizaciones no cambian (usan copias de los conceptos)."""
    if conn.execute("SELECT COUNT(*) AS n FROM bibliotecas").fetchone()["n"] <= 1:
        raise ValueError("Debe existir al menos una biblioteca.")
    n = conn.execute("SELECT COUNT(*) AS n FROM conceptos WHERE biblioteca_id = ?", (biblioteca_id,)).fetchone()["n"]
    conn.execute("DELETE FROM conceptos WHERE biblioteca_id = ?", (biblioteca_id,))     # sus insumos caen en cascada
    conn.execute("DELETE FROM bibliotecas WHERE id = ?", (biblioteca_id,))
    conn.commit()
    return n


def copiar_conceptos(concepto_ids: list[int], biblioteca_destino: int, conn: sqlite3.Connection) -> int:
    """Copia conceptos (con su análisis) a otra biblioteca; devuelve cuántos copió."""
    n = 0
    for cid in concepto_ids:
        c = obtener_concepto(cid, conn)
        if c is None:
            continue
        c.id, c.biblioteca_id, c.codigo, c.fuente = None, biblioteca_destino, "", ""
        guardar_concepto(c, conn)
        n += 1
    return n


def importar_conceptos(conceptos: list[dict], fuente: str, conn: sqlite3.Connection) -> tuple[int, int]:
    """Importa (o actualiza, por `codigo`) conceptos con análisis en la biblioteca llamada como la `fuente` (se crea si no
    existe); devuelve (nuevos, actualizados).
    Cada concepto es un dict: codigo, descripcion, unidad, categoria, insumos=[[cat, desc, ud, cantidad, coef, precio, ref]]."""
    fila = conn.execute("SELECT id FROM bibliotecas WHERE nombre = ?", (fuente,)).fetchone()
    biblioteca = fila["id"] if fila else conn.execute("INSERT INTO bibliotecas (nombre) VALUES (?)", (fuente,)).lastrowid
    existentes = {f["codigo"]: f["id"] for f in conn.execute(
        "SELECT id, codigo FROM conceptos WHERE biblioteca_id = ? AND fuente = ?", (biblioteca, fuente))}
    nuevos = actualizados = 0
    for c in conceptos:
        valores = (c["descripcion"].strip(), c.get("unidad", ""), calculo.OBRA, 0.0, c.get("categoria", ""), 1.0,
                   str(c["codigo"]), fuente, biblioteca, int(c["codigo"]) if str(c["codigo"]).isdigit() else 0)
        cid = existentes.get(str(c["codigo"]))
        if cid is None:
            cid = conn.execute("INSERT INTO conceptos (descripcion, unidad, modalidad, precio, categoria, apu_base, "
                               "codigo, fuente, biblioteca_id, orden) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               valores).lastrowid
            nuevos += 1
        else:
            conn.execute("UPDATE conceptos SET descripcion = ?, unidad = ?, modalidad = ?, precio = ?, categoria = ?, "
                         "apu_base = ?, codigo = ?, fuente = ?, biblioteca_id = ?, orden = ? WHERE id = ?",
                         (*valores, cid))
            actualizados += 1
        conn.execute("DELETE FROM concepto_insumos WHERE concepto_id = ?", (cid,))
        conn.executemany(
            "INSERT INTO concepto_insumos (concepto_id, categoria, descripcion, unidad, rendimiento, coeficiente, "
            "precio, ref_categoria) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(cid, *i) for i in c["insumos"]])
    conn.commit()
    return nuevos, actualizados


def eliminar_concepto(concepto_id: int, conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM conceptos WHERE id = ?", (concepto_id,))
    conn.commit()


def duplicar_concepto(concepto_id: int, conn: sqlite3.Connection) -> int:
    c = obtener_concepto(concepto_id, conn)
    if c is None:
        raise ValueError("El concepto no existe.")
    c.id = None
    c.descripcion = f"{c.descripcion} (copia)"
    return guardar_concepto(c, conn)


def buscar_concepto(descripcion: str, unidad: str, conn: sqlite3.Connection,
                    biblioteca_id: int | None = None) -> Concepto | None:
    consulta = "SELECT * FROM conceptos WHERE descripcion = ? AND unidad = ?"
    params = [descripcion.strip(), (unidad or "").strip()]
    if biblioteca_id is not None:
        consulta += " AND biblioteca_id = ?"
        params.append(biblioteca_id)
    fila = conn.execute(consulta, params).fetchone()
    return _concepto(fila, conn) if fila else None


def precio_referencial(c: Concepto, conn: sqlite3.Connection, cfg: ConfigApu | None = None) -> float:
    """Servicio: su precio. Mano de obra y material: precio de venta con los coeficientes por defecto."""
    if c.modalidad == calculo.OBRA and c.apu:
        return calculo.precio_unitario(c.apu, cfg or coef_apu_defecto(conn))
    return c.precio


def costo_directo(c: Concepto) -> float:
    """Costo unitario sin coeficientes (en un servicio, su precio)."""
    return round(calculo.costo_unitario(c.apu), 2) if c.modalidad == calculo.OBRA and c.apu else c.precio


def concepto_desde_linea(l: Linea, categoria: str = "") -> Concepto:
    """Copia de un ítem de cotización para guardarlo en la biblioteca (con su análisis, si lo tiene)."""
    return Concepto(None, texto_rico.a_texto_plano(texto_rico.con_titulo(l.titulo, l.descripcion)), l.unidad, l.modalidad, 0.0 if l.usa_apu else l.precio, categoria,
                    l.apu.copia() if l.usa_apu and l.apu else None)


def linea_desde_concepto(c: Concepto, cantidad: float = 1.0, nivel: int = 0) -> Linea:
    """Ítem de cotización listo para insertar a partir de un concepto de la biblioteca."""
    usa = c.modalidad == calculo.OBRA
    return Linea("item", nivel, c.descripcion, cantidad, c.precio, True, c.unidad, c.modalidad,
                 (c.apu.copia() if c.apu else Apu()) if usa else None)


def obtener_config(clave: str, conn: sqlite3.Connection, defecto: str = "") -> str:
    fila = conn.execute("SELECT valor FROM configuracion WHERE clave = ?", (clave,)).fetchone()
    return fila["valor"] if fila else defecto


def guardar_config(clave: str, valor: str, conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO configuracion (clave, valor) VALUES (?, ?) "
        "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
        (clave, valor),
    )
    conn.commit()


TITULO_NOTAS = "Alcance, exclusiones y condiciones"


def obtener_plantilla_notas(conn: sqlite3.Connection) -> str:
    return obtener_config("plantilla_notas", conn, PLANTILLA_NOTAS_INICIAL)


def guardar_plantilla_notas(texto: str, conn: sqlite3.Connection) -> None:
    guardar_config("plantilla_notas", texto, conn)


def obtener_notas(cotizacion_id: int, conn: sqlite3.Connection) -> str:
    fila = conn.execute("SELECT notas FROM cotizaciones WHERE id = ?", (cotizacion_id,)).fetchone()
    return (fila["notas"] or "") if fila else ""


def guardar_notas(cotizacion_id: int, notas: str, conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE cotizaciones SET notas = ? WHERE id = ?", (notas, cotizacion_id))
    conn.commit()


def obtener_plantilla_factura(conn: sqlite3.Connection) -> str:
    """Plantilla de notas (términos de pago) con que nace cada factura. Admite {descripcion_pago}, {cierre},
    {monto}, {total}, {saldo}, {porcentaje} y {cotizacion}."""
    return obtener_config("plantilla_notas_factura", conn, PLANTILLA_FACTURA_INICIAL)


def guardar_plantilla_factura(texto: str, conn: sqlite3.Connection) -> None:
    guardar_config("plantilla_notas_factura", texto, conn)


def restaurar_plantilla_factura(conn: sqlite3.Connection) -> str:
    conn.execute("DELETE FROM configuracion WHERE clave = 'plantilla_notas_factura'")
    conn.commit()
    return PLANTILLA_FACTURA_INICIAL


def notas_de_factura(cot, monto: float, total: float, saldo_despues: float, hay_previas: bool,
                     conn: sqlite3.Connection) -> str:
    """Notas iniciales de una factura: la plantilla de términos de pago con los importes de esta factura."""
    dinero = lambda v: f"B/. {v:,.2f}"
    liquida = saldo_despues <= 0.005
    if liquida and not hay_previas:
        descripcion = (f"El presente pago por la cantidad de {dinero(monto)} corresponde al pago total de los servicios "
                       f"prestados, por el monto acordado de {dinero(total)}.")
    elif liquida:
        descripcion = (f"El presente pago por la cantidad de {dinero(monto)} corresponde a la cancelación del saldo "
                       f"pendiente y liquidación total del monto final acordado de {dinero(total)} por los servicios prestados.")
    else:
        descripcion = (f"El presente pago por la cantidad de {dinero(monto)} corresponde a un abono del "
                       f"{monto / total * 100:.2f}% del monto total acordado de {dinero(total)} por los servicios "
                       f"prestados. El saldo pendiente tras este pago será de {dinero(saldo_despues)}.".replace(".00%", "%"))
    cierre = ("la obligación contractual quedará formalmente finiquitada." if liquida else
              f"el importe se aplicará a la cotización {cot['numero']} y se actualizará el saldo pendiente.")
    valores = {"descripcion_pago": descripcion, "cierre": cierre, "monto": dinero(monto), "total": dinero(total),
               "saldo": dinero(saldo_despues), "porcentaje": f"{monto / total * 100:.2f}".rstrip("0").rstrip("."),
               "cotizacion": cot["numero"]}
    texto = obtener_plantilla_factura(conn)
    for clave, valor in valores.items():
        texto = texto.replace("{" + clave + "}", valor)
    return texto


def restaurar_plantilla_notas(conn: sqlite3.Connection) -> str:
    conn.execute("DELETE FROM configuracion WHERE clave = 'plantilla_notas'")
    conn.commit()
    return PLANTILLA_NOTAS_INICIAL


def obtener_opcion(clave: str, conn: sqlite3.Connection) -> str:
    return obtener_config(clave, conn, CONFIG_DEFECTOS[clave])


def mostrar_estado_pdf(conn: sqlite3.Connection) -> bool:
    return obtener_opcion("mostrar_estado_pdf", conn) == "1"


def obtener_proyecto(cotizacion_id: int, conn: sqlite3.Connection) -> str:
    fila = conn.execute("SELECT proyecto FROM cotizaciones WHERE id = ?", (cotizacion_id,)).fetchone()
    return (fila["proyecto"] or "") if fila else ""


def guardar_proyecto(cotizacion_id: int, proyecto: str, conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE cotizaciones SET proyecto = ? WHERE id = ?", (proyecto, cotizacion_id))
    conn.commit()


def obtener_notas_factura(factura_id: int, conn: sqlite3.Connection) -> str:
    fila = conn.execute("SELECT notas FROM facturas WHERE id = ?", (factura_id,)).fetchone()
    return (fila["notas"] or "") if fila else ""


def obtener_titulo_notas(tabla: str, registro_id: int, conn: sqlite3.Connection) -> str:
    """Título editable del bloque de notas ('' = el título por defecto)."""
    assert tabla in ("cotizaciones", "facturas")
    fila = conn.execute(f"SELECT titulo_notas FROM {tabla} WHERE id = ?", (registro_id,)).fetchone()
    return (fila["titulo_notas"] or "") if fila else ""


def guardar_titulo_notas(tabla: str, registro_id: int, titulo: str, conn: sqlite3.Connection) -> None:
    assert tabla in ("cotizaciones", "facturas")
    conn.execute(f"UPDATE {tabla} SET titulo_notas = ? WHERE id = ?", (titulo.strip(), registro_id))
    conn.commit()


def guardar_notas_factura(factura_id: int, notas: str, conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE facturas SET notas = ? WHERE id = ?", (notas, factura_id))
    conn.commit()


# ---------- Clientes ----------

def guardar_cliente(datos: dict, conn: sqlite3.Connection, cliente_id: int | None = None) -> int:
    """Crea (o actualiza si se da `cliente_id`) un cliente. Lanza ValueError si falta el nombre."""
    nombre = (datos.get("nombre") or "").strip()
    if not nombre:
        raise ValueError("El nombre del cliente es obligatorio.")
    valores = (nombre, (datos.get("identificacion") or "").strip(), (datos.get("contacto") or "").strip())
    if cliente_id is None:
        cur = conn.execute("INSERT INTO clientes (nombre, identificacion, contacto) VALUES (?, ?, ?)", valores)
        cliente_id = cur.lastrowid
    else:
        conn.execute("UPDATE clientes SET nombre = ?, identificacion = ?, contacto = ? WHERE id = ?",
                     (*valores, cliente_id))
    conn.commit()
    return cliente_id


def eliminar_cliente(cliente_id: int, conn: sqlite3.Connection) -> None:
    """No permite borrar un cliente con cotizaciones o facturas."""
    usos = conn.execute(
        "SELECT (SELECT COUNT(*) FROM cotizaciones WHERE cliente_id = ?) + "
        "(SELECT COUNT(*) FROM facturas WHERE cliente_id = ?) AS n", (cliente_id, cliente_id)).fetchone()["n"]
    if usos:
        raise ValueError(f"No se puede eliminar: el cliente tiene {usos} cotización(es)/factura(s) asociadas.")
    conn.execute("DELETE FROM clientes WHERE id = ?", (cliente_id,))
    conn.commit()
