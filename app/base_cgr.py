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
    """Importa la base en su propia biblioteca. Devuelve (nuevas, actualizadas, fuente); es idempotente."""
    datos = cargar()
    nuevos, actualizados = db.importar_conceptos(datos["conceptos"], datos["fuente"], conn)
    return nuevos, actualizados, datos["fuente"]


def precargar(conn) -> bool:
    """Deja cargada la base de la Contraloría como una biblioteca más la primera vez que se abre la app.
    Solo se hace una vez: si después el usuario la elimina, no se vuelve a cargar. Devuelve True si la cargó."""
    if db.obtener_config("base_cgr_precargada", conn):
        return False
    ya_existe = conn.execute("SELECT 1 FROM bibliotecas WHERE nombre = ?", (cargar()["fuente"],)).fetchone()
    cargada = False
    if not ya_existe:
        importar(conn)
        cargada = True
    db.guardar_config("base_cgr_precargada", "1", conn)
    return cargada
