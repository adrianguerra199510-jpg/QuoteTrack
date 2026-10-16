"""Base de datos de costo directo de la Contraloría General de la República de Panamá (1,169 actividades con su
análisis de costos unitarios), empaquetada en assets/base_costos_cgr.json.gz y lista para importar a la biblioteca."""
import gzip
import json

from app import db
from app.recursos import ruta_recurso

ARCHIVO = "assets/base_costos_cgr.json.gz"


def cargar() -> dict:
    with gzip.open(ruta_recurso(ARCHIVO), "rt", encoding="utf-8") as f:
        return json.load(f)


def importar(conn) -> tuple[int, int, str]:
    """Importa la base a la biblioteca. Devuelve (nuevas, actualizadas, fuente); es idempotente."""
    datos = cargar()
    nuevos, actualizados = db.importar_conceptos(datos["conceptos"], datos["fuente"], conn)
    return nuevos, actualizados, datos["fuente"]
