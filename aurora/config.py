"""Configuración de Aurora, leída de variables de entorno o de un archivo .env."""

from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class ServidorConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AURORA_", env_file=".env", extra="ignore")

    telegram_token: str
    # Ids de Telegram autorizados. Cualquier otro usuario es ignorado.
    telegram_usuarios: Annotated[list[int], NoDecode]
    token_agente: str = Field(min_length=16)
    dispositivo: str = "PC"  # dispositivo destino predeterminado
    modelo: str = "claude-opus-5-5"
    esfuerzo: str = "medium"
    host: str = "0.0.0.0"
    puerto: int = 8765
    base_datos: Path = Path("aurora.db")
    max_turnos: int = 40
    espera_confirmacion: int = 600  # segundos para aprobar una acción sensible
    espera_herramienta: int = 300  # segundos máximos por herramienta en la PC

    @field_validator("telegram_usuarios", mode="before")
    @classmethod
    def _separar_ids(cls, valor):
        if isinstance(valor, str):
            return [int(parte) for parte in valor.replace(" ", "").split(",") if parte]
        if isinstance(valor, int):
            return [valor]
        return valor


class AgenteConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AURORA_", env_file=".env", extra="ignore")

    servidor_url: str = "ws://127.0.0.1:8765/ws/agente"
    token_agente: str = Field(min_length=16)
    dispositivo: str = "PC"
    carpeta_trabajo: Path = Path("~/Documents/Aurora")

    @field_validator("carpeta_trabajo")
    @classmethod
    def _expandir(cls, valor: Path) -> Path:
        return valor.expanduser().resolve()
