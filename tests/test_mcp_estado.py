import json
import os
import time

from app import mcp_estado, mcp_servidor
from app.ui_mcp import ACTIVO, CONECTADO, DESCONECTADO, IndicadorMcp


def test_sin_latido_no_hay_conexion(tmp_path):
    est = mcp_estado.leer(tmp_path / "quotetrack.db")
    assert est["conectado"] is False and est["servidores"] == 0 and est["ultima_escritura"] == 0.0


def test_latido_marca_conectado_y_al_detener_desaparece(tmp_path):
    base = tmp_path / "quotetrack.db"
    latido = mcp_estado.Latido(base, escritura=True, intervalo=0.05)
    latido.iniciar()
    try:
        est = mcp_estado.leer(base)
        assert est["conectado"] and est["escritura"] and est["servidores"] == 1
        antes = json.loads(latido.ruta.read_text())["latido"]
        time.sleep(0.2)
        assert json.loads(latido.ruta.read_text())["latido"] > antes          # el hilo renueva el latido
    finally:
        latido.detener()
    assert not latido.ruta.exists() and mcp_estado.leer(base)["conectado"] is False


def test_un_latido_viejo_ya_no_cuenta_y_se_limpia(tmp_path):
    base = tmp_path / "quotetrack.db"
    latido = mcp_estado.Latido(base, escritura=False)
    latido.escribir()
    assert mcp_estado.leer(base)["conectado"]
    assert mcp_estado.leer(base, ahora=time.time() + mcp_estado.CADUCIDAD + 1)["conectado"] is False
    assert latido.ruta.exists()                                                # aún reciente para la limpieza
    mcp_estado.leer(base, ahora=time.time() + mcp_estado.CADUCIDAD * 7)
    assert not latido.ruta.exists()                                            # muy viejo: se borra


def test_varios_servidores_y_archivo_corrupto(tmp_path):
    base = tmp_path / "quotetrack.db"
    carpeta = mcp_estado.carpeta_estado(base)
    carpeta.mkdir()
    ahora = time.time()
    (carpeta / "1.json").write_text(json.dumps({"latido": ahora, "escritura": False, "actividad": 5, "ultima_escritura": 0}))
    (carpeta / "2.json").write_text(json.dumps({"latido": ahora, "escritura": True, "actividad": 9,
                                                "ultima_escritura": 8, "herramienta": "crear_cotizacion"}))
    (carpeta / "3.json").write_text("{no es json")
    est = mcp_estado.leer(base, ahora)
    assert est["servidores"] == 2 and est["escritura"] and est["ultima_escritura"] == 8
    assert est["herramienta"] == "crear_cotizacion"


def test_el_servidor_registra_actividad_y_escrituras(conn, tmp_path):
    from app import db
    latido = mcp_estado.Latido(db.DB_PATH, escritura=True)
    s = mcp_servidor.Servidor(True, latido)
    s.atender({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "estadisticas", "arguments": {}}})
    d = json.loads(latido.ruta.read_text())
    assert d["herramienta"] == "estadisticas" and d["actividad"] > 0 and d["ultima_escritura"] == 0
    s.atender({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
               "params": {"name": "crear_cliente", "arguments": {"nombre": "NUEVO SA"}}})
    d = json.loads(latido.ruta.read_text())
    assert d["herramienta"] == "crear_cliente" and d["ultima_escritura"] >= d["actividad"] - 1e-6 > 0
    latido.detener()


def test_un_error_de_herramienta_no_cuenta_como_actividad(conn):
    from app import db
    latido = mcp_estado.Latido(db.DB_PATH, escritura=False)
    s = mcp_servidor.Servidor(False, latido)
    s.atender({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "crear_cliente", "arguments": {}}})
    assert not latido.ruta.exists() or json.loads(latido.ruta.read_text())["actividad"] == 0
    latido.detener()


def test_indicador_desconectado_conectado_y_activo(qapp, tmp_path):
    ind = IndicadorMcp(db_path=tmp_path / "quotetrack.db", intervalo_ms=10_000)
    assert not ind.conectado and ind.texto == DESCONECTADO[1]
    ahora = time.time()
    ind.actualizar(ahora, {"conectado": True, "escritura": True, "actividad": ahora - 60, "ultima_escritura": 0})
    assert ind.conectado and ind.texto == CONECTADO[1] and "puede crear y modificar" in ind.toolTip()
    ind.actualizar(ahora, {"conectado": True, "escritura": False, "actividad": ahora - 1, "ultima_escritura": 0,
                           "herramienta": "listar_cotizaciones"})
    assert ind.texto == ACTIVO[1] and "solo lectura" in ind.toolTip() and "listar_cotizaciones" in ind.toolTip()
    ind.actualizar(ahora, {"conectado": False})
    assert ind.texto == DESCONECTADO[1]


def test_indicador_emite_al_modificar_datos_pero_no_por_lo_anterior(qapp, tmp_path):
    # un MCP que ya estaba conectado, con una escritura anterior, antes de abrir la aplicación
    carpeta = mcp_estado.carpeta_estado(tmp_path / "quotetrack.db")
    carpeta.mkdir()
    (carpeta / "7.json").write_text(json.dumps({"latido": time.time(), "escritura": True, "actividad": 50,
                                                "ultima_escritura": 50}))
    ind = IndicadorMcp(db_path=tmp_path / "quotetrack.db", intervalo_ms=10_000)
    assert ind.conectado
    avisos = []
    ind.datos_modificados.connect(lambda: avisos.append(1))
    base = {"conectado": True, "escritura": True, "actividad": 0}
    ind.actualizar(101, {**base, "ultima_escritura": 50})      # lo ya escrito antes de abrir la app no refresca
    assert avisos == []
    ind.actualizar(102, {**base, "ultima_escritura": 99})      # una escritura nueva
    ind.actualizar(103, {**base, "ultima_escritura": 99})
    assert avisos == [1]


def test_ventana_principal_muestra_el_indicador(qapp, conn):
    from app.ui_main import MainWindow
    w = MainWindow()
    assert w.indicador_mcp.texto == DESCONECTADO[1]
    llamado = []
    w._refrescar_actual = lambda: llamado.append(1)
    w.indicador_mcp.datos_modificados.disconnect()
    w.indicador_mcp.datos_modificados.connect(w._refrescar_actual)
    w.indicador_mcp.actualizar(1, {"conectado": True, "escritura": True, "actividad": 0, "ultima_escritura": 0})
    w.indicador_mcp.actualizar(2, {"conectado": True, "escritura": True, "actividad": 0, "ultima_escritura": 2})
    assert llamado == [1]
    w.close()


def test_main_del_mcp_crea_y_borra_su_latido(tmp_path, conn, monkeypatch):
    """`main` con una base real arranca el latido y lo retira al cerrarse la entrada estándar."""
    import io
    from app import db
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"))
    salida = io.StringIO()
    monkeypatch.setattr("sys.stdout", salida)
    monkeypatch.setattr(mcp_servidor.Servidor, "servir", lambda self, e=None, s=None: (
        mcp_estado.leer(db.DB_PATH)["conectado"] and salida.write("conectado\n")))
    assert mcp_servidor.main(["--db", str(db.DB_PATH), "--escritura"]) == 0
    assert "conectado" in salida.getvalue()
    assert mcp_estado.leer(db.DB_PATH)["conectado"] is False                  # se retiró al terminar
