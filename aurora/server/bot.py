"""Bot de Telegram: recibe órdenes desde el teléfono, muestra el estado real y avisa al terminar."""

import asyncio
import html
import logging
import uuid
from collections import defaultdict

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from .hub import Hub
from .orquestador import Orquestador, Reporte
from .tareas import AlmacenTareas, Estado, Tarea

log = logging.getLogger("aurora.bot")

MAX_HISTORIAL = 12  # mensajes (6 intercambios) que se recuerdan por chat
ICONOS = {
    Estado.COMPLETADA: "✅",
    Estado.NECESITA_INTERVENCION: "⚠️",
    Estado.FALLIDA: "❌",
    Estado.CANCELADA: "⏹",
}


class BotAurora:
    def __init__(
        self,
        token: str,
        usuarios: list[int],
        orquestador: Orquestador,
        almacen: AlmacenTareas,
        hub: Hub,
        dispositivo: str,
        espera_confirmacion: float,
    ):
        self.orq = orquestador
        self.almacen = almacen
        self.hub = hub
        self.dispositivo = dispositivo
        self.espera_confirmacion = espera_confirmacion
        self.historial: dict[int, list[dict]] = defaultdict(list)
        self.en_curso: dict[int, asyncio.Task] = {}  # tarea_id -> ejecución
        self.mensajes_estado: dict[int, int] = {}  # tarea_id -> message_id
        self.confirmaciones: dict[str, asyncio.Future] = {}

        autorizados = filters.User(user_id=usuarios)
        self.app = Application.builder().token(token).build()
        self.app.add_handler(CommandHandler("miid", self.cmd_miid))
        self.app.add_handler(CommandHandler("start", self.cmd_inicio, filters=autorizados))
        self.app.add_handler(CommandHandler("estado", self.cmd_estado, filters=autorizados))
        self.app.add_handler(CommandHandler("tareas", self.cmd_tareas, filters=autorizados))
        self.app.add_handler(CommandHandler("cancelar", self.cmd_cancelar, filters=autorizados))
        self.app.add_handler(CommandHandler("olvidar", self.cmd_olvidar, filters=autorizados))
        self.app.add_handler(CallbackQueryHandler(self.al_confirmar, pattern=r"^conf:"))
        self.app.add_handler(MessageHandler(autorizados & filters.TEXT & ~filters.COMMAND, self.al_mensaje))
        self.app.add_handler(MessageHandler(autorizados & filters.VOICE, self.al_voz))
        self.app.add_handler(MessageHandler(~autorizados, self.no_autorizado))

    # --- ciclo de vida -------------------------------------------------------------

    async def iniciar(self) -> None:
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)
        log.info("Bot de Telegram escuchando")

    async def detener(self) -> None:
        for ejecucion in self.en_curso.values():
            ejecucion.cancel()
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()

    # --- comandos -----------------------------------------------------------------

    async def cmd_miid(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(f"Tu id de Telegram es {update.effective_user.id}")

    async def cmd_inicio(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(
            "Hola, soy Aurora. Escríbeme lo que necesitas y lo hago en tu PC, por ejemplo:\n\n"
            "«Investiga precios de cemento y varilla en Mérida, haz un Excel comparativo y un informe»\n\n"
            "Comandos: /estado /tareas /cancelar /olvidar"
        )

    async def cmd_estado(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        conectados = self.hub.dispositivos
        linea = f"Dispositivos conectados: {', '.join(conectados)}" if conectados else "Ningún dispositivo conectado."
        destino = "en línea" if self.hub.en_linea(self.dispositivo) else "desconectado"
        await update.effective_message.reply_text(
            f"{linea}\nDestino predeterminado: {self.dispositivo} ({destino})\nTareas en curso: {len(self.en_curso)}"
        )

    async def cmd_tareas(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        tareas = self.almacen.recientes(update.effective_chat.id)
        if not tareas:
            await update.effective_message.reply_text("Aún no hay tareas.")
            return
        lineas = [f"#{t.id} · {t.estado.etiqueta} · {t.instruccion[:60]}" for t in tareas]
        await update.effective_message.reply_text("\n".join(lineas))

    async def cmd_cancelar(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        propias = [
            tid for tid in self.en_curso if self.almacen.obtener(tid).chat_id == update.effective_chat.id
        ]
        if not propias:
            await update.effective_message.reply_text("No hay ninguna tarea en curso.")
            return
        self.en_curso[max(propias)].cancel()
        await update.effective_message.reply_text(f"Cancelando la tarea #{max(propias)}…")

    async def cmd_olvidar(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        self.historial.pop(update.effective_chat.id, None)
        await update.effective_message.reply_text("Listo, empecé una conversación nueva.")

    async def no_autorizado(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        log.warning("Mensaje de un usuario no autorizado: %s", update.effective_user and update.effective_user.id)

    async def al_voz(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text("Las notas de voz llegan en la fase 2. Por ahora escríbeme.")

    # --- tareas ---------------------------------------------------------------------

    async def al_mensaje(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        texto = update.effective_message.text.strip()
        tarea = self.almacen.crear(chat_id, texto, self.dispositivo)
        aviso = "" if self.hub.en_linea(self.dispositivo) else (
            f"\n⚠️ {self.dispositivo} no está conectada. Si la tarea necesita la PC te lo diré."
        )
        enviado = await update.effective_message.reply_text(f"Tarea #{tarea.id} · {Estado.RECIBIDA.etiqueta}{aviso}")
        self.mensajes_estado[tarea.id] = enviado.message_id
        self.en_curso[tarea.id] = asyncio.create_task(self._correr(tarea))

    async def _correr(self, tarea: Tarea) -> None:
        historial = list(self.historial[tarea.chat_id])
        try:
            reporte = await self.orq.ejecutar(tarea, historial, self)
        except asyncio.CancelledError:
            self.almacen.cambiar_estado(tarea.id, Estado.CANCELADA, "Cancelada por el usuario.")
            await self._editar_estado(tarea, "Tarea cancelada.")
            return
        except Exception:
            log.exception("Fallo inesperado en la tarea %s", tarea.id)
            self.almacen.cambiar_estado(tarea.id, Estado.FALLIDA, "Fallo interno de Aurora.")
            await self.app.bot.send_message(tarea.chat_id, f"❌ La tarea #{tarea.id} falló por un error interno de Aurora.")
            return
        finally:
            self.en_curso.pop(tarea.id, None)

        hist = self.historial[tarea.chat_id]
        hist += [{"role": "user", "content": tarea.instruccion}, {"role": "assistant", "content": reporte.resumen}]
        del hist[:-MAX_HISTORIAL]
        await self._editar_estado(tarea, f"{ICONOS.get(reporte.estado, '')} {reporte.estado.etiqueta}")
        await self.app.bot.send_message(tarea.chat_id, formatear_reporte(tarea, reporte), parse_mode=ParseMode.HTML)

    # --- Notificador (lo usa el orquestador) ----------------------------------------

    async def estado(self, tarea: Tarea, estado: Estado, detalle: str | None = None) -> None:
        texto = estado.etiqueta + (f": {detalle}" if detalle else "") + "…"
        await self._editar_estado(tarea, texto)

    async def confirmar(self, tarea: Tarea, descripcion: str) -> bool:
        clave = uuid.uuid4().hex[:16]
        futuro = asyncio.get_running_loop().create_future()
        self.confirmaciones[clave] = futuro
        teclado = InlineKeyboardMarkup([[
            InlineKeyboardButton("Sí, hazlo", callback_data=f"conf:{clave}:si"),
            InlineKeyboardButton("No", callback_data=f"conf:{clave}:no"),
        ]])
        mensaje = await self.app.bot.send_message(
            tarea.chat_id, f"Tarea #{tarea.id} necesita tu permiso:\n{descripcion}", reply_markup=teclado
        )
        try:
            return await asyncio.wait_for(futuro, timeout=self.espera_confirmacion)
        except asyncio.TimeoutError:
            await mensaje.edit_text(f"{mensaje.text}\n\n(Sin respuesta: no se hizo.)")
            return False
        finally:
            self.confirmaciones.pop(clave, None)

    async def enviar_archivo(self, tarea: Tarea, nombre: str, contenido: bytes) -> None:
        await self.app.bot.send_document(tarea.chat_id, InputFile(contenido, filename=nombre))

    async def al_confirmar(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        consulta = update.callback_query
        _, clave, respuesta = consulta.data.split(":")
        futuro = self.confirmaciones.get(clave)
        await consulta.answer()
        if futuro is None or futuro.done():
            await consulta.edit_message_text(f"{consulta.message.text}\n\n(Esta solicitud ya expiró.)")
            return
        futuro.set_result(respuesta == "si")
        decision = "Aprobado" if respuesta == "si" else "Rechazado"
        await consulta.edit_message_text(f"{consulta.message.text}\n\n{decision}.")

    async def _editar_estado(self, tarea: Tarea, texto: str) -> None:
        message_id = self.mensajes_estado.get(tarea.id)
        if message_id is None:
            return
        try:
            await self.app.bot.edit_message_text(f"Tarea #{tarea.id} · {texto}", tarea.chat_id, message_id)
        except BadRequest as e:  # p. ej. "message is not modified"
            log.debug("No se pudo editar el estado: %s", e)


def formatear_reporte(tarea: Tarea, r: Reporte) -> str:
    e = html.escape
    partes = [f"<b>Aurora — {e(r.estado.etiqueta)}</b> (tarea #{tarea.id})", "", e(r.resumen)]
    if r.archivos:
        partes += ["", f"<b>Archivos en {e(r.dispositivo)}:</b>"]
        for a in r.archivos:
            marca = "✓" if a.verificado else "(sin confirmar)"
            partes.append(f"• <code>{e(a.ruta)}</code> {marca}")
        if r.carpeta_trabajo:
            partes.append(f"Carpeta: <code>{e(r.carpeta_trabajo)}</code>")
    if r.pendiente:
        partes += ["", f"<b>Pendiente:</b> {e(r.pendiente)}"]
    return "\n".join(partes)
