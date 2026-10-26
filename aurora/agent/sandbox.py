"""Limita lo que el agente puede tocar a la carpeta de trabajo de Aurora."""

from pathlib import Path


class RutaNoPermitida(ValueError):
    pass


class Sandbox:
    def __init__(self, raiz: Path):
        self.raiz = raiz.expanduser().resolve()
        self.raiz.mkdir(parents=True, exist_ok=True)

    def resolver(self, ruta: str) -> Path:
        """Convierte una ruta relativa a la carpeta de trabajo en una ruta absoluta segura.

        Se aceptan rutas absolutas solo si quedan dentro de la carpeta de trabajo.
        """
        if not ruta or not ruta.strip():
            raise RutaNoPermitida("La ruta está vacía.")
        candidata = Path(ruta.strip()).expanduser()
        if not candidata.is_absolute():
            candidata = self.raiz / candidata
        final = candidata.resolve()
        if final != self.raiz and self.raiz not in final.parents:
            raise RutaNoPermitida(f"'{ruta}' está fuera de la carpeta de trabajo de Aurora.")
        return final

    def relativa(self, ruta: Path) -> str:
        return ruta.resolve().relative_to(self.raiz).as_posix() or "."
