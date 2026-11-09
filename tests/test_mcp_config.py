import io
import json
import sys

import pytest

from app import mcp_config, mcp_servidor
from app.ui_mcp import ConexionMcpDialog


@pytest.fixture
def config(tmp_path, monkeypatch):
    """Configuración de Claude con otro servidor ya registrado (que no debe tocarse)."""
    ruta = tmp_path / "Claude" / mcp_config.ARCHIVO
    ruta.parent.mkdir()
    ruta.write_text(json.dumps({"mcpServers": {"revit-mcp": {"command": "node", "args": ["x.js"]}},
                                "otraClave": {"a": 1}}), encoding="utf-8")
    monkeypatch.setattr(mcp_config, "comando_mcp",
                        lambda esc: (r"D:\apps\QuoteTrackMCP.exe", ["--escritura"] if esc else []))
    return ruta


def leer(ruta):
    return json.loads(ruta.read_text(encoding="utf-8"))


def test_activar_agrega_solo_quotetrack_y_conserva_el_resto(config):
    mcp_config.activar(config, escritura=True)
    d = leer(config)
    assert d["mcpServers"]["quotetrack"] == {"command": r"D:\apps\QuoteTrackMCP.exe", "args": ["--escritura"]}
    assert d["mcpServers"]["revit-mcp"] == {"command": "node", "args": ["x.js"]} and d["otraClave"] == {"a": 1}
    assert not config.read_bytes().startswith(b"\xef\xbb\xbf")                    # UTF-8 sin BOM


def test_respaldo_solo_la_primera_vez_con_la_configuracion_original(config):
    original = config.read_text(encoding="utf-8")
    mcp_config.activar(config, False)
    respaldo = config.with_name(config.name + mcp_config.RESPALDO)
    assert respaldo.read_text(encoding="utf-8") == original
    mcp_config.activar(config, True)
    assert respaldo.read_text(encoding="utf-8") == original                       # no se pisa


def test_estado_y_cambio_de_modo(config):
    assert mcp_config.estado(config)["activo"] is False
    mcp_config.activar(config, False)
    e = mcp_config.estado(config)
    assert e["activo"] and not e["escritura"] and e["coincide"]
    mcp_config.activar(config, True)
    assert mcp_config.estado(config)["escritura"]


def test_estado_detecta_que_apunta_a_otra_copia(config):
    d = leer(config)
    d["mcpServers"]["quotetrack"] = {"command": r"C:\viejo\QuoteTrackMCP.exe", "args": []}
    config.write_text(json.dumps(d), encoding="utf-8")
    e = mcp_config.estado(config)
    assert e["activo"] and not e["coincide"] and e["comando"].endswith("QuoteTrackMCP.exe")


def test_desactivar_quita_solo_quotetrack(config):
    mcp_config.activar(config, True)
    assert mcp_config.desactivar(config) is True
    assert list(leer(config)["mcpServers"]) == ["revit-mcp"]
    assert mcp_config.desactivar(config) is False


def test_crea_el_archivo_si_no_existe(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_config, "comando_mcp", lambda esc: ("mcp.exe", []))
    ruta = tmp_path / "nueva" / "Claude" / mcp_config.ARCHIVO
    mcp_config.activar(ruta, False)
    assert leer(ruta) == {"mcpServers": {"quotetrack": {"command": "mcp.exe", "args": []}}}


def test_un_json_danado_no_se_toca(config):
    config.write_text("{esto no es json", encoding="utf-8")
    with pytest.raises(mcp_config.ErrorConfig):
        mcp_config.activar(config, True)
    assert config.read_text(encoding="utf-8") == "{esto no es json"


def test_tolera_bom_y_archivo_vacio(config):
    config.write_bytes(b"\xef\xbb\xbf" + json.dumps({"mcpServers": {}}).encode())
    mcp_config.activar(config, False)
    assert "quotetrack" in leer(config)["mcpServers"]
    config.write_text("", encoding="utf-8")
    mcp_config.activar(config, False)
    assert "quotetrack" in leer(config)["mcpServers"]


def test_rutas_msix_y_clasica(tmp_path, monkeypatch):
    local, roaming = tmp_path / "Local", tmp_path / "Roaming"
    msix = local / "Packages" / "Claude_abc" / "LocalCache" / "Roaming" / "Claude"
    msix.mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(roaming))
    assert mcp_config.rutas_config() == [msix / mcp_config.ARCHIVO, roaming / "Claude" / mcp_config.ARCHIVO]
    assert mcp_config.rutas_destino() == [msix / mcp_config.ARCHIVO]               # solo la carpeta que existe
    (msix / mcp_config.ARCHIVO).write_text("{}")
    (roaming / "Claude").mkdir(parents=True)
    (roaming / "Claude" / mcp_config.ARCHIVO).write_text("{}")
    assert len(mcp_config.rutas_destino()) == 2                                    # existen ambos: se aplican a ambos
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "nada"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "nada2"))
    assert mcp_config.rutas_destino() == [tmp_path / "nada2" / "Claude" / mcp_config.ARCHIVO]


def test_ruta_de_datos_fuera_del_paquete_va_primero(tmp_path, monkeypatch):
    local, roaming = tmp_path / "Local", tmp_path / "Roaming"
    datos = local / "Claude-Data" / "claude_abc"
    msix = local / "Packages" / "Claude_abc" / "LocalCache" / "Roaming" / "Claude"
    datos.mkdir(parents=True)
    msix.mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(roaming))
    assert mcp_config.rutas_config()[0] == datos / mcp_config.ARCHIVO
    (datos / mcp_config.ARCHIVO).write_text("{}")
    assert mcp_config.rutas_destino() == [datos / mcp_config.ARCHIVO]              # solo el que existe


def test_comando_en_ejecutable_y_en_desarrollo(tmp_path, monkeypatch):
    exe = tmp_path / "QuoteTrack.exe"
    exe.write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    with pytest.raises(mcp_config.ErrorConfig):                                    # sin QuoteTrackMCP.exe al lado
        mcp_config.comando_mcp(True)
    (tmp_path / "QuoteTrackMCP.exe").write_text("")
    cmd, args = mcp_config.comando_mcp(True)
    assert cmd.endswith("QuoteTrackMCP.exe") and args == ["--escritura"]
    assert mcp_config.comando_mcp(False)[1] == []
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    cmd, args = mcp_config.comando_mcp(True)
    assert cmd == sys.executable and args[0].endswith("quotetrack_mcp.py") and args[-1] == "--escritura"
    assert json.loads(mcp_config.fragmento_json(False))["quotetrack"]["command"] == sys.executable


# ----------------------------------------------------------------------------- diálogo
def test_dialogo_activa_cambia_de_modo_y_desactiva(qapp, config, tmp_path):
    dlg = ConexionMcpDialog(rutas=[config], db_path=tmp_path / "quotetrack.db")
    assert "desactivado" in dlg.lbl_estado.text() and not dlg.btn_desactivar.isEnabled()
    assert dlg.btn_activar.text() == "Activar MCP"
    dlg.btn_activar.click()
    assert mcp_config.estado(config)["escritura"] and "activado" in dlg.lbl_estado.text()
    assert dlg.btn_activar.text() == "Aplicar cambios" and dlg.btn_desactivar.isEnabled()
    assert "Cierra Claude Desktop" in dlg.lbl_resultado.text()
    dlg.chk_escritura.setChecked(False)
    dlg.btn_activar.click()
    assert not mcp_config.estado(config)["escritura"] and "solo lectura" in dlg.lbl_estado.text()
    dlg.btn_desactivar.click()
    assert not mcp_config.estado(config)["activo"] and "desactivado" in dlg.lbl_estado.text()


def test_dialogo_propone_reparar_si_apunta_a_otra_copia(qapp, config, tmp_path):
    d = leer(config)
    d["mcpServers"]["quotetrack"] = {"command": r"C:\viejo\QuoteTrackMCP.exe", "args": []}
    config.write_text(json.dumps(d), encoding="utf-8")
    dlg = ConexionMcpDialog(rutas=[config], db_path=tmp_path / "quotetrack.db")
    assert dlg.btn_activar.text() == "Reparar" and "otra copia" in dlg.lbl_estado.text()
    dlg.btn_activar.click()
    assert mcp_config.estado(config)["coincide"]


def test_dialogo_con_config_danada_no_escribe_nada(qapp, config, tmp_path):
    config.write_text("{roto", encoding="utf-8")
    dlg = ConexionMcpDialog(rutas=[config], db_path=tmp_path / "quotetrack.db")
    assert "No pude leer" in dlg.lbl_estado.text() and not dlg.btn_activar.isEnabled()
    assert config.read_text(encoding="utf-8") == "{roto"


def test_dialogo_copia_la_configuracion(qapp, config, tmp_path):
    from PySide6.QtWidgets import QApplication
    dlg = ConexionMcpDialog(rutas=[config], db_path=tmp_path / "quotetrack.db")
    dlg.btn_copiar.click()
    assert json.loads(QApplication.clipboard().text())["quotetrack"]["args"] == ["--escritura"]


def test_indicador_y_configuracion_abren_el_dialogo(qapp, conn, monkeypatch):
    from app import ui_main
    from app.ui_main import MainWindow
    abiertos = []
    monkeypatch.setattr(ui_main.ConexionMcpDialog, "exec", lambda self: abiertos.append(self))
    w = MainWindow()
    w.indicador_mcp.clic.emit()
    w.configuracion_tab.btn_mcp.click()
    assert len(abiertos) == 2
    assert "Clic para activar" in w.indicador_mcp.toolTip()
    w.indicador_mcp.actualizar(1, {"conectado": False})
    assert w.indicador_mcp.toolTip().count("Clic para activar") == 1               # el aviso no se acumula
    w.close()


# ----------------------------------------------------------------------------- ejecutable sin consola
def test_flujos_ausentes_se_enlazan_a_los_descriptores_o_a_devnull(monkeypatch):
    for nombre in ("stdin", "stdout", "stderr"):
        monkeypatch.setattr(sys, nombre, None)
    abiertos = []

    def abrir_ok(destino, modo, **k):                      # hay tuberías heredadas de Claude Desktop
        abiertos.append(destino)
        return io.StringIO()

    monkeypatch.setattr(mcp_servidor, "open", abrir_ok, raising=False)
    mcp_servidor._asegurar_flujos()
    assert abiertos == [0, 1, 2] and sys.stdin is not None and sys.stdout is not None and sys.stderr is not None

    for nombre in ("stdin", "stdout", "stderr"):
        monkeypatch.setattr(sys, nombre, None)

    def abrir_sin_tuberias(destino, modo, **k):            # doble clic en el .exe: no hay descriptores válidos
        if isinstance(destino, int):
            raise OSError("descriptor no válido")
        return io.StringIO()

    monkeypatch.setattr(mcp_servidor, "open", abrir_sin_tuberias, raising=False)
    mcp_servidor._asegurar_flujos()
    assert sys.stdin.read() == "" and sys.stdout is not None                      # EOF inmediato: el servidor termina


def test_servir_con_stdin_vacio_termina_sin_colgarse(monkeypatch):
    mcp_servidor.Servidor(False).servir(io.StringIO(""), io.StringIO())           # no bloquea ni lanza
