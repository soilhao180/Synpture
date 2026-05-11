from __future__ import annotations

import os
import socket
import sys
from typing import Any

import uvicorn


def resolve_server_port(host: str, preferred_port: int, max_attempts: int = 20) -> int:
    for port in range(preferred_port, preferred_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    return preferred_port


def create_uvicorn_server(app: Any, *, host: str, port: int, log_level: str | None = None) -> uvicorn.Server:
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=log_level or os.getenv("SYNPTURE_LOG_LEVEL", "info"),
        log_config=_resolve_uvicorn_log_config(),
    )
    return uvicorn.Server(config)


def _resolve_uvicorn_log_config() -> dict[str, Any] | None:
    # PyInstaller windowed launches may not expose stdout/stderr objects.
    # Uvicorn's default formatter assumes those streams exist and calls `.isatty()`.
    return uvicorn.config.LOGGING_CONFIG if _has_console_streams() else None


def _has_console_streams() -> bool:
    return _is_usable_stream(sys.stdout) and _is_usable_stream(sys.stderr)


def _is_usable_stream(stream: Any) -> bool:
    return stream is not None and hasattr(stream, "write")
