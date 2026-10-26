"""Utilidades compartidas por las sub-apps."""

import hashlib
from pathlib import Path


class ErrorSubApp(ValueError):
    """Error con un mensaje que se puede mostrar tal cual al modelo y al usuario."""


def preparar_destino(destino: Path, extension: str, sobrescribir: bool) -> Path:
    if destino.suffix.lower() != extension:
        destino = destino.with_suffix(extension)
    if destino.exists() and not sobrescribir:
        raise ErrorSubApp(f"Ya existe '{destino.name}'. Usa otro nombre o pide sobrescribir.")
    destino.parent.mkdir(parents=True, exist_ok=True)
    return destino


def huella(ruta: Path) -> dict:
    datos = ruta.read_bytes()
    return {"bytes": len(datos), "sha256": hashlib.sha256(datos).hexdigest()}
