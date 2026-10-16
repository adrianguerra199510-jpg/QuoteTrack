"""Convierte el PDF «Base de datos de costo directo» de la Contraloría General de la República de Panamá
(texto en Markdown, extraído del PDF) en `assets/base_costos_cgr.json.gz`, que la app importa a la biblioteca.

Uso:  python scripts/generar_base_cgr.py RUTA/AL/archivo.md [--informe]

Cada actividad (1,169) trae su análisis de costos unitarios: mano de obra, materiales, herramienta (% de la mano
de obra), equipo, auxiliares y matrices (otras actividades). La app los guarda como insumos de un análisis de precio
unitario. No se ejecuta al iniciar la app; solo sirve para regenerar el archivo de datos."""
import collections
import gzip
import json
import re
import sys
from pathlib import Path

SALIDA = Path(__file__).resolve().parent.parent / "assets" / "base_costos_cgr.json.gz"
FUENTE = "CGR Panamá - Base de costos directos v002 (salarios jul 2025 - jun 2026)"

# Disciplinas (capítulos principales) por página inicial; el documento solo las marca de forma irregular
DISCIPLINAS = [(46, "ALBAÑILERÍA"), (142, "TECHOS"), (192, "ACABADOS Y REMODELACIONES"), (339, "CARRETERAS"),
               (546, "ACUEDUCTOS Y ALCANTARILLADOS"), (680, "PLOMERÍA"), (741, "ELECTRICIDAD"),
               (987, "ESTRUCTURAS METÁLICAS"), (1032, "PUERTAS Y VENTANAS"), (1103, "VIGADUCTOS Y CI ELÉCTRICOS"),
               (1123, "FECE")]

# Encabezados que el PDF pegó con el anterior (sin separador)
ENCABEZADOS = {
    46: "LIMPIEZA, REPLANTEO, DEMOLICIÓN Y EXCAVACIÓN",
    426: "CAJAS DE REGISTRO › CÁMARA DE INSPECCIÓN 1.23 M X 1.23 M X 0.15 M",
    546: "TUBERÍAS PVC, VÁLVULAS E HIDRANTES › TUBERÍA PVC",
    547: "TUBERÍA PVC › SDR-17 › SDR-17 LISA",
    618: "TUBERÍA CORRUGADA › CORRUGADA R35",
    627: "VÁLVULAS (INCLUYEN CAJA DE PROTECCIÓN) › VÁLVULAS CON CAJA DE BLOQUE PARA ACUEDUCTOS RURALES",
    741: "INSTALACIÓN DE TUBERÍAS",
    863: "BREAKER PLUG IN › BREAKER PLUG IN 1 POLO",
    880: "BREAKER PLUG IN EN CAJA › BREAKER DE 2 POLOS EN CAJA",
    889: "SAFETY SWITCHES › SAFETY SWITCHES TIPO CUCHILLA 3 POLOS",
    1032: "PUERTAS",
}
SECCIONES = {"mano de obra": "mano_obra", "materiales": "material", "herramienta": "auxiliar", "equipo": "auxiliar",
             "auxiliares": "auxiliar", "matrices": "auxiliar"}
NUM = r"-?[\d,]*\.?\d+"
# `resto`: cuando la descripción es larga, el PDF deja el final del texto después de los números
FILA = re.compile(rf"^(?P<ini>.+?)\s+(?P<unidad>\S+)\s+(?P<rend>{NUM})\s+(?P<cant>{NUM})\s+(?P<cu>{NUM})\s+"
                  rf"(?P<total>{NUM})(?:\s+(?P<resto>[A-Za-zÁÉÍÓÚÑ(].*))?$")


def num(s: str) -> float:
    return float(s.replace(",", ""))


def disciplina(pagina: int) -> str:
    return [d for p, d in DISCIPLINAS if p <= pagina][-1]


def parsear_indice(texto: str) -> list[dict]:
    """Filas del índice (página, descripción, unidad, costo) con su capítulo (último encabezado en negrita)."""
    indice = texto.split("\n## ANÁLISIS DE COSTOS UNITARIOS\n")[0]
    filas, capitulo = [], ""
    for pagina, celda, unidad, costo in re.findall(r"^\| (\d+) \| (.*?) \| ([^|]*) \| ([^|]*) \|$", indice, re.M):
        segmentos = re.split(r"\*\*", celda)
        desc, nuevo = "", None
        for i, seg in enumerate(segmentos):
            seg = seg.strip()
            if i % 2 == 1:                       # negrita = encabezado de capítulo
                if not desc and nuevo is None:   # «**CAPÍTULO**Descripción»: aplica a esta fila
                    capitulo = ENCABEZADOS.get(int(pagina), seg.replace("P0 - BASE DE DATOS DE COSTOS DIRECTOS", ""))
                else:                            # «Descripción**CAPÍTULO**»: aplica a las siguientes
                    nuevo = seg
            elif seg:
                desc += seg
        filas.append({"pagina": int(pagina), "descripcion": desc, "unidad": unidad.strip(),
                      "costo": num(costo), "capitulo": capitulo})
        if nuevo is not None:
            capitulo = ENCABEZADOS.get(int(pagina) + 1, nuevo)
    return filas


def celdas_de(linea: str) -> list[str]:
    linea = re.sub(r"\*\*Total de [^*]*\*\*", " ", linea).replace("**", " ").strip()
    if linea.startswith("|"):
        return [c.strip() for c in linea.strip("|").split("|")]
    return [linea]


def parsear_bloque(bloque: str, pagina_esperada: int | None = None) -> dict:
    """Un análisis de costos unitarios: cabecera + insumos por sección. Si la cabecera no trae «Página:»
    (el PDF la perdió en unas pocas actividades), se usa `pagina_esperada`."""
    cab = re.search(r"Página:\s*(\d+)", bloque)
    titulo = re.search(r"\n### (?!Página|Costo|Unidad)(.+)", bloque)
    pagina = int(cab.group(1)) if cab else pagina_esperada
    unidad = (re.search(r"Unidad:\s*(\S+)", bloque) or [None, ""])[1]
    insumos, seccion = [], None
    for linea in bloque.split("\n"):
        if not linea.strip() or set(linea.strip()) <= set("|- :"):
            continue
        celdas = celdas_de(linea)
        primera = celdas[0].replace("+", "").strip().lower()
        # sección anunciada en la primera celda («Mano de Obra», «| Materiales | clave | …», «Matrices+»)
        if primera in SECCIONES:
            seccion = SECCIONES[primera]
            celdas = [c for c in celdas[1:] if c]
            if not celdas:
                continue
        elif celdas[0].lower().startswith(("total de", "costo directo", "precio unitario", "subtotal")) or \
                (len(celdas) > 1 and celdas[1].lower().startswith(("costo directo", "precio unitario"))):
            continue
        celdas = [c for c in celdas if c and c not in ("+", "\\+")]
        if not celdas or seccion is None:
            continue
        # fila de cuadrilla («Rendimiento: 0.105820 m/lb»): la cantidad real por unidad es 1 / rendimiento
        if any(c.startswith("Rendimiento:") for c in celdas) and insumos:
            insumos[-1]["cantidad"] = round(1 / insumos[-1]["rend"], 6) if insumos[-1]["rend"] else insumos[-1]["cantidad"]
            continue
        if len(celdas) > 1 and re.fullmatch(rf"{NUM} {NUM}", celdas[-1]):    # sobra el total de la sección
            celdas[-1] = celdas[-1].split(" ")[0]
        texto = " ".join(celdas)
        m = FILA.match(texto)
        if not m:
            continue
        # clave y descripción: 7 celdas reparten (clave, desc, unidad, …); con 6, la primera trae ambas
        if len(celdas) >= 7:
            clave, desc = celdas[0], " ".join(celdas[1:-5])
        else:
            partes = m.group("ini").split(" ", 1)
            clave, desc = partes[0], (partes[1] if len(partes) > 1 else "")
        clave = clave.lstrip("+\\ ").strip()
        if clave == "+" or not desc:
            desc = (desc or m.group("ini")).lstrip("+\\ ").strip()
        if m.group("resto"):
            desc = f"{desc} {m.group('resto')}"
        insumos.append({"seccion": seccion, "clave": clave, "descripcion": desc.strip(), "unidad": m.group("unidad"),
                        "rend": num(m.group("rend")), "cantidad": num(m.group("cant")), "costo": num(m.group("cu")),
                        "total": num(m.group("total"))})
    return {"pagina": pagina, "unidad": unidad, "titulo": titulo.group(1).strip() if titulo else "", "insumos": insumos}


def a_insumos(insumos: list[dict]) -> list[list]:
    """[categoría, descripción, unidad, rendimiento (cantidad), coeficiente, precio, referencia]."""
    res = []
    for i in insumos:
        unidad = i["unidad"]
        if unidad.startswith("(%)"):             # herramienta: % del coste de la mano de obra
            ref = "mano_obra" if unidad == "(%)mo" else "material"
            res.append(["auxiliar", i["descripcion"], "%", 1.0, i["cantidad"], 0.0, ref])
        else:
            res.append([i["seccion"], i["descripcion"], unidad, i["cantidad"], 1.0, i["costo"], ""])
    return res


def coste(insumos: list[list]) -> float:
    base = {}
    for cat, _d, _u, rend, coef, precio, ref in insumos:
        if not ref:
            base[cat] = base.get(cat, 0.0) + rend * coef * precio
    return sum(base.values()) + sum(rend * coef * base.get(ref, 0.0) for _c, _d, _u, rend, coef, _p, ref in insumos if ref)


def arreglar_palabras(textos: list[str]) -> dict:
    """El PDF une palabras al cortar renglones («COMPACTADOMANUALMENTE»): se separan cuando ambas mitades son
    palabras que aparecen sueltas muchas veces en el propio documento."""
    freq = collections.Counter(w for t in textos for w in re.findall(r"[A-ZÁÉÍÓÚÑÜ]{3,}", t.upper()))
    vocab = {w for w, n in freq.items() if n >= 6}
    cambios = {}
    for palabra in freq:
        if len(palabra) < 9 or palabra in vocab:
            continue
        for i in range(3, len(palabra) - 2):
            a, b = palabra[:i], palabra[i:]
            if a in vocab and b in vocab:
                cambios[palabra] = f"{a} {b}"
                break
    return cambios


def prettificar(unidad: str) -> str:
    return {"m2": "m²", "m3": "m³", "M2": "m²", "M3": "m³"}.get(unidad, unidad)


def main(ruta_md: str, informe: bool = False) -> None:
    texto = Path(ruta_md).read_text(encoding="utf-8", errors="replace")
    texto = re.sub(r"!\[[^\]]*\]\(data:image[^)]*\)", "", texto)         # imágenes incrustadas
    indice = {f["pagina"]: f for f in parsear_indice(texto)}
    bloques = {}
    for b in texto.split("\n## ANÁLISIS DE COSTOS UNITARIOS\n")[1:]:
        # Solo los análisis bien formados (que empiezan por su cabecera «Página: N»). En unas pocas actividades el PDF
        # desordenó la página (los números de una actividad quedaron junto al nombre de la siguiente).
        cab = re.match(r"\s*### Página:\s*(\d+)", b)
        if cab:
            b = re.split(r"\n### Página:", b[cab.end():], maxsplit=1)[0]       # descarta el nombre de la siguiente
            bloques[int(cab.group(1))] = parsear_bloque("### Página: " + cab.group(1) + b)
    cambios = arreglar_palabras([f["descripcion"] for f in indice.values()] +
                                [i["descripcion"] for b in bloques.values() for i in b["insumos"]])
    arreglo = lambda s: re.sub(r"[A-ZÁÉÍÓÚÑÜ]{9,}", lambda m: cambios.get(m.group(0), m.group(0)), s)
    conceptos, problemas = [], []
    for pagina, fila in sorted(indice.items()):
        b = bloques.get(pagina, {"insumos": [], "unidad": "", "titulo": ""})
        insumos = a_insumos(b["insumos"])
        for i in insumos:
            i[1] = arreglo(i[1])
        calculado = coste(insumos)
        analisis = True
        if not insumos or abs(calculado - fila["costo"]) > max(0.05, fila["costo"] * 0.005):
            # El PDF trae estas páginas desordenadas y el análisis no se pudo reconstruir: se importa solo el
            # costo directo publicado, en una única fila, y se informa.
            problemas.append((pagina, f"análisis no reconstruible (calculado {calculado:.2f}, publicado {fila['costo']:.2f})"))
            insumos = [["material", f"Costo directo publicado (pág. {pagina} de la base; análisis detallado no disponible)",
                        fila["unidad"] or b["unidad"], 1.0, 1.0, fila["costo"], ""]]
            analisis = False
        cat = disciplina(pagina) + (f" › {fila['capitulo']}" if fila["capitulo"] else "")
        conceptos.append({"codigo": str(pagina), "descripcion": arreglo(fila["descripcion"] or b["titulo"]),
                          "unidad": prettificar(fila["unidad"] or b["unidad"]), "categoria": arreglo(cat),
                          "costo": fila["costo"], "analisis": analisis, "insumos": insumos})
    print(f"Índice: {len(indice)} · análisis bien formados: {len(bloques)} · conceptos: {len(conceptos)} · palabras corregidas: {len(cambios)}")
    print(f"Actividades sin análisis reconstruible (se importan con el costo publicado): {len(problemas)}")
    if informe:
        for p, msg in problemas[:60]:
            print("  pág.", p, msg)
        print(dict(list(cambios.items())[:25]))
    SALIDA.parent.mkdir(exist_ok=True)
    with gzip.open(SALIDA, "wt", encoding="utf-8", compresslevel=9) as f:
        json.dump({"fuente": FUENTE, "conceptos": conceptos}, f, ensure_ascii=False, separators=(",", ":"))
    print("Escrito", SALIDA, f"({SALIDA.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], "--informe" in sys.argv)
