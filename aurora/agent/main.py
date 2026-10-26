"""Agente de PC: se conecta al servidor de Aurora y ejecuta las herramientas que le pide.

La conexión siempre sale de la PC hacia el servidor, así que no hace falta abrir puertos.
"""

import asyncio
import json
import logging

import websockets

from .. import protocolo
from ..config import AgenteConfig
from .herramientas import Herramientas
from .sandbox import RutaNoPermitida, Sandbox
from .subapps.comun import ErrorSubApp

log = logging.getLogger("aurora.agente")


async def atender_llamada(herramientas: Herramientas, mensaje: dict) -> dict:
    id_ = mensaje["id"]
    nombre = mensaje.get("herramienta", "")
    try:
        resultado = await asyncio.to_thread(herramientas.ejecutar, nombre, mensaje.get("argumentos") or {})
        log.info("OK %s", nombre)
        return protocolo.resultado_ok(id_, resultado)
    except (ErrorSubApp, RutaNoPermitida, ValueError) as e:
        log.warning("Error en %s: %s", nombre, e)
        return protocolo.resultado_error(id_, str(e))
    except KeyError as e:
        return protocolo.resultado_error(id_, f"Falta el argumento {e}.")
    except Exception as e:  # el agente nunca debe caerse por una herramienta
        log.exception("Fallo inesperado en %s", nombre)
        return protocolo.resultado_error(id_, f"Fallo inesperado: {type(e).__name__}: {e}")


async def sesion(config: AgenteConfig, herramientas: Herramientas) -> None:
    async with websockets.connect(config.servidor_url, max_size=64 * 1024 * 1024) as ws:
        await ws.send(json.dumps({
            "tipo": protocolo.HOLA,
            "token": config.token_agente,
            "dispositivo": config.dispositivo,
            "herramientas": herramientas.nombres,
        }))
        bienvenida = json.loads(await ws.recv())
        if bienvenida.get("tipo") != protocolo.BIENVENIDA:
            raise RuntimeError(f"Respuesta inesperada del servidor: {bienvenida}")
        log.info("Conectado como '%s'. Carpeta de trabajo: %s", config.dispositivo, herramientas.sb.raiz)

        pendientes: set[asyncio.Task] = set()

        async def responder(mensaje: dict) -> None:
            await ws.send(json.dumps(await atender_llamada(herramientas, mensaje)))

        async for crudo in ws:
            mensaje = json.loads(crudo)
            if mensaje.get("tipo") == protocolo.LLAMADA:
                tarea = asyncio.create_task(responder(mensaje))
                pendientes.add(tarea)
                tarea.add_done_callback(pendientes.discard)


async def ejecutar(config: AgenteConfig) -> None:
    herramientas = Herramientas(Sandbox(config.carpeta_trabajo))
    espera = 2
    while True:
        try:
            await sesion(config, herramientas)
            espera = 2
        except websockets.ConnectionClosedError as e:
            if e.rcvd and e.rcvd.code == protocolo.CIERRE_NO_AUTORIZADO:
                log.error("El servidor rechazó el token del agente. Revisa AURORA_TOKEN_AGENTE.")
                return
            log.warning("Conexión cerrada: %s", e)
        except (OSError, websockets.WebSocketException) as e:
            log.warning("No se pudo conectar con %s: %s", config.servidor_url, e)
        log.info("Reintentando en %s s", espera)
        await asyncio.sleep(espera)
        espera = min(espera * 2, 60)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(ejecutar(AgenteConfig()))


if __name__ == "__main__":
    main()
