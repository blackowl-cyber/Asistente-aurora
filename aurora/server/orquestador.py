"""Bucle del agente: el modelo decide qué herramienta usar y Aurora la ejecuta y registra."""

import base64
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

import anthropic

from .catalogo import ESTADO_FINAL, HERRAMIENTAS_PROPIAS, HERRAMIENTAS_SERVIDOR, INSTRUCCIONES, POLITICAS
from .hub import DispositivoNoDisponible, ErrorHerramienta, Hub
from .tareas import AlmacenTareas, Estado, Tarea

log = logging.getLogger("aurora.orquestador")

BETA_RESPALDO = "server-side-fallback-2026-07-01"


class Notificador(Protocol):
    async def estado(self, tarea: Tarea, estado: Estado, detalle: str | None = None) -> None: ...
    async def confirmar(self, tarea: Tarea, descripcion: str) -> bool: ...
    async def enviar_archivo(self, tarea: Tarea, nombre: str, contenido: bytes) -> None: ...


@dataclass
class Archivo:
    ruta: str
    verificado: bool


@dataclass
class Reporte:
    estado: Estado
    resumen: str
    dispositivo: str
    archivos: list[Archivo] = field(default_factory=list)
    pendiente: str | None = None
    carpeta_trabajo: str | None = None


class Orquestador:
    def __init__(
        self,
        cliente: anthropic.AsyncAnthropic,
        hub: Hub,
        almacen: AlmacenTareas,
        modelo: str,
        esfuerzo: str = "medium",
        max_turnos: int = 40,
        espera_herramienta: float = 300,
    ):
        self.cliente = cliente
        self.hub = hub
        self.almacen = almacen
        self.modelo = modelo
        self.esfuerzo = esfuerzo
        self.max_turnos = max_turnos
        self.espera_herramienta = espera_herramienta

    async def ejecutar(self, tarea: Tarea, historial: list[dict], notificador: Notificador) -> Reporte:
        ejecucion = _Ejecucion(self, tarea, notificador)
        try:
            reporte = await ejecucion.correr(historial)
        except anthropic.RateLimitError:
            reporte = ejecucion.fallo("El servicio del modelo está saturado. Intenta de nuevo en unos minutos.")
        except anthropic.APIStatusError as e:
            log.exception("Error de la API en la tarea %s", tarea.id)
            reporte = ejecucion.fallo(f"El servicio del modelo respondió con un error ({e.status_code}).")
        except anthropic.APIConnectionError:
            reporte = ejecucion.fallo("No hubo conexión con el servicio del modelo.")
        self.almacen.cambiar_estado(tarea.id, reporte.estado, reporte.resumen)
        return reporte


class _Ejecucion:
    """Estado de una sola tarea mientras corre."""

    def __init__(self, orq: Orquestador, tarea: Tarea, notificador: Notificador):
        self.orq = orq
        self.tarea = tarea
        self.notificador = notificador
        self.estado_actual = Estado.RECIBIDA
        self.creados: dict[str, bool] = {}  # rutas confirmadas por el agente
        self.carpeta_trabajo: str | None = None
        self.final: dict | None = None

    async def correr(self, historial: list[dict]) -> Reporte:
        await self._estado(Estado.PREPARANDO)
        fecha = datetime.now().strftime("%A %d de %B de %Y, %H:%M")
        mensajes: list = list(historial) + [{
            "role": "user",
            "content": f"[Fecha y hora local del servidor: {fecha}. Dispositivo destino: {self.tarea.dispositivo}]\n\n{self.tarea.instruccion}",
        }]

        for _ in range(self.orq.max_turnos):
            respuesta = await self.orq.cliente.beta.messages.create(
                model=self.orq.modelo,
                max_tokens=16000,
                system=INSTRUCCIONES,
                tools=HERRAMIENTAS_SERVIDOR + HERRAMIENTAS_PROPIAS,
                messages=mensajes,
                thinking={"type": "adaptive"},
                output_config={"effort": self.orq.esfuerzo},
                betas=[BETA_RESPALDO],
                fallbacks="default",
            )
            if respuesta.stop_reason == "refusal":
                return self.fallo("El modelo rechazó la solicitud por sus políticas de seguridad.")
            mensajes.append({"role": "assistant", "content": respuesta.content})

            if any(b.type == "server_tool_use" for b in respuesta.content):
                await self._estado(Estado.INVESTIGANDO)
            if respuesta.stop_reason == "pause_turn":
                continue  # una búsqueda larga se pausó; se reenvía para que continúe
            if respuesta.stop_reason == "max_tokens":
                return self.fallo("La respuesta del modelo se cortó por longitud antes de terminar.")

            usos = [b for b in respuesta.content if b.type == "tool_use"]
            if not usos:
                texto = "".join(b.text for b in respuesta.content if b.type == "text").strip()
                return self._reporte_sin_finalizar(texto)

            resultados = [await self._usar(b) for b in usos]
            if self.final is not None:
                return self._reporte_final()
            mensajes.append({"role": "user", "content": resultados})

        return self.fallo(f"La tarea superó el límite de {self.orq.max_turnos} pasos sin terminar.")

    async def _usar(self, bloque) -> dict:
        nombre, args = bloque.name, dict(bloque.input or {})
        politica = POLITICAS.get(nombre)
        if politica is None:
            return _resultado(bloque.id, f"La herramienta '{nombre}' no existe.", error=True)

        if nombre == "finalizar_tarea":
            await self._estado(Estado.REVISANDO)
            self.final = args
            return _resultado(bloque.id, "Reporte recibido.")

        if politica.sensible:
            await self._estado(Estado.ESPERANDO_CONFIRMACION)
            aprobado = await self.notificador.confirmar(self.tarea, _describir(nombre, args))
            if not aprobado:
                self.orq.almacen.registrar_accion(self.tarea.id, nombre, args, False, False, "rechazada por el usuario")
                return _resultado(bloque.id, "El usuario NO autorizó esta acción. No se ejecutó.", error=True)

        await self._estado(politica.estado)
        try:
            if nombre == "enviar_al_telefono":
                datos = await self._llamar_pc("leer_para_envio", args)
                await self.notificador.enviar_archivo(
                    self.tarea, datos["nombre"], base64.b64decode(datos["contenido_b64"])
                )
                salida = {"enviado": datos["nombre"]}
            else:
                salida = await self._llamar_pc(nombre, args)
        except (DispositivoNoDisponible, ErrorHerramienta) as e:
            self.orq.almacen.registrar_accion(self.tarea.id, nombre, args, False, False, str(e))
            return _resultado(bloque.id, str(e), error=True)

        self.orq.almacen.registrar_accion(self.tarea.id, nombre, args, True, True, salida)
        if salida.get("verificado") and "ruta" in salida:
            self.creados[salida["ruta"]] = True
        if nombre == "mover_archivo" and salida.get("verificado"):
            self.creados[salida["destino"]] = True
        self.carpeta_trabajo = salida.get("carpeta_trabajo", self.carpeta_trabajo)
        return _resultado(bloque.id, salida)

    async def _llamar_pc(self, herramienta: str, args: dict) -> dict:
        return await self.orq.hub.llamar(self.tarea.dispositivo, herramienta, args, self.orq.espera_herramienta)

    async def _estado(self, estado: Estado) -> None:
        if estado != self.estado_actual:
            self.estado_actual = estado
            self.orq.almacen.cambiar_estado(self.tarea.id, estado)
            await self.notificador.estado(self.tarea, estado)

    def _reporte_final(self) -> Reporte:
        f = self.final or {}
        estado = ESTADO_FINAL.get(f.get("estado", ""), Estado.FALLIDA)
        archivos = [Archivo(r, self._confirmado(r)) for r in f.get("archivos") or []]
        if estado == Estado.COMPLETADA and any(not a.verificado for a in archivos):
            # El modelo reportó archivos que el agente no confirmó: no se presenta como éxito total.
            estado = Estado.NECESITA_INTERVENCION
        return Reporte(
            estado=estado,
            resumen=f.get("resumen", "").strip() or "Sin resumen.",
            dispositivo=self.tarea.dispositivo,
            archivos=archivos,
            pendiente=f.get("pendiente"),
            carpeta_trabajo=self.carpeta_trabajo,
        )

    def _reporte_sin_finalizar(self, texto: str) -> Reporte:
        # Respuesta conversacional sin acciones, o el modelo olvidó llamar a finalizar_tarea.
        return Reporte(
            estado=Estado.COMPLETADA,
            resumen=texto or "Listo.",
            dispositivo=self.tarea.dispositivo,
            archivos=[Archivo(r, True) for r in self.creados],
            carpeta_trabajo=self.carpeta_trabajo,
        )

    def _confirmado(self, ruta: str) -> bool:
        normal = ruta.replace("\\", "/").lstrip("./")
        return any(normal == c or normal.endswith("/" + c) or c.endswith("/" + normal) for c in self.creados)

    def fallo(self, motivo: str) -> Reporte:
        hechos = ", ".join(self.creados) if self.creados else "ningún archivo"
        return Reporte(
            estado=Estado.FALLIDA,
            resumen=f"{motivo} Alcancé a crear: {hechos}.",
            dispositivo=self.tarea.dispositivo,
            archivos=[Archivo(r, True) for r in self.creados],
            carpeta_trabajo=self.carpeta_trabajo,
        )


def _resultado(id_: str, contenido, error: bool = False) -> dict:
    texto = contenido if isinstance(contenido, str) else json.dumps(contenido, ensure_ascii=False)
    bloque = {"type": "tool_result", "tool_use_id": id_, "content": texto}
    if error:
        bloque["is_error"] = True
    return bloque


def _describir(nombre: str, args: dict) -> str:
    if nombre == "mover_archivo":
        return f"Mover «{args.get('origen')}» a «{args.get('destino')}»"
    return f"{nombre}: {args}"

