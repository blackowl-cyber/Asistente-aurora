"""Registro de los agentes de PC conectados y llamadas remotas a sus herramientas."""

import asyncio
import uuid
from typing import Protocol

from .. import protocolo


class Conexion(Protocol):
    async def send_json(self, datos: dict) -> None: ...


class DispositivoNoDisponible(RuntimeError):
    pass


class ErrorHerramienta(RuntimeError):
    pass


class Hub:
    def __init__(self) -> None:
        self._conexiones: dict[str, Conexion] = {}
        self._pendientes: dict[str, asyncio.Future] = {}

    @property
    def dispositivos(self) -> list[str]:
        return sorted(self._conexiones)

    def en_linea(self, dispositivo: str) -> bool:
        return dispositivo in self._conexiones

    def registrar(self, dispositivo: str, conexion: Conexion) -> None:
        self._conexiones[dispositivo] = conexion

    def quitar(self, dispositivo: str, conexion: Conexion) -> None:
        if self._conexiones.get(dispositivo) is conexion:
            del self._conexiones[dispositivo]
        # Las llamadas en curso a ese dispositivo ya no van a responder.
        for id_, futuro in list(self._pendientes.items()):
            if getattr(futuro, "dispositivo", None) == dispositivo and not futuro.done():
                futuro.set_exception(DispositivoNoDisponible(f"'{dispositivo}' se desconectó a mitad de la tarea."))

    def resolver(self, mensaje: dict) -> None:
        futuro = self._pendientes.pop(mensaje.get("id", ""), None)
        if futuro is None or futuro.done():
            return
        if mensaje.get("ok"):
            futuro.set_result(mensaje.get("resultado") or {})
        else:
            futuro.set_exception(ErrorHerramienta(mensaje.get("error") or "Error desconocido."))

    async def llamar(self, dispositivo: str, herramienta: str, argumentos: dict, espera: float) -> dict:
        conexion = self._conexiones.get(dispositivo)
        if conexion is None:
            raise DispositivoNoDisponible(
                f"El dispositivo '{dispositivo}' no está conectado (¿está apagado o sin internet?)."
            )
        id_ = uuid.uuid4().hex
        futuro = asyncio.get_running_loop().create_future()
        futuro.dispositivo = dispositivo  # type: ignore[attr-defined]
        self._pendientes[id_] = futuro
        try:
            await conexion.send_json(protocolo.llamada(id_, herramienta, argumentos))
            return await asyncio.wait_for(futuro, timeout=espera)
        except asyncio.TimeoutError:
            raise ErrorHerramienta(f"'{herramienta}' no respondió en {int(espera)} s.") from None
        finally:
            self._pendientes.pop(id_, None)
