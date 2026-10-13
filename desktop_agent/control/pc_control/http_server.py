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
    """An MCP server whose tools/list is exactly ``registered_tools``.

    OAuth stays on. Unauthenticated ``/mcp`` is 401. A bearer token from
    ``/token`` is what ``tools/list`` accepts.
    """
    try:
        from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
        from mcp.server.mcpserver import MCPServer
    except ImportError as exc:
        raise RuntimeError(
            "The PC control listener needs the mcp package (2.x). "
            "Install it with: python -m pip install 'mcp>=2'"
        ) from exc
    from .oauth import LocalDesktopOAuth, public_origin

    origin = public_origin()
    provider = LocalDesktopOAuth()
    server = MCPServer(
        "desktop-agent-pc",
        auth=AuthSettings(
            issuer_url=origin,
            resource_server_url=origin,
            client_registration_options=ClientRegistrationOptions(enabled=True),
            required_scopes=[],
            validate_token_resource=False,
        ),
        auth_server_provider=provider,
    )
    server.pc_oauth = provider
    for fn in registered_tools():
        server.add_tool(fn, structured_output=False)
    return server


def _install_confirm_authorize(app: Any, provider: Any) -> None:
    """Replace the SDK ``/authorize`` route with the confirm page.

    The SDK handler answers an unknown ``client_id`` with 400 and redirects
    immediately. Sesame opens ``/authorize`` for a client registered on another
    process, and that GET has to be the confirm page.
    """
    from mcp.server.transport_security import DEFAULT_MAX_REQUEST_BODY_SIZE, RequestBodyLimitMiddleware
    from starlette.routing import Route, request_response

    from .oauth import ConfirmAuthorize

    endpoint = RequestBodyLimitMiddleware(
        request_response(ConfirmAuthorize(provider).handle),
        DEFAULT_MAX_REQUEST_BODY_SIZE,
    )
    replacement = Route("/authorize", endpoint=endpoint, methods=["GET", "POST"])
    routes = app.router.routes
    for index, route in enumerate(routes):
        if getattr(route, "path", None) == "/authorize":
            routes[index] = replacement
            return
    raise RuntimeError("PC control listener is missing /authorize")


def build_http_app(host: str = HOST, path: str = HTTP_PATH) -> Any:
    """One Starlette app, one ``StreamableHTTPSessionManager``, for the process.

    ``streamable_http_app`` is called once. Its Starlette lifespan is that
    manager's ``run()``, entered when uvicorn starts and left when it stops.
    Requests do not build another manager.

    ``stateless_http`` and ``json_response`` stay on. DNS-rebinding protection
    is off, the same way a tunneled host such as ``aetherbridge.a.pinggy.link``
    is allowed through to Miles Memory: the SDK's localhost allow-list would
    otherwise answer that Host with 421.
    """
    from mcp.server.transport_security import TransportSecuritySettings

    server = build_server()
    app = server.streamable_http_app(
        streamable_http_path=path,
        json_response=True,
        stateless_http=True,
        host=host,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    _install_confirm_authorize(app, server.pc_oauth)
    manager = server.session_manager
    if not manager.stateless or not manager.json_response:
        raise RuntimeError("PC control listener must be one stateless JSON session manager")
    app.state.pc_session_manager = manager
    return app


def serve(host: str = HOST, port: int | None = None, path: str = HTTP_PATH) -> None:
    """Block on the streamable HTTP listener."""
    import uvicorn

    chosen = listen_port() if port is None else port
    if chosen == MEMORY_PORT:
        raise RuntimeError(
            "Port 8765 belongs to Miles Memory (127.0.0.1:8765 /mcp). "
            "The PC control listener will not bind it."
        )
    app = build_http_app(host=host, path=path)
    message = f"PC control MCP listening at http://{host}:{chosen}{path}"
    config = uvicorn.Config(app, host=host, port=chosen, log_level="info", lifespan="on")

    class _Server(uvicorn.Server):
        async def startup(self, sockets=None):  # type: ignore[no-untyped-def]
            await super().startup(sockets=sockets)
            print(message, flush=True)

    _Server(config).run()
