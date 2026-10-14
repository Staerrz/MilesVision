"""Streamable HTTP MCP listener for the registered ``pc_*`` bridge tools.

Run from ``desktop_agent/control`` with ``python -m pc_control.server``.
The process listens on ``127.0.0.1:8770`` at ``/mcp``. Miles Memory keeps
``127.0.0.1:8765`` and its own ``/mcp``. This module does not import
``memory_kb``.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Any, Callable, Union, get_args, get_origin

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


# Descriptions for parameters the registered functions actually take.
# ``confirm`` is not one of them.
_ARGUMENT_TEXT: dict[str, dict[str, str]] = {
    "pc_windows": {
        "filter": "Text matched against the window title or process. Empty lists every window.",
    },
    "pc_look": {
        "window": "Window title substring or hwnd from pc_windows.",
        "mode": "How to look. Default auto.",
        "find": "Element text to locate. Empty returns the whole look.",
        "wait": "Seconds to poll while finding. Default 0.",
    },
    "pc_click": {
        "window": "Window title substring or hwnd.",
        "target": "Element id from pc_look.",
        "right": "Right click. Default false.",
        "double": "Double click. Default false.",
        "dry_run": "When true, return the plan and do not change the screen.",
    },
    "pc_type": {
        "window": "Window title substring or hwnd.",
        "target": "Element id from pc_look.",
        "text": "Text to type into that element.",
        "replace": "Replace the element's current text. Default false.",
        "dry_run": "When true, return the plan and do not change the screen.",
    },
    "pc_drag": {
        "window": "Window title substring or hwnd.",
        "points": "Image points to drag through.",
        "shape": "Drag shape. Default path.",
        "right": "Right-button drag. Default false.",
        "dry_run": "When true, return the plan and do not change the screen.",
    },
    "pc_key": {
        "window": "Window title substring or hwnd.",
        "name": "Key name or the app's own shortcut command.",
        "dry_run": "When true, return the plan and do not change the screen.",
    },
    "pc_scroll": {
        "window": "Window title substring or hwnd.",
        "direction": "Scroll direction. Default down.",
        "target": "Element id to scroll. Empty scrolls the window.",
        "amount": "Scroll steps. Default 1.",
        "dry_run": "When true, return the plan and do not change the screen.",
    },
    "pc_read": {
        "window": "Window title substring or hwnd.",
        "target": "Document, page, or field to read. Empty reads the window.",
        "start": "Character offset. Default 0.",
        "length": "Maximum characters. Default 6000.",
        "find": "Text to locate inside the document. Empty reads from start.",
    },
    "pc_show": {
        "window": "Window title substring or hwnd.",
        "target": "Element id to mark.",
        "label": "Caption drawn with the mark. Default empty.",
        "seconds": "How long the mark stays. Default 10.",
        "dry_run": "When true, return the plan and do not change the screen.",
    },
    "pc_open_app": {
        "command": "Application command line to launch.",
        "hidden": "Launch on the hidden desktop. Default false.",
        "dry_run": "When true, return the plan and do not start the app.",
    },
}


def argument_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    """JSON Schema for ``fn``'s real parameters. No extra names are added."""
    from typing import get_type_hints

    signature = inspect.signature(fn)
    hints = get_type_hints(fn)
    help_for = _ARGUMENT_TEXT.get(fn.__name__, {})
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, param in signature.parameters.items():
        if name == "self" or param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        properties[name] = {
            "type": _json_type_name(hints.get(name, param.annotation)),
            "description": help_for.get(name, name),
        }
        if param.default is inspect.Parameter.empty:
            required.append(name)
    published: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        published["required"] = required
    unknown = set(help_for) - set(properties)
    if unknown:
        raise RuntimeError(f"{fn.__name__} describes unknown parameters: {sorted(unknown)}")
    return published


def _json_type_name(annotation: Any) -> str:
    origin = get_origin(annotation)
    if origin in (Union, getattr(__import__("types"), "UnionType", Union)):
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        annotation = args[0] if args else str
    if annotation is str:
        return "string"
    if annotation is bool:
        return "boolean"
    if annotation is int:
        return "integer"
    if annotation is float:
        return "number"
    return "string"


def _visible_call(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Log ``tools/call <name>`` on uvicorn's logger so it shows in the server terminal."""
    import logging

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        logging.getLogger("uvicorn.error").info("tools/call %s", fn.__name__)
        print(f"tools/call {fn.__name__}", flush=True)
        return fn(*args, **kwargs)

    wrapped.__name__ = fn.__name__
    wrapped.__doc__ = fn.__doc__
    wrapped.__annotations__ = dict(getattr(fn, "__annotations__", {}))
    wrapped.__signature__ = inspect.signature(fn)  # type: ignore[attr-defined]
    return wrapped


def _advertise_tools_only(server: Any) -> None:
    """``initialize`` capabilities are exactly ``{"tools": {}}``.

    Prompt and resource handlers are registered by the SDK even when this
    process has none. Advertising them, or ``tools.listChanged``, is not a
    tool list. Clients that do not see a tools object never call ``tools/list``.
    """
    from mcp_types import ToolsCapability

    low = server._lowlevel_server
    original = low.get_capabilities

    def get_capabilities(*args: Any, **kwargs: Any) -> Any:
        caps = original(*args, **kwargs)
        caps.experimental = None
        caps.logging = None
        caps.prompts = None
        caps.resources = None
        caps.completions = None
        caps.tasks = None
        caps.tools = ToolsCapability()
        return caps

    low.get_capabilities = get_capabilities


def build_server() -> Any:
    """An MCP server whose tools/list is exactly ``registered_tools``.

    OAuth stays on. Unauthenticated ``/mcp`` is 401. A bearer token from
    ``/token`` is what ``tools/list`` accepts. ``initialize`` advertises
    ``capabilities.tools`` and nothing else.
    """
    try:
        from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
        from mcp.server.mcpserver import MCPServer
    except ImportError as exc:
        raise RuntimeError(
            "The PC control listener needs the mcp package (2.x). "
            "Install it with: python -m pip install 'mcp>=2'"
        ) from exc
    from . import __version__
    from .oauth import LocalDesktopOAuth, public_origin

    origin = public_origin()
    provider = LocalDesktopOAuth()
    server = MCPServer(
        "desktop-agent-pc",
        version=__version__,
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
        server.add_tool(_visible_call(fn), structured_output=False)
        tool = server._tool_manager.get_tool(fn.__name__)
        if tool is None:
            raise RuntimeError(f"{fn.__name__} was not registered")
        tool.parameters = argument_schema(fn)
        if not (tool.description or "").strip():
            tool.description = tool.name
    _advertise_tools_only(server)
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


def _header(headers: list[tuple[bytes, bytes]], name: bytes) -> str | None:
    for key, value in headers:
        if key.lower() == name:
            return value.decode("latin-1")
    return None


def _set_header(headers: list[tuple[bytes, bytes]], name: bytes, value: bytes) -> list[tuple[bytes, bytes]]:
    kept = [(key, item) for key, item in headers if key.lower() != name]
    kept.append((name, value))
    return kept


def _drop_header(headers: list[tuple[bytes, bytes]], name: bytes) -> list[tuple[bytes, bytes]]:
    return [(key, item) for key, item in headers if key.lower() != name]


def _live_session_id(manager: Any) -> str | None:
    instances = getattr(manager, "_server_instances", {})
    if not instances:
        return None
    return next(reversed(instances))


def _keep_process_session(manager: Any, path: str) -> None:
    """Do not end the session when initialize or tools/list finishes.

    A client that sees the session terminate keeps the tool list and never
    opens tools/call. A later POST with no ``mcp-session-id`` is attached to
    the session this process already initialized. A stale id from an earlier
    process is dropped so it does not 404.
    """
    original = manager.asgi_app

    async def asgi_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "http" and scope.get("path", "").rstrip("/") == path.rstrip("/"):
            headers = list(scope.get("headers") or [])
            current = _header(headers, b"mcp-session-id")
            instances = manager._server_instances
            live = _live_session_id(manager)
            if live is not None and (current is None or current not in instances):
                headers = _set_header(headers, b"mcp-session-id", live.encode("ascii"))
                scope = dict(scope)
                scope["headers"] = headers
            elif live is None and current is not None:
                scope = dict(scope)
                scope["headers"] = _drop_header(headers, b"mcp-session-id")
        await original(scope, receive, send)

    manager.asgi_app = asgi_app


def build_http_app(host: str = HOST, path: str = HTTP_PATH) -> Any:
    """One Starlette app, one ``StreamableHTTPSessionManager``, for the process.

    ``streamable_http_app`` is called once. Its Starlette lifespan is that
    manager's ``run()``, entered when uvicorn starts and left when it stops.
    Requests do not build another manager.

    JSON responses stay on. The session is not stateless: it is not terminated
    after initialize or tools/list, so a later tools/call is still served.
    Requests omit ``mcp-session-id`` and still reach that session.
    DNS-rebinding protection is off, the same way a tunneled host such as
    ``aetherbridge.a.pinggy.link`` is allowed through to Miles Memory.
    """
    from mcp.server.transport_security import TransportSecuritySettings

    server = build_server()
    app = server.streamable_http_app(
        streamable_http_path=path,
        json_response=True,
        stateless_http=False,
        session_idle_timeout=None,
        host=host,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    _install_confirm_authorize(app, server.pc_oauth)
    manager = server.session_manager
    if manager.stateless or not manager.json_response or manager.session_idle_timeout is not None:
        raise RuntimeError("PC control listener must keep one JSON session for the process")
    _keep_process_session(manager, path)
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
