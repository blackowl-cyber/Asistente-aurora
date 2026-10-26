"""Aurora Archivos: lista, crea carpetas y organiza archivos dentro de la carpeta de trabajo."""

import base64
import shutil
from datetime import datetime
from pathlib import Path

from .comun import ErrorSubApp

MAX_ENTRADAS = 500
MAX_ENVIO = 45 * 1024 * 1024  # Telegram acepta documentos de hasta 50 MB


def listar(carpeta: Path, raiz: Path, recursivo: bool = False) -> dict:
    if not carpeta.is_dir():
        raise ErrorSubApp(f"No existe la carpeta '{carpeta.name}'.")
    patron = carpeta.rglob("*") if recursivo else carpeta.iterdir()
    entradas = []
    for ruta in sorted(patron):
        if len(entradas) >= MAX_ENTRADAS:
            break
        info = ruta.stat()
        entradas.append({
            "ruta": ruta.relative_to(raiz).as_posix(),
            "tipo": "carpeta" if ruta.is_dir() else "archivo",
            "bytes": None if ruta.is_dir() else info.st_size,
            "modificado": datetime.fromtimestamp(info.st_mtime).isoformat(timespec="minutes"),
        })
    return {"entradas": entradas, "truncado": len(entradas) >= MAX_ENTRADAS}


def crear_carpeta(carpeta: Path) -> dict:
    existia = carpeta.is_dir()
    carpeta.mkdir(parents=True, exist_ok=True)
    return {"ruta": str(carpeta), "ya_existia": existia}


def mover(origen: Path, destino: Path) -> dict:
    if not origen.exists():
        raise ErrorSubApp(f"No existe '{origen.name}'.")
    if destino.is_dir():
        destino = destino / origen.name
    if destino.exists():
        raise ErrorSubApp(f"Ya existe '{destino.name}' en el destino; no se sobrescribe.")
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(origen), str(destino))
    return {"origen": str(origen), "destino": str(destino), "verificado": destino.exists()}


def leer_para_envio(ruta: Path) -> dict:
    if not ruta.is_file():
        raise ErrorSubApp(f"No existe el archivo '{ruta.name}'.")
    tamano = ruta.stat().st_size
    if tamano > MAX_ENVIO:
        raise ErrorSubApp(f"'{ruta.name}' pesa {tamano // 1_048_576} MB; el límite es 45 MB.")
    return {"nombre": ruta.name, "contenido_b64": base64.b64encode(ruta.read_bytes()).decode()}
