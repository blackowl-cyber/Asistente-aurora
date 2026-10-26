import asyncio
from types import SimpleNamespace as NS

import pytest

from aurora.server.hub import DispositivoNoDisponible, ErrorHerramienta, Hub
from aurora.server.orquestador import Orquestador
from aurora.server.tareas import AlmacenTareas, Estado


# --- dobles de prueba -----------------------------------------------------------------

def texto(t):
    return NS(type="text", text=t)


def uso(id_, nombre, entrada):
    return NS(type="tool_use", id=id_, name=nombre, input=entrada)


def respuesta(stop, *bloques):
    return NS(stop_reason=stop, content=list(bloques))


class ClienteFalso:
    """Imita client.beta.messages.create devolviendo respuestas preparadas."""

    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []
        self.beta = NS(messages=NS(create=self._crear))

    async def _crear(self, **kwargs):
        self.llamadas.append(kwargs)
        return self.respuestas.pop(0)


class HubFalso:
    def __init__(self, resultados=None, en_linea=True):
        self.resultados = resultados or {}
        self.llamadas = []
        self._en_linea = en_linea

    async def llamar(self, dispositivo, herramienta, argumentos, espera):
        self.llamadas.append((herramienta, argumentos))
        if not self._en_linea:
            raise DispositivoNoDisponible(f"El dispositivo '{dispositivo}' no está conectado.")
        r = self.resultados[herramienta]
        if isinstance(r, Exception):
            raise r
        return r


class NotificadorFalso:
    def __init__(self, aprobar=True):
        self.estados = []
        self.confirmaciones = []
        self.archivos = []
        self.aprobar = aprobar

    async def estado(self, tarea, estado, detalle=None):
        self.estados.append(estado)

    async def confirmar(self, tarea, descripcion):
        self.confirmaciones.append(descripcion)
        return self.aprobar

    async def enviar_archivo(self, tarea, nombre, contenido):
        self.archivos.append((nombre, contenido))


@pytest.fixture
def almacen(tmp_path):
    return AlmacenTareas(tmp_path / "t.db")


def orq(cliente, hub, almacen):
    return Orquestador(cliente, hub, almacen, modelo="claude-opus-5-5")


DOC_OK = {"ruta": "Proyectos/X/informe.docx", "verificado": True, "bytes": 10, "carpeta_trabajo": "C:/Users/j/Aurora"}


# --- orquestador ----------------------------------------------------------------------

async def test_flujo_completo_con_archivo_verificado(almacen):
    cliente = ClienteFalso(
        respuesta("tool_use", NS(type="server_tool_use", id="s1", name="web_search", input={}),
                  uso("t1", "crear_documento", {"ruta": "Proyectos/X/informe.docx", "titulo": "X", "bloques": []})),
        respuesta("tool_use", uso("t2", "finalizar_tarea", {
            "estado": "completada", "resumen": "Hice el informe.", "archivos": ["Proyectos/X/informe.docx"]})),
    )
    hub = HubFalso({"crear_documento": DOC_OK})
    notif = NotificadorFalso()
    tarea = almacen.crear(1, "haz un informe", "PC")

    r = await orq(cliente, hub, almacen).ejecutar(tarea, [], notif)

    assert r.estado == Estado.COMPLETADA
    assert [(a.ruta, a.verificado) for a in r.archivos] == [("Proyectos/X/informe.docx", True)]
    assert r.carpeta_trabajo == "C:/Users/j/Aurora"
    assert notif.estados == [Estado.PREPARANDO, Estado.INVESTIGANDO, Estado.CREANDO_ARCHIVOS, Estado.REVISANDO]
    assert almacen.obtener(tarea.id).estado == Estado.COMPLETADA
    assert [a["herramienta"] for a in almacen.acciones(tarea.id)] == ["crear_documento"]
    pedido = cliente.llamadas[0]
    assert pedido["model"] == "claude-opus-5-5" and pedido["fallbacks"] == "default"
    assert pedido["thinking"] == {"type": "adaptive"}


async def test_archivo_no_confirmado_no_cuenta_como_exito(almacen):
    cliente = ClienteFalso(respuesta("tool_use", uso("t1", "finalizar_tarea", {
        "estado": "completada", "resumen": "Listo", "archivos": ["inventado.xlsx"]})))
    r = await orq(cliente, HubFalso(), almacen).ejecutar(almacen.crear(1, "x", "PC"), [], NotificadorFalso())
    assert r.estado == Estado.NECESITA_INTERVENCION
    assert r.archivos[0].verificado is False


async def test_pc_desconectada_se_reporta_al_modelo(almacen):
    cliente = ClienteFalso(
        respuesta("tool_use", uso("t1", "crear_hoja", {"ruta": "a.xlsx", "hojas": []})),
        respuesta("tool_use", uso("t2", "finalizar_tarea", {"estado": "fallida", "resumen": "La PC está apagada."})),
    )
    tarea = almacen.crear(1, "x", "PC")
    r = await orq(cliente, HubFalso(en_linea=False), almacen).ejecutar(tarea, [], NotificadorFalso())
    resultado = cliente.llamadas[1]["messages"][2]["content"][0]
    assert resultado["is_error"] and "no está conectado" in resultado["content"]
    assert r.estado == Estado.FALLIDA
    assert almacen.acciones(tarea.id)[0]["ejecutada"] is False


async def test_accion_sensible_rechazada_no_se_ejecuta(almacen):
    cliente = ClienteFalso(
        respuesta("tool_use", uso("t1", "mover_archivo", {"origen": "a", "destino": "b"})),
        respuesta("end_turn", texto("No moví nada porque no lo autorizaste.")),
    )
    hub = HubFalso({"mover_archivo": {"verificado": True}})
    notif = NotificadorFalso(aprobar=False)
    r = await orq(cliente, hub, almacen).ejecutar(almacen.crear(1, "x", "PC"), [], notif)
    assert hub.llamadas == []
    assert notif.confirmaciones == ["Mover «a» a «b»"]
    assert "no lo autorizaste" in r.resumen


async def test_enviar_al_telefono(almacen):
    cliente = ClienteFalso(
        respuesta("tool_use", uso("t1", "enviar_al_telefono", {"ruta": "a.txt"})),
        respuesta("end_turn", texto("Te lo mandé.")),
    )
    hub = HubFalso({"leer_para_envio": {"nombre": "a.txt", "contenido_b64": "YWJj"}})
    notif = NotificadorFalso()
    await orq(cliente, hub, almacen).ejecutar(almacen.crear(1, "x", "PC"), [], notif)
    assert notif.archivos == [("a.txt", b"abc")]


async def test_pause_turn_continua(almacen):
    cliente = ClienteFalso(
        respuesta("pause_turn", NS(type="server_tool_use", id="s1", name="web_search", input={})),
        respuesta("end_turn", texto("Hola")),
    )
    r = await orq(cliente, HubFalso(), almacen).ejecutar(almacen.crear(1, "x", "PC"), [], NotificadorFalso())
    assert r.estado == Estado.COMPLETADA and len(cliente.llamadas) == 2


async def test_rechazo_del_modelo(almacen):
    cliente = ClienteFalso(respuesta("refusal"))
    r = await orq(cliente, HubFalso(), almacen).ejecutar(almacen.crear(1, "x", "PC"), [], NotificadorFalso())
    assert r.estado == Estado.FALLIDA


async def test_limite_de_turnos(almacen):
    cliente = ClienteFalso(*[respuesta("tool_use", uso(f"t{i}", "listar_archivos", {})) for i in range(3)])
    o = Orquestador(cliente, HubFalso({"listar_archivos": {"entradas": []}}), almacen, "m", max_turnos=3)
    r = await o.ejecutar(almacen.crear(1, "x", "PC"), [], NotificadorFalso())
    assert r.estado == Estado.FALLIDA and "límite" in r.resumen


# --- hub ------------------------------------------------------------------------------

class ConexionFalsa:
    def __init__(self, hub, respuesta):
        self.hub, self.respuesta = hub, respuesta

    async def send_json(self, datos):
        asyncio.get_running_loop().call_soon(self.hub.resolver, {"id": datos["id"], **self.respuesta})


async def test_hub_llamada_y_error():
    hub = Hub()
    with pytest.raises(DispositivoNoDisponible):
        await hub.llamar("PC", "x", {}, 1)
    hub.registrar("PC", ConexionFalsa(hub, {"ok": True, "resultado": {"a": 1}}))
    assert await hub.llamar("PC", "x", {}, 1) == {"a": 1}
    hub.registrar("PC", ConexionFalsa(hub, {"ok": False, "error": "falló"}))
    with pytest.raises(ErrorHerramienta, match="falló"):
        await hub.llamar("PC", "x", {}, 1)


async def test_hub_desconexion_a_mitad():
    hub = Hub()

    class Muda:
        async def send_json(self, datos):
            pass

    conexion = Muda()
    hub.registrar("PC", conexion)
    llamada = asyncio.create_task(hub.llamar("PC", "x", {}, 5))
    await asyncio.sleep(0)
    hub.quitar("PC", conexion)
    with pytest.raises(DispositivoNoDisponible):
        await llamada
    assert not hub.en_linea("PC")
