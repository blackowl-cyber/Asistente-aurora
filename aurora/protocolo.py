"""Mensajes JSON que intercambian el servidor y el agente de PC por WebSocket.

agente -> servidor
    {"tipo": "hola", "token": str, "dispositivo": str, "herramientas": [str]}
    {"tipo": "resultado", "id": str, "ok": bool, "resultado": dict | None, "error": str | None}

servidor -> agente
    {"tipo": "bienvenida"}
    {"tipo": "llamada", "id": str, "herramienta": str, "argumentos": dict}
"""

HOLA = "hola"
BIENVENIDA = "bienvenida"
LLAMADA = "llamada"
RESULTADO = "resultado"

# Código de cierre cuando el token del agente no es válido.
CIERRE_NO_AUTORIZADO = 4401


def llamada(id_: str, herramienta: str, argumentos: dict) -> dict:
    return {"tipo": LLAMADA, "id": id_, "herramienta": herramienta, "argumentos": argumentos}


def resultado_ok(id_: str, resultado: dict) -> dict:
    return {"tipo": RESULTADO, "id": id_, "ok": True, "resultado": resultado, "error": None}


def resultado_error(id_: str, error: str) -> dict:
    return {"tipo": RESULTADO, "id": id_, "ok": False, "resultado": None, "error": error}
