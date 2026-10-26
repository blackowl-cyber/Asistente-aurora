"""Abre páginas web y archivos en la PC con el programa predeterminado del sistema."""

import os
import subprocess
import sys
import webbrowser
from pathlib import Path

from .comun import ErrorSubApp


def abrir_url(url: str) -> dict:
    if not url.startswith(("http://", "https://")):
        raise ErrorSubApp("Solo se pueden abrir direcciones http o https.")
    abierto = webbrowser.open(url)
    return {"url": url, "abierto": abierto}


def abrir_archivo(ruta: Path) -> dict:
    if not ruta.exists():
        raise ErrorSubApp(f"No existe '{ruta.name}'.")
    if sys.platform == "win32":
        os.startfile(ruta)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(ruta)])
    else:
        subprocess.Popen(["xdg-open", str(ruta)])
    return {"ruta": str(ruta), "abierto": True}
