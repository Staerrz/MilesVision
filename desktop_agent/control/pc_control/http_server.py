"""Streamable HTTP MCP listener for the registered ``pc_*`` bridge tools.

Run ``python -m pc_control.server`` from ``desktop_agent/control`` or from
``desktop_agent``. Both load this package. The second directory uses the shim
at ``desktop_agent/pc_control``.
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
    stay off this listener. MCP ``tools/list`` publishes these under the
    original short names (``click``, ``type``, ...) and keeps ``pc_*`` as aliases.
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


def listed_names() -> tuple[str, ...]:
    """Names ``tools/list`` returns.

    The original PC-Control names come first, so a toolkit trigger for
    ``click`` or ``type`` matches. ``pc_*`` follows as an alias of the same
    function, so a client that still looks up ``pc_click`` does not miss it.
    ``mouse_click`` and ``keyboard_type`` are not in this list.
    """
    from desktop_agent.bridge.pc import SOURCE_NAMES

    short = tuple(SOURCE_NAMES)
    return short + tuple(f"pc_{name}" for name in short)


def bridge_callable(listed_name: str) -> Callable[..., Any]:
    """The ``pc_*`` bridge function a listed MCP name runs."""
    source = listed_name[3:] if listed_name.startswith("pc_") else listed_name
    for fn in registered_tools():
        if fn.__name__ == f"pc_{source}":
            return fn
    raise RuntimeError(f"{listed_name} is not a PC control tool")


# What the model reads. The first sentence is the exact argument names.
# ``confirm`` is a PC-Control parameter this bridge does not accept, so it is
# not listed and not added to the schema.
_TITLES: dict[str, str] = {
    "windows": "Windows",
    "look": "Look",
    "click": "Click",
    "type": "Type",
    "drag": "Drag",
    "key": "Key",
    "scroll": "Scroll",
    "read": "Read",
    "show": "Show",
    "open_app": "Open app",
}

_TOOL_TEXT: dict[str, str] = {
    "pc_windows": "List open windows as hwnd, process, and title, most recent first. filter matches the title or process. Empty lists every window.",
    "pc_look": "See a window without focusing it. window is a title substring or hwnd. mode defaults to auto. find limits the elements, including those out of view. wait is seconds to poll.",
    "pc_click": "Click an element id from look, its exact name, or x,y pixels of the last image. right and double default to false. dry_run true returns the plan and does not change the screen.",
    "pc_type": "Type into an element id from look, or its name. replace true replaces the current text. dry_run true returns the plan and does not change the screen.",
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
        "window": "Window title substring or hwnd from windows.",
        "mode": "How to look. Default auto.",
        "find": "Element text to locate. Empty returns the whole look.",
        "wait": "Seconds to poll while finding. Default 0.",
    },
    "pc_click": {
        "window": "Window title substring or hwnd.",
        "target": "Element id from look.",
        "right": "Right click. Default false.",
        "double": "Double click. Default false.",
        "dry_run": "When true, return the plan and do not change the screen.",
    },
    "pc_type": {
        "window": "Window title substring or hwnd.",
        "target": "Element id from look.",
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


def _visible_call(fn: Callable[..., Any], listed_name: str) -> Callable[..., Any]:
    """Log ``tools/call <listed name>`` so it shows in the server terminal."""
    import logging

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        logging.getLogger("uvicorn.error").info("tools/call %s", listed_name)
        print(f"tools/call {listed_name}", flush=True)
        return fn(*args, **kwargs)

    wrapped.__name__ = listed_name
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
    from .oauth import LocalDesktopOAuth, public_origin, tool_scopes

    origin = public_origin()
    provider = LocalDesktopOAuth()
    scopes = tool_scopes()
    server = MCPServer(
        "desktop-agent-pc",
        version=__version__,
        auth=AuthSettings(
            issuer_url=origin,
            resource_server_url=origin,
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=scopes,
                default_scopes=scopes,
            ),
            required_scopes=[],
            validate_token_resource=False,
        ),
        auth_server_provider=provider,
    )
    server.pc_oauth = provider
    for listed_name in listed_names():
        fn = bridge_callable(listed_name)
        source = listed_name[3:] if listed_name.startswith("pc_") else listed_name
        title = _TITLES[source]
        description = tool_description(fn)
        server.add_tool(
            _visible_call(fn, listed_name),
            name=listed_name,
            title=title,
            description=description,
            structured_output=False,
        )
        tool = server._tool_manager.get_tool(listed_name)
        if tool is None:
            raise RuntimeError(f"{listed_name} was not registered")
        tool.parameters = argument_schema(fn)
        tool.description = description
        tool.title = title
        if not tool.name or not tool.title or not tool.description or not tool.parameters.get("properties"):
            raise RuntimeError(f"{listed_name} is missing name, title, description, or inputSchema")
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


def _install_tool_scope_metadata(app: Any) -> None:
    """Publish tool scopes on the protected-resource document.

    The SDK copies ``required_scopes`` into that document. Those stay empty so
    a bearer token is not turned into 403. The document itself still lists
    ``windows``, ``look``, ``click``, and ``type`` so a client does not treat
    the tool permission set as omitted.
    """
    from urllib.parse import urlparse

    from mcp.server.auth.handlers.metadata import ProtectedResourceMetadataHandler
    from mcp.server.auth.routes import build_resource_metadata_url, cors_middleware
    from mcp.shared.auth import ProtectedResourceMetadata
    from pydantic import AnyHttpUrl
    from starlette.routing import Route

    from .oauth import public_origin, tool_scopes

    origin = AnyHttpUrl(public_origin())
    metadata = ProtectedResourceMetadata(
        resource=origin,
        authorization_servers=[origin],
        scopes_supported=tool_scopes(),
        resource_name="PC control",
    )
    endpoint = cors_middleware(ProtectedResourceMetadataHandler(metadata).handle, ["GET", "OPTIONS"])
    path = urlparse(str(build_resource_metadata_url(origin))).path
    replacement = Route(path, endpoint=endpoint, methods=["GET", "OPTIONS"])
    routes = app.router.routes
    for index, route in enumerate(routes):
        if getattr(route, "path", None) == path:
            routes[index] = replacement
            return
    routes.insert(0, replacement)


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


# The SDK answers ``Invalid Origin header`` with HTTP 403. That check can still
# run after Host DNS-rebinding protection is off. A missing Origin is allowed.
# Sesame's browser sends ``Origin: https://sesameai.app`` to the public host.
# There is no handshake secret to paste into Sesame.
_SESAME_ORIGIN = "https://sesameai.app"


def accepted_browser_origins() -> frozenset[str]:
    """Origin values that must not be HTTP 403 on this listener."""
    from .oauth import DEFAULT_PUBLIC_ORIGIN, public_origin

    found = {
        _SESAME_ORIGIN,
        DEFAULT_PUBLIC_ORIGIN.rstrip("/"),
        public_origin().rstrip("/"),
    }
    with_port: set[str] = set()
    for origin in found:
        with_port.add(origin)
        host = origin.split("://", 1)[-1]
        if ":" not in host:
            with_port.add(f"{origin}:443")
    return frozenset(with_port)


def _drop_accepted_origin(scope: dict[str, Any]) -> dict[str, Any]:
    """Remove an allowlisted Origin so the SDK cannot answer 403 for it."""
    if scope.get("type") != "http":
        return scope
    headers = list(scope.get("headers") or [])
    origin = _header(headers, b"origin")
    if origin is None:
        return scope
    allowed = {item.lower() for item in accepted_browser_origins()}
    if origin.rstrip("/").lower() not in allowed:
        return scope
    scope = dict(scope)
    scope["headers"] = _drop_header(headers, b"origin")
    return scope


class _AdvertiseToolScopes:
    """Tell a client which tool scopes to request.

    ``WWW-Authenticate`` on 401 otherwise has no ``scope``. A client then
    treats the protected-resource list as empty and can hide tools after a
    200 initialize. Unauthenticated ``POST /mcp`` stays 401.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        async def send_challenge(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start" and message.get("status") == 401:
                message = dict(message)
                message["headers"] = _with_tool_scope(list(message.get("headers") or []))
            await send(message)

        await self.app(scope, receive, send_challenge)


def _with_tool_scope(headers: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    from .oauth import tool_scopes

    parameter = f'scope="{" ".join(tool_scopes())}"'.encode()
    updated: list[tuple[bytes, bytes]] = []
    found = False
    for key, value in headers:
        if key.lower() == b"www-authenticate":
            found = True
            if b"scope=" not in value:
                value = value + b", " + parameter
        updated.append((key, value))
    if not found:
        updated.append((b"www-authenticate", b"Bearer " + parameter))
    return updated


class _PassthroughAcceptedOrigin:
    """Run before auth and the SDK transport.

    Unauthenticated ``POST /mcp`` still reaches the bearer check and stays
    401. ``Origin`` is already gone, so a later Origin check cannot turn that
    request, or a bearer ``initialize``, into 403.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        await self.app(_drop_accepted_origin(scope), receive, send)


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
            scope = _drop_accepted_origin(scope)
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
    ``Origin`` is still allowlisted and removed for Sesame
    (``https://sesameai.app``) and that public origin. The SDK's Origin check
    is the HTTP 403, and it can run after the Host check is off. No handshake
    secret is required.
    """
    from urllib.parse import urlsplit

    from mcp.server.transport_security import TransportSecuritySettings

    from .oauth import DEFAULT_PUBLIC_ORIGIN, public_origin

    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    for origin in (DEFAULT_PUBLIC_ORIGIN, public_origin()):
        hostname = urlsplit(origin).hostname
        if hostname and hostname not in hosts:
            hosts.append(hostname)
            hosts.append(f"{hostname}:*")
    server = build_server()
    app = server.streamable_http_app(
        streamable_http_path=path,
        json_response=True,
        stateless_http=False,
        session_idle_timeout=None,
        host=host,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
            allowed_hosts=hosts,
            allowed_origins=sorted(accepted_browser_origins()),
        ),
    )
    app.add_middleware(_AdvertiseToolScopes)
    app.add_middleware(_PassthroughAcceptedOrigin)
    _install_confirm_authorize(app, server.pc_oauth)
    _install_tool_scope_metadata(app)
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
