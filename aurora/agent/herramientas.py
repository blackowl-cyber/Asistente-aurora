"""Herramientas que el agente ejecuta en la PC. Cada una recibe argumentos JSON y devuelve un dict."""

from collections.abc import Callable

from .sandbox import Sandbox
from .subapps import archivos, documentos, hojas, sistema


class Herramientas:
    def __init__(self, sandbox: Sandbox):
        self.sb = sandbox
        self._tabla: dict[str, Callable[[dict], dict]] = {
            "crear_documento": self.crear_documento,
            "crear_hoja": self.crear_hoja,
            "listar_archivos": self.listar_archivos,
            "crear_carpeta": self.crear_carpeta,
            "mover_archivo": self.mover_archivo,
            "abrir": self.abrir,
            "leer_para_envio": self.leer_para_envio,
        }

    @property
    def nombres(self) -> list[str]:
        return sorted(self._tabla)

    def ejecutar(self, nombre: str, argumentos: dict) -> dict:
        if nombre not in self._tabla:
            raise ValueError(f"La herramienta '{nombre}' no existe en este agente.")
        return self._tabla[nombre](argumentos)

    def _relativizar(self, resultado: dict) -> dict:
        """Muestra las rutas relativas a la carpeta de trabajo, más fáciles de leer."""
        for clave in ("ruta", "origen", "destino"):
            if isinstance(resultado.get(clave), str):
                resultado[clave] = self.sb.relativa(self.sb.resolver(resultado[clave]))
        resultado["carpeta_trabajo"] = str(self.sb.raiz)
        return resultado

    def crear_documento(self, a: dict) -> dict:
        r = documentos.crear_documento(
            self.sb.resolver(a["ruta"]),
            titulo=a["titulo"],
            bloques=a.get("bloques", []),
            subtitulo=a.get("subtitulo"),
            sobrescribir=bool(a.get("sobrescribir", False)),
        )
        return self._relativizar(r)

    def crear_hoja(self, a: dict) -> dict:
        r = hojas.crear_hoja(
            self.sb.resolver(a["ruta"]),
            hojas=a.get("hojas", []),
            sobrescribir=bool(a.get("sobrescribir", False)),
        )
        return self._relativizar(r)

    def listar_archivos(self, a: dict) -> dict:
        carpeta = self.sb.resolver(a.get("ruta") or ".")
        return archivos.listar(carpeta, self.sb.raiz, recursivo=bool(a.get("recursivo", False)))

    def crear_carpeta(self, a: dict) -> dict:
        return self._relativizar(archivos.crear_carpeta(self.sb.resolver(a["ruta"])))

    def mover_archivo(self, a: dict) -> dict:
        r = archivos.mover(self.sb.resolver(a["origen"]), self.sb.resolver(a["destino"]))
        return self._relativizar(r)

    def abrir(self, a: dict) -> dict:
        objetivo = a["objetivo"].strip()
        if objetivo.startswith(("http://", "https://")):
            return sistema.abrir_url(objetivo)
        return self._relativizar(sistema.abrir_archivo(self.sb.resolver(objetivo)))

    def leer_para_envio(self, a: dict) -> dict:
        return archivos.leer_para_envio(self.sb.resolver(a["ruta"]))
