import json
import subprocess
import sys
from pathlib import Path

import pytest

from app import db, mcp_servidor
from app.calculo import Cargo, Linea

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture
def datos(conn):
    """Base con ACME (cotización 1 borrador con un ítem), una cotización aprobada y su factura pagada."""
    db.guardar_cotizacion(1, [Linea("item", 0, "Diseño estructural", 1, 1000.0, True, "gl", titulo="Diseño")],
                          [Cargo("Administración", "porcentaje", 10)], conn, tasa=0.07)
    cid, _ = db.crear_cotizacion(db.guardar_cliente({"nombre": "BETA SA", "identificacion": "1-2-3"}, conn), conn)
    db.guardar_cotizacion(cid, [Linea("item", 0, "Planos", 2, 250.0, True, "u")], [], conn, tasa=0.0)
    db.cambiar_estado_cotizacion(cid, "enviada", conn)
    db.cambiar_estado_cotizacion(cid, "aprobada", conn)
    db.generar_factura(cid, conn, porcentaje=40)
    return conn


def llamar(escritura, herramienta, /, **args):
    r = mcp_servidor.Servidor(escritura).atender(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": herramienta, "arguments": args}})["result"]
    texto = r["content"][0]["text"]
    return r["isError"], (texto if r["isError"] else json.loads(texto))


def test_protocolo_basico():
    s = mcp_servidor.Servidor()
    r = s.atender({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}})
    assert r["result"]["protocolVersion"] == "2025-03-26" and r["result"]["serverInfo"]["name"] == "quotetrack"
    assert s.atender({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert s.atender({"jsonrpc": "2.0", "id": 2, "method": "ping"})["result"] == {}
    assert s.atender({"jsonrpc": "2.0", "id": 3, "method": "nada"})["error"]["code"] == -32601


def test_lista_solo_herramientas_de_lectura_por_defecto():
    lectura = {t["name"] for t in mcp_servidor.Servidor(False).listar()}
    todas = {t["name"] for t in mcp_servidor.Servidor(True).listar()}
    assert {"estadisticas", "listar_cotizaciones", "obtener_cotizacion", "resumen_cotizacion"} <= lectura
    assert not lectura & {"crear_cotizacion", "generar_factura", "marcar_factura_pagada", "crear_cliente"}
    assert {"crear_cotizacion", "generar_factura", "marcar_factura_pagada"} <= todas
    assert all(t["inputSchema"]["type"] == "object" for t in mcp_servidor.Servidor(True).listar())


def test_lectura(datos):
    error, est = llamar(False, "estadisticas")
    assert not error and est["clientes"] == 2 and est["facturas_por_estado"]["pendiente"]["total"] == 200.0
    assert est["por_cobrar"] == 200.0 and est["cotizaciones_por_estado"]["aprobada"]["cantidad"] == 1
    _, lista = llamar(False, "listar_cotizaciones", cliente="beta")
    assert [c["numero"] for c in lista] == ["COT-2026-0002"] or lista[0]["cliente"] == "BETA SA"
    _, det = llamar(False, "obtener_cotizacion", numero="COT-2026-0001")
    assert det["cliente"] == "ACME" and det["items"][0]["titulo"] == "Diseño"
    assert det["totales"]["total"] == 1177.0 and det["costos_adicionales"][0]["monto"] == 100.0
    _, res = llamar(False, "resumen_cotizacion", numero="COT-2026-0001")
    assert res[-1]["concepto"] == "TOTAL" and res[-1]["monto"] == 1177.0
    _, facs = llamar(False, "listar_facturas", estado="pendiente")
    assert len(facs) == 1 and facs[0]["concepto"].startswith("Abono")
    _, fac = llamar(False, "obtener_factura", numero=facs[0]["numero"])
    assert fac["cotizacion"] == "COT-2026-0002" and fac["cliente"]["nombre"] == "BETA SA"
    _, clientes = llamar(False, "listar_clientes", buscar="1-2-3")
    assert [c["nombre"] for c in clientes] == ["BETA SA"]


def test_errores_claros(datos):
    assert llamar(False, "obtener_cotizacion", numero="COT-9999")[0]
    assert "solo lectura" in llamar(False, "crear_cliente", nombre="X")[1]
    assert llamar(False, "inexistente")[0]


def test_pdf(datos, tmp_path):
    _, r = llamar(False, "exportar_pdf", numero="COT-2026-0001", carpeta=str(tmp_path))
    assert Path(r["archivo"]).read_bytes()[:4] == b"%PDF"
    _, r = llamar(False, "exportar_pdf", numero="FAC-2026-0001", carpeta=str(tmp_path))
    assert Path(r["archivo"]).name == "FAC-2026-0001.pdf" and Path(r["archivo"]).exists()


def test_escritura(datos):
    assert not llamar(True, "crear_cliente", nombre="GAMMA SA", identificacion="9-9-9")[0]
    error, nueva = llamar(True, "crear_cotizacion", cliente="gamma", proyecto="Torre", lineas=[
        {"titulo": "Estructura", "descripcion": "Diseño completo", "cantidad": 1, "precio": 2000},
        {"descripcion": "Planos", "cantidad": 4, "precio": 100, "unidad": "u"}],
        cargos=[{"concepto": "Utilidad", "tipo": "porcentaje", "valor": 10, "diluir": True}])
    assert not error and nueva["estado"] == "borrador" and nueva["total"] == 2824.8       # (2,400 + 10% diluido = 2,640) + ITBMS 7%
    num = nueva["numero"]
    assert llamar(True, "cambiar_estado_cotizacion", numero=num, estado="aprobada")[0]   # no se salta «enviada»
    assert not llamar(True, "cambiar_estado_cotizacion", numero=num, estado="enviada")[0]
    assert not llamar(True, "cambiar_estado_cotizacion", numero=num, estado="aprobada")[0]
    _, f1 = llamar(True, "generar_factura", cotizacion=num, porcentaje=50)
    assert f1["total"] == 1412.4 and f1["saldo_por_facturar"] == 1412.4
    _, f2 = llamar(True, "generar_factura", cotizacion=num)
    assert f2["concepto"] == "Saldo final"
    assert llamar(True, "generar_factura", cotizacion=num)[0]                             # ya no hay saldo
    _, pagada = llamar(True, "marcar_factura_pagada", numero=f1["numero"], fecha_pago="2026-03-01")
    assert pagada["estado"] == "pagada"
    assert llamar(True, "marcar_factura_pagada", numero=f1["numero"], fecha_pago="mañana")[0]
    _, det = llamar(False, "obtener_factura", numero=f1["numero"])
    assert det["estado"] == "pagada" and det["fecha_pago"] == "2026-03-01"


def test_cliente_ambiguo_o_inexistente(datos):
    db.guardar_cliente({"nombre": "ACME NORTE"}, datos)
    assert "varios clientes" in llamar(True, "crear_cotizacion", cliente="acm", lineas=[{"descripcion": "x", "precio": 1}])[1]
    assert "No existe" in llamar(True, "crear_cotizacion", cliente="zzz", lineas=[{"descripcion": "x", "precio": 1}])[1]
    assert not llamar(True, "crear_cotizacion", cliente="acme", lineas=[{"descripcion": "x", "precio": 1}])[0]   # el nombre exacto gana
    assert llamar(True, "crear_cotizacion", cliente="ACME", lineas=[])[0]


def test_servidor_por_la_entrada_estandar(tmp_path, datos):
    """Arranca el servidor como lo hará Claude Desktop: proceso aparte, JSON por líneas, base de datos indicada."""
    mensajes = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "estadisticas", "arguments": {}}},
    ]
    entrada = "\n".join(json.dumps(m) for m in mensajes) + "\n"
    p = subprocess.run([sys.executable, "-m", "app.mcp_servidor", "--db", str(db.DB_PATH)], input=entrada,
                       capture_output=True, text=True, cwd=RAIZ, timeout=60, encoding="utf-8")
    respuestas = [json.loads(l) for l in p.stdout.splitlines()]
    assert [r["id"] for r in respuestas] == [1, 2, 3]
    assert respuestas[0]["result"]["serverInfo"]["name"] == "quotetrack"
    assert "estadisticas" in [t["name"] for t in respuestas[1]["result"]["tools"]]
    assert json.loads(respuestas[2]["result"]["content"][0]["text"])["clientes"] == 2
    assert "solo lectura" in p.stderr


def test_sin_base_de_datos(tmp_path):
    p = subprocess.run([sys.executable, "-m", "app.mcp_servidor", "--db", str(tmp_path / "no_existe.db")],
                       input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                         "params": {"name": "estadisticas", "arguments": {}}}) + "\n",
                       capture_output=True, text=True, cwd=RAIZ, timeout=60, encoding="utf-8")
    r = json.loads(p.stdout.splitlines()[0])["result"]
    assert r["isError"] and "No se encontró la base de datos" in r["content"][0]["text"]
    assert not (tmp_path / "no_existe.db").exists()          # no crea una base vacía
