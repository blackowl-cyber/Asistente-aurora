# Aurora

Aurora es un asistente personal que hace el trabajo de verdad. Le escribes desde Telegram en tu teléfono, ella investiga en internet, crea los archivos en tu PC y te avisa cuando termina, con el estado real de cada tarea.

Esta es la **fase 1 (MVP)**. Por ahora puede:

- Recibir órdenes por Telegram desde cualquier red.
- Investigar en la web con fuentes (búsqueda y lectura de páginas).
- Crear documentos de Word y hojas de Excel en tu PC con sus propias sub-apps, sin abrir Office.
- Listar, crear carpetas y organizar archivos dentro de su carpeta de trabajo.
- Abrir páginas web o archivos en tu PC.
- Mandarte una copia de un archivo al teléfono.
- Mostrar estados reales (investigando, creando archivos, esperando tu confirmación, etc.).
- Pedirte permiso con botones antes de una acción sensible (mover archivos).
- Avisarte al final qué hizo, dónde guardó cada archivo y si algo quedó pendiente.

Lo que **no** hace, a propósito: compras, pagos, WhatsApp ni servicios de streaming.

## Cómo funciona

```
Teléfono (Telegram) ──► Servidor de Aurora ──► Claude (decide qué herramienta usar)
                              │
                              └── WebSocket ──► Agente de PC (crea los archivos)
```

- **Servidor** (`aurora-servidor`): el bot de Telegram, el orquestador que habla con Claude y el registro de tareas en SQLite.
- **Agente de PC** (`aurora-agente`): ejecuta las herramientas en tu computadora. Solo puede tocar su carpeta de trabajo (por defecto `Documentos\Aurora`). La conexión sale de la PC hacia el servidor, así que no hay que abrir puertos en el router.

En la fase 1 ambos corren en tu PC. Telegram hace de puente con el teléfono, así que funciona aunque estés fuera de casa. Si la PC está apagada, el bot no contesta; para que Aurora te avise de eso, el servidor puede moverse más adelante a un servidor en la nube sin cambiar el agente.

## Instalación en Windows

### 1. Requisitos

- [Python 3.12](https://www.python.org/downloads/) (marca "Add Python to PATH" al instalar).
- Una clave de API de Anthropic, de [console.anthropic.com](https://console.anthropic.com).
- Telegram en tu teléfono.

### 2. Crear el bot de Telegram

1. En Telegram, abre [@BotFather](https://t.me/BotFather) y envía `/newbot`.
2. Elige un nombre (por ejemplo "Aurora") y un usuario que termine en `bot`.
3. Copia el token que te da.

### 3. Descargar e instalar

En PowerShell:

```powershell
git clone https://github.com/blackowl-cyber/Asistente-aurora.git
cd Asistente-aurora
py -3.12 -m venv .venv
.venv\Scripts\pip install -e ".[servidor]"
copy .env.example .env
notepad .env
```

En `.env` llena:

| Variable | Qué poner |
| --- | --- |
| `ANTHROPIC_API_KEY` | Tu clave de Anthropic |
| `AURORA_TELEGRAM_TOKEN` | El token de BotFather |
| `AURORA_TELEGRAM_USUARIOS` | Tu id de Telegram (ver paso 4) |
| `AURORA_TOKEN_AGENTE` | Un texto largo y aleatorio inventado por ti; protege la conexión con la PC |
| `AURORA_CARPETA_TRABAJO` | Dónde guarda Aurora los archivos (por defecto `~/Documents/Aurora`) |

### 4. Averiguar tu id de Telegram

Arranca el servidor una vez con `.venv\Scripts\aurora-servidor`, escribe `/miid` a tu bot y copia el número en `AURORA_TELEGRAM_USUARIOS`. Solo los ids de esa lista pueden darle órdenes a Aurora.

### 5. Iniciar Aurora

Doble clic en `scripts\iniciar_aurora.bat`. Se abren dos ventanas: el servidor y el agente de PC. Para que arranque sola al encender la PC, crea un acceso directo a ese archivo en la carpeta que abre `Win + R` → `shell:startup`.

## Uso

Escríbele a tu bot, por ejemplo:

> Investiga dónde comprar cemento, varilla y block más barato en Mérida, haz un Excel comparativo y un informe en Word, y mándame el informe al teléfono.

Comandos:

| Comando | Para qué |
| --- | --- |
| `/estado` | Ver si tu PC está conectada |
| `/tareas` | Últimas tareas y su estado |
| `/cancelar` | Detener la tarea en curso |
| `/olvidar` | Empezar una conversación nueva |
| `/miid` | Ver tu id de Telegram |

## Desarrollo

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

Estructura:

```
aurora/
  config.py            configuración (.env)
  protocolo.py         mensajes entre servidor y agente
  server/
    app.py             FastAPI: WebSocket de agentes + arranque del bot
    bot.py             bot de Telegram, confirmaciones y reportes
    orquestador.py     bucle del modelo con herramientas, estados y verificación
    catalogo.py        herramientas, permisos e instrucciones de Aurora
    hub.py             agentes conectados y llamadas remotas
    tareas.py          tareas, estados e historial de acciones (SQLite)
  agent/
    main.py            cliente WebSocket con reconexión
    herramientas.py    despacho de herramientas
    sandbox.py         limita todo a la carpeta de trabajo
    subapps/           Documentos (Word), Hojas (Excel), Archivos, Sistema
```

Para agregar una herramienta nueva: impleméntala en `aurora/agent/subapps/`, regístrala en `aurora/agent/herramientas.py` y descríbela en `aurora/server/catalogo.py` con su política (si es sensible y qué estado muestra).

## Siguientes fases

1. **Voz y memoria**: notas de voz, palabra de activación "Aurora" en la PC y memoria de preferencias.
2. **Aurora Home**: luces, ventiladores y aire acondicionado con Home Assistant.
3. **Autónoma**: rutinas programadas (eventos de la semana, vigilancia de precios), agenda y correo.
4. **Avanzada**: sub-apps de presentaciones y diseño, app Android propia.
