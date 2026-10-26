"""Servidor de Aurora: WebSocket para los agentes de PC + bot de Telegram en el mismo proceso."""

import hmac
import logging
from contextlib import asynccontextmanager

import anthropic
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .. import protocolo
from ..config import ServidorConfig
from .bot import BotAurora
from .hub import Hub
from .orquestador import Orquestador
from .tareas import AlmacenTareas

log = logging.getLogger("aurora.servidor")


def crear_app(config: ServidorConfig, hub: Hub | None = None, con_bot: bool = True) -> FastAPI:
    hub = hub or Hub()

    @asynccontextmanager
    async def ciclo(app: FastAPI):
        bot = None
        if con_bot:
            almacen = AlmacenTareas(config.base_datos)
            orquestador = Orquestador(
                anthropic.AsyncAnthropic(), hub, almacen, config.modelo, config.esfuerzo,
                config.max_turnos, config.espera_herramienta,
            )
            bot = BotAurora(
                config.telegram_token, config.telegram_usuarios, orquestador, almacen, hub,
                config.dispositivo, config.espera_confirmacion,
            )
            await bot.iniciar()
        yield
        if bot:
            await bot.detener()

    app = FastAPI(title="Aurora", lifespan=ciclo)
    app.state.hub = hub

    @app.get("/salud")
    async def salud() -> dict:
        return {"ok": True, "dispositivos": hub.dispositivos}

    @app.websocket("/ws/agente")
    async def agente(ws: WebSocket) -> None:
        await ws.accept()
        hola = await ws.receive_json()
        token = str(hola.get("token", ""))
        if hola.get("tipo") != protocolo.HOLA or not hmac.compare_digest(token, config.token_agente):
            log.warning("Agente rechazado: token inválido")
            await ws.close(code=protocolo.CIERRE_NO_AUTORIZADO)
            return
        dispositivo = str(hola.get("dispositivo") or "PC")
        hub.registrar(dispositivo, ws)
        await ws.send_json({"tipo": protocolo.BIENVENIDA})
        log.info("Agente conectado: %s (%s)", dispositivo, ", ".join(hola.get("herramientas", [])))
        try:
            while True:
                mensaje = await ws.receive_json()
                if mensaje.get("tipo") == protocolo.RESULTADO:
                    hub.resolver(mensaje)
        except WebSocketDisconnect:
            log.info("Agente desconectado: %s", dispositivo)
        finally:
            hub.quitar(dispositivo, ws)

    return app
