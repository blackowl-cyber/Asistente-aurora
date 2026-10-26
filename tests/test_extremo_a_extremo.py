"""Servidor real por WebSocket + agente real: el protocolo funciona de punta a punta."""

import asyncio
import socket

import pytest
import uvicorn
import websockets

from aurora.agent.herramientas import Herramientas
from aurora.agent.main import sesion
from aurora.agent.sandbox import Sandbox
from aurora.config import AgenteConfig, ServidorConfig
from aurora.server.app import crear_app
from aurora.server.bot import formatear_reporte
from aurora.server.hub import ErrorHerramienta, Hub
from aurora.server.orquestador import Archivo, Reporte
from aurora.server.tareas import Estado, Tarea

TOKEN = "token-de-prueba-suficientemente-largo"


def puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def servidor():
    puerto = puerto_libre()
    config = ServidorConfig(telegram_token="x", telegram_usuarios="1", token_agente=TOKEN, _env_file=None)
    hub = Hub()
    srv = uvicorn.Server(uvicorn.Config(crear_app(config, hub, con_bot=False), port=puerto, log_level="warning"))
    tarea = asyncio.create_task(srv.serve())
    while not srv.started:
        await asyncio.sleep(0.05)
    yield hub, f"ws://127.0.0.1:{puerto}/ws/agente"
    srv.should_exit = True
    await tarea


async def test_agente_crea_documento_por_websocket(servidor, tmp_path):
    hub, url = servidor
    config = AgenteConfig(servidor_url=url, token_agente=TOKEN, dispositivo="PC", carpeta_trabajo=tmp_path, _env_file=None)
    herramientas = Herramientas(Sandbox(config.carpeta_trabajo))
    agente = asyncio.create_task(sesion(config, herramientas))
    for _ in range(100):
        if hub.en_linea("PC"):
            break
        await asyncio.sleep(0.05)
    assert hub.en_linea("PC")

    r = await hub.llamar("PC", "crear_documento", {
        "ruta": "Proyectos/E2E/doc.docx", "titulo": "Hola", "bloques": [{"tipo": "parrafo", "texto": "x"}],
    }, espera=10)
    assert r["verificado"] and (tmp_path / "Proyectos/E2E/doc.docx").exists()

    with pytest.raises(ErrorHerramienta, match="fuera de la carpeta"):
        await hub.llamar("PC", "crear_carpeta", {"ruta": "../escape"}, espera=10)

    agente.cancel()
    for _ in range(100):
        if not hub.en_linea("PC"):
            break
        await asyncio.sleep(0.05)
    assert not hub.en_linea("PC")


async def test_token_invalido_es_rechazado(servidor):
    hub, url = servidor
    async with websockets.connect(url) as ws:
        await ws.send('{"tipo": "hola", "token": "malo", "dispositivo": "PC"}')
        with pytest.raises(websockets.ConnectionClosed) as e:
            await ws.recv()
    assert e.value.rcvd.code == 4401
    assert not hub.en_linea("PC")


def test_config_lee_varios_usuarios():
    c = ServidorConfig(telegram_token="x", telegram_usuarios="11, 22", token_agente=TOKEN, _env_file=None)
    assert c.telegram_usuarios == [11, 22]


def test_formato_del_reporte_escapa_html():
    tarea = Tarea(7, 1, "x", "PC", Estado.COMPLETADA, None, "")
    r = Reporte(Estado.COMPLETADA, "Precio <bajo> & bueno", "PC",
                [Archivo("Proyectos/a.xlsx", True), Archivo("b.docx", False)], "Elegir proveedor", "C:/Aurora")
    texto = formatear_reporte(tarea, r)
    assert "Precio &lt;bajo&gt; &amp; bueno" in texto
    assert "Proyectos/a.xlsx</code> ✓" in texto and "(sin confirmar)" in texto
    assert "Trabajo completado" in texto and "Elegir proveedor" in texto
