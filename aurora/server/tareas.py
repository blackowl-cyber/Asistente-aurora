"""Tareas, sus estados y el historial de acciones, guardados en SQLite."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class Estado(str, Enum):
    RECIBIDA = "recibida"
    PREPARANDO = "preparando"
    INVESTIGANDO = "investigando"
    CREANDO_ARCHIVOS = "creando_archivos"
    EJECUTANDO = "ejecutando"
    ESPERANDO_CONFIRMACION = "esperando_confirmacion"
    REVISANDO = "revisando"
    COMPLETADA = "completada"
    NECESITA_INTERVENCION = "necesita_intervencion"
    FALLIDA = "fallida"
    CANCELADA = "cancelada"

    @property
    def etiqueta(self) -> str:
        return ETIQUETAS[self]

    @property
    def final(self) -> bool:
        return self in (Estado.COMPLETADA, Estado.NECESITA_INTERVENCION, Estado.FALLIDA, Estado.CANCELADA)


ETIQUETAS = {
    Estado.RECIBIDA: "Instrucción recibida",
    Estado.PREPARANDO: "Preparando la tarea",
    Estado.INVESTIGANDO: "Investigando información",
    Estado.CREANDO_ARCHIVOS: "Creando archivos",
    Estado.EJECUTANDO: "Trabajando en tu PC",
    Estado.ESPERANDO_CONFIRMACION: "Esperando tu confirmación",
    Estado.REVISANDO: "Revisando resultados",
    Estado.COMPLETADA: "Trabajo completado",
    Estado.NECESITA_INTERVENCION: "Necesita tu intervención",
    Estado.FALLIDA: "No se pudo completar",
    Estado.CANCELADA: "Cancelada",
}

ESQUEMA = """
CREATE TABLE IF NOT EXISTS tareas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    instruccion TEXT NOT NULL,
    dispositivo TEXT NOT NULL,
    estado TEXT NOT NULL,
    resumen TEXT,
    creada TEXT NOT NULL,
    actualizada TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS acciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tarea_id INTEGER NOT NULL REFERENCES tareas(id),
    momento TEXT NOT NULL,
    herramienta TEXT NOT NULL,
    argumentos TEXT NOT NULL,
    ejecutada INTEGER NOT NULL,
    ok INTEGER NOT NULL,
    resultado TEXT
);
"""


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Tarea:
    id: int
    chat_id: int
    instruccion: str
    dispositivo: str
    estado: Estado
    resumen: str | None
    creada: str


class AlmacenTareas:
    def __init__(self, ruta: Path | str):
        self.db = sqlite3.connect(str(ruta), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(ESQUEMA)

    def crear(self, chat_id: int, instruccion: str, dispositivo: str) -> Tarea:
        momento = _ahora()
        cur = self.db.execute(
            "INSERT INTO tareas (chat_id, instruccion, dispositivo, estado, creada, actualizada)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, instruccion, dispositivo, Estado.RECIBIDA.value, momento, momento),
        )
        self.db.commit()
        return self.obtener(cur.lastrowid)

    def obtener(self, tarea_id: int) -> Tarea:
        fila = self.db.execute("SELECT * FROM tareas WHERE id = ?", (tarea_id,)).fetchone()
        if fila is None:
            raise KeyError(tarea_id)
        return self._tarea(fila)

    def recientes(self, chat_id: int, limite: int = 5) -> list[Tarea]:
        filas = self.db.execute(
            "SELECT * FROM tareas WHERE chat_id = ? ORDER BY id DESC LIMIT ?", (chat_id, limite)
        ).fetchall()
        return [self._tarea(f) for f in filas]

    def cambiar_estado(self, tarea_id: int, estado: Estado, resumen: str | None = None) -> None:
        if resumen is None:
            self.db.execute(
                "UPDATE tareas SET estado = ?, actualizada = ? WHERE id = ?",
                (estado.value, _ahora(), tarea_id),
            )
        else:
            self.db.execute(
                "UPDATE tareas SET estado = ?, resumen = ?, actualizada = ? WHERE id = ?",
                (estado.value, resumen, _ahora(), tarea_id),
            )
        self.db.commit()

    def registrar_accion(
        self, tarea_id: int, herramienta: str, argumentos: dict, ejecutada: bool, ok: bool, resultado
    ) -> None:
        self.db.execute(
            "INSERT INTO acciones (tarea_id, momento, herramienta, argumentos, ejecutada, ok, resultado)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                tarea_id, _ahora(), herramienta,
                json.dumps(argumentos, ensure_ascii=False)[:20000],
                int(ejecutada), int(ok),
                json.dumps(resultado, ensure_ascii=False)[:20000],
            ),
        )
        self.db.commit()

    def acciones(self, tarea_id: int) -> list[dict]:
        filas = self.db.execute(
            "SELECT herramienta, argumentos, ejecutada, ok, resultado FROM acciones WHERE tarea_id = ? ORDER BY id",
            (tarea_id,),
        ).fetchall()
        return [
            {
                "herramienta": f["herramienta"],
                "argumentos": json.loads(f["argumentos"]),
                "ejecutada": bool(f["ejecutada"]),
                "ok": bool(f["ok"]),
                "resultado": json.loads(f["resultado"]) if f["resultado"] else None,
            }
            for f in filas
        ]

    def _tarea(self, f: sqlite3.Row) -> Tarea:
        return Tarea(
            id=f["id"], chat_id=f["chat_id"], instruccion=f["instruccion"],
            dispositivo=f["dispositivo"], estado=Estado(f["estado"]),
            resumen=f["resumen"], creada=f["creada"],
        )
