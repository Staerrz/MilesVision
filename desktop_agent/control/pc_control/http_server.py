"""Streamable HTTP MCP listener for the registered ``pc_*`` bridge tools.

Run from ``desktop_agent/control`` with ``python -m pc_control.server``.
The process listens on ``127.0.0.1:8770`` at ``/mcp``. Miles Memory keeps
``127.0.0.1:8765`` and its own ``/mcp``. This module does not import
``memory_kb``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

HOST = "127.0.0.1"
PORT = 8770
HTTP_PATH = "/mcp"
MEMORY_PORT = 8765


def repo_root() -> Path:
    """MilesVision root: ``desktop_agent/control/pc_control`` is three levels down."""
    return Path(__file__).resolve().parents[3]


def ensure_repo_on_path() -> None:
    """Make ``import desktop_agent`` work when the cwd is ``desktop_agent/control``."""
    root = str(repo_root())
    if root not in sys.path:
        sys.path.insert(0, root)


def listen_port() -> int:
    """Default 8770. ``PC_CONTROL_HTTP_PORT`` overrides it. 8765 is refused."""
    from .envvars import get as pc_env

    raw = pc_env("HTTP_PORT")
    port = PORT if raw is None or str(raw).strip() == "" else int(str(raw).strip())
    if port == MEMORY_PORT:
        raise RuntimeError(
            "Port 8765 belongs to Miles Memory (127.0.0.1:8765 /mcp). "
            "The PC control listener will not bind it."
        )
    return port


def registered_tools() -> tuple[Callable[..., Any], ...]:
    """The bridge callables whose names are ``pc_`` plus each ``SOURCE_NAMES`` entry.

    Nothing else is registered. Screen, mouse, keyboard, and Miles Memory tools
    stay off this listener.
    """
    ensure_repo_on_path()
    from desktop_agent.bridge import api as bridge_api
    from desktop_agent.bridge.pc import SOURCE_NAMES

    tools: list[Callable[..., Any]] = []
    for source_name in SOURCE_NAMES:
        name = f"pc_{source_name}"
        fn = getattr(bridge_api, name, None)
        if not callable(fn) or getattr(fn, "__name__", None) != name:
            raise RuntimeError(f"{name} is not registered on desktop_agent.bridge")
        tools.append(fn)
    return tuple(tools)


def build_server() -> Any:
    """An MCP server whose tools/list is exactly ``registered_tools``."""
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError as exc:
        raise RuntimeError(
            "The PC control listener needs the mcp package (2.x). "
            "Install it with: python -m pip install 'mcp>=2'"
        ) from exc
    server = MCPServer("desktop-agent-pc")
    for fn in registered_tools():
        server.add_tool(fn, structured_output=False)
    return server


def serve(host: str = HOST, port: int | None = None, path: str = HTTP_PATH) -> None:
    """Block on the streamable HTTP listener."""
    chosen = listen_port() if port is None else port
    if chosen == MEMORY_PORT:
        raise RuntimeError(
            "Port 8765 belongs to Miles Memory (127.0.0.1:8765 /mcp). "
            "The PC control listener will not bind it."
        )
    server = build_server()
    print(f"PC control MCP listening at http://{host}:{chosen}{path}", flush=True)
    server.run(
        "streamable-http",
        host=host,
        port=chosen,
        streamable_http_path=path,
    )
