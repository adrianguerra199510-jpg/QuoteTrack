"""Texto con formato sencillo (negrita, cursiva, subrayado, viñetas y numeración) para las descripciones de los ítems.

Se guarda como un HTML mínimo (`<p>`, `<ul>/<ol>/<li>`, `<b>`, `<i>`, `<u>`, `<br>`); el texto sin etiquetas de
versiones anteriores (o de la base de la Contraloría) sigue funcionando como texto plano con saltos de línea.
Este módulo no depende de Qt: lo usan la interfaz, el PDF y el Word."""
import re
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser

INICIOS_RICOS = ("<p>", "<ul>", "<ol>", "<p/>")


@dataclass
class Tramo:
    texto: str
    negrita: bool = False
    cursiva: bool = False
    subrayado: bool = False

    def mismo_formato(self, otro: "Tramo") -> bool:
        return (self.negrita, self.cursiva, self.subrayado) == (otro.negrita, otro.cursiva, otro.subrayado)


@dataclass
class Parrafo:
    tipo: str = "p"                      # 'p' párrafo · 'ul' viñeta · 'ol' lista numerada
    tramos: list = field(default_factory=list)
    numero: int = 0                      # posición dentro de una lista numerada (1, 2, 3…)

    @property
    def texto(self) -> str:
        return "".join(t.texto for t in self.tramos)


def es_rico(s: str | None) -> bool:
    return bool(s) and s.lstrip().startswith(INICIOS_RICOS)


class _Lector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parrafos: list[Parrafo] = []
        self.actual: Parrafo | None = None
        self.formato = {"b": 0, "i": 0, "u": 0}
        self.listas: list[str] = []

    def _abrir(self, tipo):
        self._cerrar()
        self.actual = Parrafo(tipo)

    def _cerrar(self):
        if self.actual is not None:
            self.parrafos.append(self.actual)
            self.actual = None

    def handle_starttag(self, tag, attrs):
        if tag in ("b", "strong"):
            self.formato["b"] += 1
        elif tag in ("i", "em"):
            self.formato["i"] += 1
        elif tag == "u":
            self.formato["u"] += 1
        elif tag in ("ul", "ol"):
            self._cerrar()
            self.listas.append(tag)
        elif tag == "li":
            self._abrir(self.listas[-1] if self.listas else "ul")
        elif tag == "p":
            self._abrir("p")
        elif tag == "br":
            if self.actual is None:
                self._abrir("p")
            self.actual.tramos.append(Tramo("\n", *self._f()))

    def handle_endtag(self, tag):
        if tag in ("b", "strong"):
            self.formato["b"] = max(0, self.formato["b"] - 1)
        elif tag in ("i", "em"):
            self.formato["i"] = max(0, self.formato["i"] - 1)
        elif tag == "u":
            self.formato["u"] = max(0, self.formato["u"] - 1)
        elif tag in ("ul", "ol"):
            self._cerrar()
            if self.listas:
                self.listas.pop()
        elif tag in ("li", "p"):
            self._cerrar()

    def _f(self):
        return (self.formato["b"] > 0, self.formato["i"] > 0, self.formato["u"] > 0)

    def handle_data(self, data):
        if not data:
            return
        if self.actual is None:
            if not data.strip():
                return
            self._abrir("p")
        self.actual.tramos.append(Tramo(data, *self._f()))

    def cerrar(self):
        self._cerrar()
        return self.parrafos


def _unir(tramos: list) -> list:
    """Une tramos contiguos con el mismo formato y descarta los vacíos."""
    res = []
    for t in tramos:
        if not t.texto:
            continue
        if res and res[-1].mismo_formato(t):
            res[-1] = Tramo(res[-1].texto + t.texto, t.negrita, t.cursiva, t.subrayado)
        else:
            res.append(Tramo(t.texto, t.negrita, t.cursiva, t.subrayado))
    return res


def _numerar(parrafos: list) -> list:
    n = 0
    for p in parrafos:
        n = n + 1 if p.tipo == "ol" else 0
        p.numero = n if p.tipo == "ol" else 0
    return parrafos


def parsear(s: str | None) -> list:
    """Lista de párrafos de un texto (con formato o plano). El texto plano da un párrafo por línea."""
    if not s:
        return []
    if not es_rico(s):
        lineas = s.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        while lineas and not lineas[-1].strip():
            lineas.pop()
        return _numerar([Parrafo("p", [Tramo(l)] if l else []) for l in lineas])
    lector = _Lector()
    lector.feed(s)
    lector.close()
    parrafos = lector.cerrar()
    for p in parrafos:
        p.tramos = _unir(p.tramos)
    while parrafos and parrafos[-1].tipo == "p" and not parrafos[-1].tramos:
        parrafos.pop()
    return _numerar(parrafos)


def _html_tramo(t: Tramo) -> str:
    h = escape(t.texto, quote=False).replace("\n", "<br>")
    for activo, etiqueta in ((t.subrayado, "u"), (t.cursiva, "i"), (t.negrita, "b")):
        if activo:
            h = f"<{etiqueta}>{h}</{etiqueta}>"
    return h


def serializar(parrafos: list) -> str:
    """HTML mínimo canónico de una lista de párrafos."""
    partes, lista = [], None
    for p in parrafos:
        cuerpo = "".join(_html_tramo(t) for t in _unir(p.tramos))
        if p.tipo in ("ul", "ol"):
            if lista != p.tipo:
                if lista:
                    partes.append(f"</{lista}>")
                partes.append(f"<{p.tipo}>")
                lista = p.tipo
            partes.append(f"<li>{cuerpo}</li>")
        else:
            if lista:
                partes.append(f"</{lista}>")
                lista = None
            partes.append(f"<p>{cuerpo}</p>")
    if lista:
        partes.append(f"</{lista}>")
    return "".join(partes)


def a_html(s: str | None) -> str:
    """Texto (plano o con formato) como HTML mínimo, listo para mostrarlo o cargarlo en un editor."""
    return serializar(parsear(s))


def a_texto_plano(s: str | None) -> str:
    """Texto sin formato: un párrafo por línea, con «• » y «1. » en las listas."""
    if not s:
        return ""
    if not es_rico(s):
        return s
    lineas = []
    for p in parsear(s):
        prefijo = "• " if p.tipo == "ul" else f"{p.numero}. " if p.tipo == "ol" else ""
        lineas.append(prefijo + p.texto)
    return "\n".join(lineas)


def es_vacio(s: str | None) -> bool:
    return not any(t.texto.strip() for p in parsear(s) for t in p.tramos)


def resumen(s: str | None, largo: int = 90) -> str:
    """Una línea corta para tablas y mensajes."""
    plano = re.sub(r"\s+", " ", a_texto_plano(s)).strip()
    return plano if len(plano) <= largo else plano[:largo - 1].rstrip() + "…"


def con_titulo(titulo: str | None, descripcion: str | None) -> str:
    """Descripción con el título del ítem como primer párrafo en negrita (texto rico). Sin título, no cambia nada."""
    titulo = (titulo or "").strip()
    if not titulo:
        return descripcion or ""
    return serializar([Parrafo("p", [Tramo(titulo, negrita=True)])] + parsear(descripcion))
