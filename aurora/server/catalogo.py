"""Catálogo de herramientas que Aurora ofrece al modelo y su política de permisos."""

from dataclasses import dataclass

from .tareas import Estado

# Herramientas que corren en los servidores de Anthropic (búsqueda y lectura web).
HERRAMIENTAS_SERVIDOR = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 15},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 15},
]


@dataclass(frozen=True)
class Politica:
    estado: Estado  # estado que se muestra mientras corre
    sensible: bool  # requiere confirmación del usuario antes de ejecutarse
    en_pc: bool  # se ejecuta en el agente de PC (si no, en el servidor)


POLITICAS = {
    "crear_documento": Politica(Estado.CREANDO_ARCHIVOS, sensible=False, en_pc=True),
    "crear_hoja": Politica(Estado.CREANDO_ARCHIVOS, sensible=False, en_pc=True),
    "listar_archivos": Politica(Estado.EJECUTANDO, sensible=False, en_pc=True),
    "crear_carpeta": Politica(Estado.EJECUTANDO, sensible=False, en_pc=True),
    "mover_archivo": Politica(Estado.EJECUTANDO, sensible=True, en_pc=True),
    "abrir": Politica(Estado.EJECUTANDO, sensible=False, en_pc=True),
    "enviar_al_telefono": Politica(Estado.REVISANDO, sensible=False, en_pc=False),
    "finalizar_tarea": Politica(Estado.REVISANDO, sensible=False, en_pc=False),
}

_RUTA = {
    "type": "string",
    "description": "Ruta relativa a la carpeta de trabajo de Aurora, por ejemplo 'Proyectos/Materiales/informe.docx'.",
}

_BLOQUE = {
    "type": "object",
    "properties": {
        "tipo": {"type": "string", "enum": ["encabezado", "parrafo", "lista", "lista_numerada", "tabla", "salto_pagina"]},
        "texto": {"type": "string", "description": "Para encabezado y parrafo. **texto** va en negritas."},
        "nivel": {"type": "integer", "minimum": 1, "maximum": 4, "description": "Nivel del encabezado."},
        "items": {"type": "array", "items": {"type": "string"}, "description": "Para listas."},
        "encabezados": {"type": "array", "items": {"type": "string"}, "description": "Para tablas."},
        "filas": {"type": "array", "items": {"type": "array", "items": {}}, "description": "Para tablas."},
        "nota": {"type": "string", "description": "Leyenda opcional bajo la tabla, por ejemplo la fuente."},
    },
    "required": ["tipo"],
}

_HOJA = {
    "type": "object",
    "properties": {
        "nombre": {"type": "string", "description": "Nombre de la pestaña, máximo 31 caracteres."},
        "encabezados": {"type": "array", "items": {"type": "string"}},
        "filas": {
            "type": "array",
            "items": {"type": "array", "items": {}},
            "description": "Valores por fila. Usa números reales para cifras. Un texto que empieza con '=' es una fórmula de Excel, por ejemplo '=B2*C2'.",
        },
        "formatos": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": "Formato numérico por encabezado, por ejemplo {\"Precio\": \"$#,##0.00\"}.",
        },
        "grafica": {
            "type": "object",
            "properties": {
                "tipo": {"type": "string", "enum": ["barras", "lineas"]},
                "titulo": {"type": "string"},
                "categorias": {"type": "string", "description": "Encabezado de la columna de categorías."},
                "valores": {"type": "array", "items": {"type": "string"}, "description": "Encabezados de las columnas a graficar."},
            },
            "required": ["categorias", "valores"],
        },
    },
    "required": ["encabezados", "filas"],
}

HERRAMIENTAS_PROPIAS = [
    {
        "name": "crear_documento",
        "description": "Aurora Documentos: crea un archivo de Word (.docx) en la PC con título y bloques de contenido. Devuelve la ruta, el tamaño y si el archivo se verificó.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ruta": _RUTA,
                "titulo": {"type": "string"},
                "subtitulo": {"type": "string"},
                "bloques": {"type": "array", "items": _BLOQUE},
                "sobrescribir": {"type": "boolean", "description": "Solo si el usuario pidió reemplazar el archivo."},
            },
            "required": ["ruta", "titulo", "bloques"],
        },
    },
    {
        "name": "crear_hoja",
        "description": "Aurora Hojas: crea una hoja de cálculo de Excel (.xlsx) en la PC con una o varias pestañas, fórmulas, formatos y gráfica opcional.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ruta": _RUTA,
                "hojas": {"type": "array", "items": _HOJA},
                "sobrescribir": {"type": "boolean"},
            },
            "required": ["ruta", "hojas"],
        },
    },
    {
        "name": "listar_archivos",
        "description": "Lista archivos y carpetas dentro de la carpeta de trabajo de Aurora en la PC.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ruta": {"type": "string", "description": "Carpeta a listar; vacío para la raíz."},
                "recursivo": {"type": "boolean"},
            },
        },
    },
    {
        "name": "crear_carpeta",
        "description": "Crea una carpeta (y las intermedias) en la carpeta de trabajo de la PC.",
        "input_schema": {"type": "object", "properties": {"ruta": _RUTA}, "required": ["ruta"]},
    },
    {
        "name": "mover_archivo",
        "description": "Mueve o renombra un archivo o carpeta dentro de la carpeta de trabajo. Nunca sobrescribe. El usuario debe confirmarlo en su teléfono.",
        "input_schema": {
            "type": "object",
            "properties": {"origen": _RUTA, "destino": _RUTA},
            "required": ["origen", "destino"],
        },
    },
    {
        "name": "abrir",
        "description": "Abre en la PC una página web (http/https) en el navegador, o un archivo de la carpeta de trabajo con su programa predeterminado.",
        "input_schema": {
            "type": "object",
            "properties": {"objetivo": {"type": "string", "description": "URL o ruta relativa."}},
            "required": ["objetivo"],
        },
    },
    {
        "name": "enviar_al_telefono",
        "description": "Envía una copia de un archivo de la PC al chat de Telegram del usuario para que lo abra en su teléfono. Máximo 45 MB.",
        "input_schema": {"type": "object", "properties": {"ruta": _RUTA}, "required": ["ruta"]},
    },
    {
        "name": "finalizar_tarea",
        "description": (
            "Llama a esta herramienta una sola vez al terminar, para reportar el resultado real al usuario. "
            "Usa 'completada' solo si todo lo pedido se hizo y las herramientas lo confirmaron; "
            "'necesita_intervencion' si falta una decisión o dato del usuario; 'fallida' si no se pudo hacer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "estado": {"type": "string", "enum": ["completada", "necesita_intervencion", "fallida"]},
                "resumen": {"type": "string", "description": "2 a 5 frases: qué se hizo, hallazgos clave, qué falta."},
                "archivos": {"type": "array", "items": {"type": "string"}, "description": "Rutas de los archivos creados o modificados."},
                "pendiente": {"type": "string", "description": "Lo que el usuario debe decidir o hacer, si aplica."},
            },
            "required": ["estado", "resumen"],
        },
    },
]

ESTADO_FINAL = {
    "completada": Estado.COMPLETADA,
    "necesita_intervencion": Estado.NECESITA_INTERVENCION,
    "fallida": Estado.FALLIDA,
}

INSTRUCCIONES = """\
Eres Aurora, la asistente personal de tu usuario. No te limitas a dar instrucciones: haces el trabajo con tus herramientas y entregas resultados reales.

Cómo trabajas:
- Entiende qué resultado quiere el usuario, planea los pasos y ejecútalos sin pedir permiso para cada uno.
- Para investigar usa web_search y web_fetch. Consulta varias fuentes, prefiere las oficiales, verifica fechas y anota las URL. Distingue hechos, opiniones y estimaciones. Si un precio, una fecha o una disponibilidad no se puede verificar, dilo.
- Los archivos se crean en la PC del usuario con tus sub-apps: crear_documento (Word) y crear_hoja (Excel). Guárdalos en 'Proyectos/<nombre del proyecto>/' salvo que el usuario indique otra ruta. Los informes llevan una sección de fuentes con enlaces y la fecha de consulta.
- Las hojas de cálculo usan números reales (no texto) en las cifras y fórmulas de Excel para totales y cálculos.
- Si el usuario no está frente a la PC y el archivo le sirve en el teléfono, envíaselo con enviar_al_telefono.

Honestidad:
- Nunca digas que hiciste algo que una herramienta no confirmó. Si una herramienta falla o la PC no está conectada, dilo con claridad, explica qué sí se completó y qué falta.
- Distingue entre lo que preparaste y lo que realmente ejecutaste.
- No hagas compras, pagos ni envíos de mensajes a terceros: están fuera de tus funciones.

Al terminar, llama a finalizar_tarea con el estado real, un resumen breve y las rutas de los archivos. Escribe siempre en español, con un tono cercano y directo.
"""
