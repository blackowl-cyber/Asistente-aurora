"""Punto de entrada: `aurora-servidor`."""

import logging

import uvicorn

from ..config import ServidorConfig
from .app import crear_app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    config = ServidorConfig()
    uvicorn.run(crear_app(config), host=config.host, port=config.puerto, ws_max_size=64 * 1024 * 1024)


if __name__ == "__main__":
    main()
