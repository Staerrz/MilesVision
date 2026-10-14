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


# What the model reads. The first sentence is the exact argument names.
# ``confirm`` is a PC-Control parameter this bridge does not accept, so it is
# not listed and not added to the schema.
_TOOL_TEXT: dict[str, str] = {
    "pc_windows": "List open windows as hwnd, process, and title, most recent first. filter matches the title or process. Empty lists every window.",
    "pc_look": "See a window without focusing it. window is a title substring or hwnd. mode defaults to auto. find limits the elements, including those out of view. wait is seconds to poll.",
    "pc_click": "Click an element id from pc_look, its exact name, or x,y pixels of the last image. right and double default to false. dry_run true returns the plan and does not change the screen.",
    "pc_type": "Type into an element id from pc_look, or its name. replace true replaces the current text. dry_run true returns the plan and does not change the screen.",
    "pc_drag": "Drag through image points. shape defaults to path. right defaults to false. dry_run true returns the plan and does not change the screen.",
    "pc_key": "Send a key or the app's own shortcut. name is enter, tab, esc, arrows, or a shortcut such as ctrl+s. dry_run true returns the plan and does not change the screen.",
    "pc_scroll": "Scroll the window or an element id. direction defaults to down. amount defaults to 1. dry_run true returns the plan and does not change the screen.",
    "pc_read": "Read the window's document, page, or editor, or one element. target empty reads the window. start defaults to 0. length defaults to 6000. find limits the lines.",
    "pc_show": "Mark an element id so the user can see it. Nothing is clicked. label and seconds default to empty and 10. dry_run true returns the plan and does not change the screen.",
    "pc_open_app": "Launch an app minimized and unfocused. command is the program and its arguments. hidden defaults to false. dry_run true returns the plan and does not start the app.",
}

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
    """JSON Schema for ``fn``'s real parameters. No extra names are added.

    ``additionalProperties`` is left unset. A closed schema rejects a normal
    agent call before it is posted when the model also sends a name this
    function does not take, such as PC-Control's ``confirm``.
    """
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
    published: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        published["required"] = required
    unknown = set(help_for) - set(properties)
    if unknown:
        raise RuntimeError(f"{fn.__name__} describes unknown parameters: {sorted(unknown)}")
    missing = set(properties) - set(help_for)
    if fn.__name__ in _ARGUMENT_TEXT and missing:
        raise RuntimeError(f"{fn.__name__} is missing argument text: {sorted(missing)}")
    return published


def tool_description(fn: Callable[..., Any]) -> str:
    """The description the model sees, leading with the exact argument names."""
    names = ", ".join(argument_schema(fn)["properties"])
    behavior = _TOOL_TEXT.get(fn.__name__, (fn.__doc__ or fn.__name__).strip())
    return f"Argument names: {names}. {behavior}"


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
        tool.description = tool_description(fn)
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


# Handshake revisions return ``Mcp-Session-Id``. ``2026-07-28`` is a stateless
# one-shot and does not, so a client that already listed tools never posts
# ``tools/call``.
_HANDSHAKE_VERSIONS = frozenset({"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"})


def _keep_process_session(manager: Any, path: str) -> None:
    """Keep the session initialize created, and return its id.

    ``initialize`` answers with ``Mcp-Session-Id``. That id stays valid after
    ``tools/list``. A later ``tools/call`` that sends it is handled. A POST
    with no session id is attached to the same session. A protocol version
    that would take the stateless path is served on the handshake path so the
    response still carries the id. A stale id from an earlier process is
    dropped only when this process has no session yet, so initialize can open
    one instead of answering 404.
    """
    original = manager.asgi_app

    async def asgi_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "http" and scope.get("path", "").rstrip("/") == path.rstrip("/"):
            if scope.get("method") == "OPTIONS":
                await _send_cors(send, 204)
                return
            headers = list(scope.get("headers") or [])
            version = _header(headers, b"mcp-protocol-version")
            if version is not None and version not in _HANDSHAKE_VERSIONS:
                headers = _set_header(headers, b"mcp-protocol-version", b"2025-11-25")
            current = _header(headers, b"mcp-session-id")
            instances = manager._server_instances
            live = _live_session_id(manager)
            if live is not None and (current is None or current not in instances):
                headers = _set_header(headers, b"mcp-session-id", live.encode("ascii"))
            elif live is None and current is not None:
                headers = _drop_header(headers, b"mcp-session-id")
            scope = dict(scope)
            scope["headers"] = headers

            async def send_session(message: dict[str, Any]) -> None:
                if message.get("type") == "http.response.start":
                    message = dict(message)
                    message["headers"] = _expose_session_id(list(message.get("headers") or []))
                await send(message)

            await original(scope, receive, send_session)
            return
        await original(scope, receive, send)

    manager.asgi_app = asgi_app


def _expose_session_id(headers: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    """Publish the session id under the spec name and let a browser read it."""
    session = _header(headers, b"mcp-session-id")
    if session:
        headers.append((b"Mcp-Session-Id", session.encode("ascii")))
    if _header(headers, b"access-control-expose-headers") is None:
        headers.append((b"Access-Control-Expose-Headers", b"Mcp-Session-Id"))
    return headers


async def _send_cors(send: Any, status: int) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"access-control-allow-origin", b"*"),
                (b"access-control-allow-methods", b"GET, POST, DELETE, OPTIONS"),
                (
                    b"access-control-allow-headers",
                    b"Authorization, Content-Type, Accept, Mcp-Session-Id, mcp-protocol-version",
                ),
                (b"access-control-expose-headers", b"Mcp-Session-Id"),
                (b"content-length", b"0"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": b""})


def build_http_app(host: str = HOST, path: str = HTTP_PATH) -> Any:
    """One Starlette app, one ``StreamableHTTPSessionManager``, for the process.

    ``streamable_http_app`` is called once. Its Starlette lifespan is that
    manager's ``run()``, entered when uvicorn starts and left when it stops.
    Requests do not build another manager.

    JSON responses stay on. ``initialize`` sets ``Mcp-Session-Id`` and that
    session is not terminated after initialize or tools/list. A later
    tools/call that sends the id is served. A request that omits the id still
    reaches the same session.
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
