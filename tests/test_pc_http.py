"""The PC listener stays up and tools/list is the registered pc_* bridge tools."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

from desktop_agent.bridge.pc import SOURCE_NAMES
from desktop_agent.control.pc_control.http_server import HOST, HTTP_PATH, PORT, listed_names, registered_tools

CONTROL = Path(__file__).resolve().parents[1] / "desktop_agent" / "control"
EXPECTED = listed_names()


def test_one_session_manager_for_the_process_lifespan() -> None:
    import anyio

    from desktop_agent.control.pc_control.http_server import build_http_app

    app = build_http_app()
    manager = app.state.pc_session_manager
    assert manager.stateless is False
    assert manager.json_response is True
    assert manager.session_idle_timeout is None
    assert manager._task_group is None

    async def enter_once() -> None:
        async with app.router.lifespan_context(app):
            assert manager._task_group is not None

    anyio.run(enter_once)
    assert manager._task_group is None


def test_registered_names_match_the_bridge() -> None:
    names = tuple(fn.__name__ for fn in registered_tools())
    assert names == tuple(f"pc_{name}" for name in SOURCE_NAMES)
    assert listed_names()[: len(SOURCE_NAMES)] == tuple(SOURCE_NAMES)
    assert "click" in listed_names()
    assert "type" in listed_names()
    assert "pc_click" in listed_names()
    assert "mouse_click" not in listed_names()
    assert "keyboard_type" not in listed_names()
    assert "memory_recall" not in names


def test_listener_lists_pc_tools_and_keeps_dry_run(tmp_path: Path) -> None:
    port = 18770
    site = tmp_path / "site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(
        textwrap.dedent(
            """
            import ctypes, sys, types

            class _Win:
                def __getattr__(self, name):
                    return self
                def __call__(self, *args, **kwargs):
                    return self

            ctypes.windll = _Win()
            ctypes.WinDLL = lambda *args, **kwargs: _Win()

            def _mod(name):
                module = types.ModuleType(name)
                sys.modules[name] = module
                return module

            auto = _mod("uiautomation")
            auto.UIAutomationInitializerInThread = lambda *args, **kwargs: _Win()
            for missing in ("win32gui", "win32process", "win32api", "win32con", "cv2", "numpy"):
                _mod(missing)

            # The installed SDK skips Origin when DNS-rebinding protection is off.
            # Sesame still gets HTTP 403 from that check on builds that keep
            # running it. Force it here, with an empty Origin allowlist, so a
            # request that still carries Origin: https://sesameai.app fails.
            import mcp.server.transport_security as _ts

            _validate = _ts.TransportSecurityMiddleware.validate_request

            async def _origin_still_checked(self, request, is_post=False):
                saved = (
                    self.settings.enable_dns_rebinding_protection,
                    list(self.settings.allowed_origins),
                    list(self.settings.allowed_hosts),
                )
                self.settings.enable_dns_rebinding_protection = True
                self.settings.allowed_origins = []
                self.settings.allowed_hosts = [
                    "127.0.0.1:*",
                    "localhost:*",
                    "[::1]:*",
                    "aetherbridge.a.pinggy.link",
                    "aetherbridge.a.pinggy.link:*",
                ]
                try:
                    return await _validate(self, request, is_post=is_post)
                finally:
                    (
                        self.settings.enable_dns_rebinding_protection,
                        self.settings.allowed_origins,
                        self.settings.allowed_hosts,
                    ) = saved

            _ts.TransportSecurityMiddleware.validate_request = _origin_still_checked
            """
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(site) + os.pathsep + env.get("PYTHONPATH", "")
    env["PC_CONTROL_HTTP_PORT"] = str(port)
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "-m", "pc_control.server"],
        cwd=CONTROL,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.time() + 20
        output = ""
        while time.time() < deadline:
            if proc.poll() is not None:
                output += proc.stdout.read() if proc.stdout else ""
                raise AssertionError(f"listener exited {proc.returncode}: {output}")
            line = proc.stdout.readline() if proc.stdout else ""
            output += line
            if f"http://{HOST}:{port}{HTTP_PATH}" in output:
                break
        else:
            raise AssertionError(f"listener did not stay up: {output}")
        pinggy = _pinggy_oauth_roundtrip(port)
        assert pinggy["unauthenticated_status"] == 401
        assert pinggy["www_authenticate_has_metadata"]
        assert pinggy["token_route_status"] != 404
        assert pinggy["protected_resource_status"] == 200
        assert pinggy["tools"] == list(EXPECTED)
        assert pinggy["capabilities"].get("tools") == {}
        assert "prompts" not in pinggy["capabilities"]
        assert "resources" not in pinggy["capabilities"]
        assert pinggy["sesame_authorize_status"] == 200
        assert pinggy["sesame_token_before_code"] == 401
        assert pinggy["sesame_access_token"]
        visible = ("windows", "look", "click", "type")
        for name in visible:
            assert name in pinggy["tools"]
            fields = pinggy["tool_fields"][name]
            assert fields["title"] and fields["description"] and fields["inputSchema"]
        for scopes in (
            pinggy["token_scopes"],
            pinggy["sesame_scopes"],
            pinggy["protected_scopes"],
            pinggy["authorization_scopes"],
        ):
            assert list(scopes[:4]) == list(visible)
            for name in visible:
                assert name in scopes
        assert 'scope="windows look click type' in pinggy["www_authenticate"]
        names, click, refused = asyncio.run(_listed_and_called(port, pinggy["access_token"]))
        assert names == list(EXPECTED)
        assert click["ok"] is True
        assert click["outcome"]["dry_run"] is True
        assert click["outcome"]["executed"] is False
        assert refused["ok"] is False
        assert "VISION_ALLOW_SCREEN_CONTROL" in refused["outcome"]["reason"]
        rest = _drain(proc)
        log = output + rest
        assert "tools/call click" in rest
        assert "Terminating session: None" not in log
        ended = log.find("Terminating session:")
        if ended != -1:
            assert ended > log.find("tools/call click")
        assert proc.poll() is None
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


async def _listed_and_called(port: int, access_token: str):
    import httpx2
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    url = f"http://{HOST}:{port}{HTTP_PATH}"
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {access_token}"}) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                names = [tool.name for tool in listed.tools]
                click = await session.call_tool(
                    "click",
                    {"window": "Notepad", "target": "12", "dry_run": True},
                )
                refused = await session.call_tool(
                    "open_app",
                    {"command": "notepad.exe", "dry_run": False},
                )
    return names, _payload(click), _payload(refused)


def _payload(result) -> dict:
    import json

    if getattr(result, "structuredContent", None):
        return result.structuredContent
    if getattr(result, "structured_content", None):
        return result.structured_content
    text = ""
    for block in result.content:
        text += getattr(block, "text", "") or ""
    return json.loads(text)


def _pinggy_oauth_roundtrip(port: int) -> dict:
    """Host aetherbridge.a.pinggy.link must be 401 on /mcp, not 421, and /token must exist."""
    import base64
    import hashlib
    import http.client
    import json
    import secrets
    from urllib.parse import parse_qs, urlencode, urlparse

    from desktop_agent.control.pc_control.oauth import DEFAULT_PUBLIC_ORIGIN, resource_metadata_url

    tunnel_host = "aetherbridge.a.pinggy.link"
    metadata = resource_metadata_url(DEFAULT_PUBLIC_ORIGIN)

    def request(
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        posted = http.client.HTTPConnection(HOST, port, timeout=5)
        sent = {"Host": tunnel_host, "Origin": "https://sesameai.app"}
        if headers:
            sent.update(headers)
        posted.request(method, path, body=body, headers=sent)
        response = posted.getresponse()
        status = response.status
        header_map = {name.lower(): value for name, value in response.getheaders()}
        raw = response.read()
        posted.close()
        return status, header_map, raw

    unauthenticated_status, unauthenticated_headers, _raw = request(
        "POST",
        HTTP_PATH,
        body=json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "miles", "version": "0"},
                },
            }
        ).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    if unauthenticated_status != 401 or b"Invalid Origin" in _raw:
        raise AssertionError(f"unauthenticated POST /mcp {unauthenticated_status}: {_raw!r}")
    token_route_status, _token_headers, _token_raw = request(
        "POST",
        "/token",
        body=b"",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    protected_status, _protected_headers, protected_body = request("GET", "/.well-known/oauth-protected-resource")
    if protected_status != 200:
        raise AssertionError(f"protected resource {protected_status}: {protected_body!r}")
    protected_scopes = json.loads(protected_body.decode()).get("scopes_supported") or []
    as_status, _as_headers, as_body = request("GET", "/.well-known/oauth-authorization-server")
    if as_status != 200:
        raise AssertionError(f"authorization server {as_status}: {as_body!r}")
    authorization_scopes = json.loads(as_body.decode()).get("scopes_supported") or []

    registered_status, _registered_headers, registered_body = request(
        "POST",
        "/register",
        body=json.dumps(
            {
                "redirect_uris": ["http://127.0.0.1/callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "client_secret_post",
                "client_name": "miles",
            }
        ).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    if registered_status != 201:
        raise AssertionError(f"register {registered_status}: {registered_body!r}")
    client = json.loads(registered_body.decode())
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client["client_id"],
            "redirect_uri": "http://127.0.0.1/callback",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "miles",
            "resource": DEFAULT_PUBLIC_ORIGIN,
        }
    )
    authorize_status, _authorize_headers, authorize_body = request("GET", f"/authorize?{query}")
    if authorize_status != 200 or b"Allow" not in authorize_body:
        raise AssertionError(f"authorize {authorize_status}: {authorize_body!r}")
    approved_status, approved_headers, approved_body = request(
        "POST",
        "/authorize",
        body=urlencode(
            {
                "response_type": "code",
                "client_id": client["client_id"],
                "redirect_uri": "http://127.0.0.1/callback",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "miles",
                "resource": DEFAULT_PUBLIC_ORIGIN,
                "decision": "approve",
            }
        ).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if approved_status != 302:
        raise AssertionError(f"approve {approved_status}: {approved_body!r}")
    code = parse_qs(urlparse(approved_headers["location"]).query)["code"][0]
    issued_status, _issued_headers, issued_body = request(
        "POST",
        "/token",
        body=urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://127.0.0.1/callback",
                "client_id": client["client_id"],
                "client_secret": client["client_secret"],
                "code_verifier": verifier,
                "resource": DEFAULT_PUBLIC_ORIGIN,
            }
        ).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    if issued_status != 200:
        raise AssertionError(f"token {issued_status}: {issued_body!r}")
    issued = json.loads(issued_body.decode())
    access_token = issued["access_token"]
    token_scopes = (issued.get("scope") or "").split()
    bearer = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}",
        "mcp-protocol-version": "2025-11-25",
    }
    init_status, init_headers, init_body = request(
        "POST",
        HTTP_PATH,
        body=json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "miles", "version": "0"},
                },
            }
        ).encode(),
        headers=bearer,
    )
    if init_status == 403 or b"Invalid Origin" in init_body:
        raise AssertionError(f"initialize rejected Origin: {init_status} {init_body!r}")
    if init_status != 200 or "application/json" not in init_headers.get("content-type", ""):
        raise AssertionError(f"initialize {init_status} {init_headers.get('content-type')}: {init_body!r}")
    capabilities = json.loads(init_body.decode())["result"]["capabilities"]
    if not isinstance(capabilities.get("tools"), dict):
        raise AssertionError(f"initialize capabilities {capabilities!r}")
    session_id = init_headers.get("mcp-session-id")
    if not session_id:
        raise AssertionError(f"initialize did not set mcp-session-id: {init_headers!r}")
    with_session = {**bearer, "mcp-session-id": session_id}
    request(
        "POST",
        HTTP_PATH,
        body=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode(),
        headers=with_session,
    )
    listed_status, _listed_headers, listed_body = request(
        "POST",
        HTTP_PATH,
        body=json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}).encode(),
        headers=with_session,
    )
    if listed_status != 200:
        raise AssertionError(f"tools/list {listed_status}: {listed_body!r}")
    if "application/json" not in _listed_headers.get("content-type", ""):
        raise AssertionError(f"tools/list content-type {_listed_headers.get('content-type')!r}")
    if listed_body.startswith(b"event:") or listed_body.startswith(b":"):
        raise AssertionError(f"tools/list was SSE: {listed_body[:200]!r}")
    listed = json.loads(listed_body.decode())
    from desktop_agent.control.pc_control.http_server import argument_schema, bridge_callable, tool_description

    by_name = {tool["name"]: tool for tool in listed["result"]["tools"]}
    for name in EXPECTED:
        tool = by_name[name]
        if not tool.get("title") or not tool.get("description") or not tool.get("inputSchema"):
            raise AssertionError(f"{name} missing title, description, or inputSchema: {tool!r}")
        schema = tool.get("inputSchema")
        fn = bridge_callable(name)
        expected = argument_schema(fn)
        if schema != expected:
            raise AssertionError(f"{name} inputSchema {schema!r} != {expected!r}")
        if not schema.get("properties"):
            raise AssertionError(f"{name} inputSchema has no arguments")
        if "confirm" in schema["properties"]:
            raise AssertionError(f"{name} invented confirm")
        if "additionalProperties" in schema:
            raise AssertionError(f"{name} inputSchema is closed: {schema!r}")
        description = tool.get("description") or ""
        if description != tool_description(fn):
            raise AssertionError(f"{name} description {description!r}")
        for arg in schema["properties"]:
            if arg not in description:
                raise AssertionError(f"{name} description omits {arg}: {description!r}")
    called_status, called_headers, called_body = request(
        "POST",
        HTTP_PATH,
        body=json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "click",
                    "arguments": {"window": "Notepad", "target": "12", "dry_run": True, "confirm": False},
                },
            }
        ).encode(),
        headers=with_session,
    )
    if called_status == 404:
        raise AssertionError(f"tools/call 404 for session {session_id}: {called_body!r}")
    if called_status != 200 or "application/json" not in called_headers.get("content-type", ""):
        raise AssertionError(f"tools/call {called_status}: {called_body!r}")
    if called_headers.get("mcp-session-id") != session_id:
        raise AssertionError(f"tools/call session {called_headers.get('mcp-session-id')!r} != {session_id}")
    called = json.loads(called_body.decode())
    called_text = json.dumps(called)
    if "dry_run" not in called_text or called.get("error"):
        raise AssertionError(f"tools/call did not reach the bridge: {called!r}")
    alias_status, _alias_headers, alias_body = request(
        "POST",
        HTTP_PATH,
        body=json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "pc_click",
                    "arguments": {"window": "Notepad", "target": "12", "dry_run": True},
                },
            }
        ).encode(),
        headers=with_session,
    )
    if alias_status != 200 or b"dry_run" not in alias_body:
        raise AssertionError(f"pc_click alias {alias_status}: {alias_body!r}")
    modern_status, modern_headers, modern_body = request(
        "POST",
        HTTP_PATH,
        body=json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2026-07-28",
                    "capabilities": {},
                    "clientInfo": {"name": "miles", "version": "0"},
                },
            }
        ).encode(),
        headers={**bearer, "mcp-protocol-version": "2026-07-28"},
    )
    if modern_status != 200 or not modern_headers.get("mcp-session-id"):
        raise AssertionError(f"2026 initialize {modern_status} {modern_headers!r}: {modern_body!r}")
    sesame = _sesame_unknown_client(request)
    www = unauthenticated_headers.get("www-authenticate", "")
    return {
        "unauthenticated_status": unauthenticated_status,
        "www_authenticate_has_metadata": f'resource_metadata="{metadata}"' in www,
        "token_route_status": token_route_status,
        "protected_resource_status": protected_status,
        "protected_scopes": protected_scopes,
        "authorization_scopes": authorization_scopes,
        "token_scopes": token_scopes,
        "access_token": access_token,
        "tools": [tool["name"] for tool in listed["result"]["tools"]],
        "tool_fields": {
            name: {
                "title": by_name[name].get("title"),
                "description": by_name[name].get("description"),
                "inputSchema": by_name[name].get("inputSchema"),
            }
            for name in ("windows", "look", "click", "type")
        },
        "capabilities": capabilities,
        "sesame_authorize_status": sesame["authorize_status"],
        "sesame_token_before_code": sesame["token_before_code"],
        "sesame_access_token": sesame["access_token"],
        "sesame_scopes": sesame["scopes"],
        "www_authenticate": www,
    }


def _sesame_unknown_client(request) -> dict:
    """The Sesame GET has no prior /register. It must be the confirm page, then a token."""
    import base64
    import hashlib
    import json
    import secrets
    from urllib.parse import parse_qs, urlencode, urlparse

    client_id = "fGTSoieUnojA4VEH36u1nRV5mBtM57E4"
    redirect_uri = "https://sesameai.app/api/oauth/external-mcp/callback"
    resource = "https://aetherbridge.a.pinggy.link/mcp"
    state = "v1.gAAAA" + ("A" * 2048)
    exact = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": "GEjhW7wZVT6lHluVzSCg5wnCdezdydgbnLeptwitwW0",
            "code_challenge_method": "S256",
            "resource": resource,
            "state": state,
        }
    )
    page_status, _page_headers, page_body = request("GET", f"/authorize?{exact}")
    if page_status != 200 or b"Allow" not in page_body or client_id.encode() not in page_body:
        raise AssertionError(f"sesame authorize {page_status}: {page_body[:300]!r}")
    if b"unknown client" in page_body.lower():
        raise AssertionError(page_body[:300])

    before_status, _before_headers, _before_body = request(
        "POST",
        "/token",
        body=urlencode(
            {
                "grant_type": "authorization_code",
                "code": "not-issued",
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "code_verifier": "a" * 64,
                "resource": resource,
            }
        ).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )

    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    approved_status, approved_headers, approved_body = request(
        "POST",
        "/authorize",
        body=urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "resource": resource,
                "state": state,
                "decision": "approve",
            }
        ).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if approved_status != 302:
        raise AssertionError(f"sesame approve {approved_status}: {approved_body!r}")
    code = parse_qs(urlparse(approved_headers["location"]).query)["code"][0]
    if parse_qs(urlparse(approved_headers["location"]).query)["state"][0] != state:
        raise AssertionError("state was dropped")
    issued_status, _issued_headers, issued_body = request(
        "POST",
        "/token",
        body=urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "code_verifier": verifier,
                "resource": resource,
            }
        ).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    if issued_status != 200:
        raise AssertionError(f"sesame token {issued_status}: {issued_body!r}")
    issued = json.loads(issued_body.decode())
    return {
        "authorize_status": page_status,
        "token_before_code": before_status,
        "access_token": issued["access_token"],
        "scopes": (issued.get("scope") or "").split(),
    }


def _drain(proc: subprocess.Popen[str]) -> str:
    """Read the listener pipe, including bytes ``readline`` already buffered.

    ``select`` on the text stream misses lines sitting in the ``BufferedReader``
    after the first ``readline`` prefetched them. A non-blocking ``readline``
    returns that buffer, then raises ``BlockingIOError`` when the pipe is empty.
    """
    import os

    if proc.stdout is None:
        return ""
    os.set_blocking(proc.stdout.fileno(), False)
    chunks: list[str] = []
    deadline = time.time() + 2
    while time.time() < deadline:
        try:
            line = proc.stdout.readline()
        except BlockingIOError:
            if "tools/call click" in "".join(chunks):
                break
            time.sleep(0.05)
            continue
        if line:
            chunks.append(line)
            continue
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    return "".join(chunks)


def test_sesame_origin_is_removed_before_the_sdk() -> None:
    from desktop_agent.control.pc_control.http_server import (
        _drop_accepted_origin,
        accepted_browser_origins,
        build_http_app,
    )

    origins = accepted_browser_origins()
    assert "https://sesameai.app" in origins
    assert "https://aetherbridge.a.pinggy.link" in origins
    scope = {
        "type": "http",
        "headers": [
            (b"host", b"aetherbridge.a.pinggy.link"),
            (b"origin", b"https://sesameai.app"),
        ],
    }
    dropped = _drop_accepted_origin(scope)
    assert all(key.lower() != b"origin" for key, _value in dropped["headers"])
    kept = _drop_accepted_origin(
        {
            "type": "http",
            "headers": [(b"origin", b"https://evil.example")],
        }
    )
    assert _header_value(kept, b"origin") == "https://evil.example"
    app = build_http_app()
    settings = app.state.pc_session_manager.security_settings
    assert settings.enable_dns_rebinding_protection is False
    assert "https://sesameai.app" in settings.allowed_origins
    assert "aetherbridge.a.pinggy.link" in settings.allowed_hosts


def _header_value(scope: dict, name: bytes) -> str | None:
    for key, value in scope["headers"]:
        if key.lower() == name:
            return value.decode()
    return None


def test_default_port_is_not_memory() -> None:
    assert PORT == 8770
    assert PORT != 8765
    assert HTTP_PATH == "/mcp"


def test_server_module_starts_from_control_and_desktop_agent(tmp_path: Path) -> None:
    """Both directories resolve ``python -m pc_control.server`` to the real listener."""
    real = CONTROL / "pc_control" / "server.py"
    shim = CONTROL.parent / "pc_control" / "server.py"
    assert real.is_file()
    assert shim.is_file()
    assert "desktop_agent.control.pc_control.server" in shim.read_text(encoding="utf-8")
    for cwd, port in ((CONTROL, 18781), (CONTROL.parent, 18782)):
        proc, output = _boot_listener(tmp_path / f"site-{port}", cwd, port)
        try:
            assert f"http://{HOST}:{port}{HTTP_PATH}" in output
            assert "ModuleNotFoundError" not in output
            assert proc.poll() is None
            status = _mcp_status(port)
            assert status == 401
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def _boot_listener(site: Path, cwd: Path, port: int) -> tuple[subprocess.Popen[str], str]:
    site.mkdir()
    (site / "sitecustomize.py").write_text(
        textwrap.dedent(
            """
            import ctypes, sys, types

            class _Win:
                def __getattr__(self, name):
                    return self
                def __call__(self, *args, **kwargs):
                    return self

            ctypes.windll = _Win()
            ctypes.WinDLL = lambda *args, **kwargs: _Win()

            def _mod(name):
                module = types.ModuleType(name)
                sys.modules[name] = module
                return module

            auto = _mod("uiautomation")
            auto.UIAutomationInitializerInThread = lambda *args, **kwargs: _Win()
            for missing in ("win32gui", "win32process", "win32api", "win32con", "cv2", "numpy"):
                _mod(missing)
            """
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(site) + os.pathsep + env.get("PYTHONPATH", "")
    env["PC_CONTROL_HTTP_PORT"] = str(port)
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "-m", "pc_control.server"],
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output = ""
    deadline = time.time() + 20
    while time.time() < deadline:
        if proc.poll() is not None:
            output += proc.stdout.read() if proc.stdout else ""
            raise AssertionError(f"{cwd} exited {proc.returncode}: {output}")
        line = proc.stdout.readline() if proc.stdout else ""
        output += line
        if f"http://{HOST}:{port}{HTTP_PATH}" in output:
            return proc, output
    raise AssertionError(f"{cwd} did not stay up: {output}")


def _mcp_status(port: int) -> int:
    import http.client
    import json

    posted = http.client.HTTPConnection(HOST, port, timeout=5)
    posted.request(
        "POST",
        HTTP_PATH,
        body=json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "miles", "version": "0"},
                },
            }
        ).encode(),
        headers={
            "Host": "aetherbridge.a.pinggy.link",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    response = posted.getresponse()
    status = response.status
    response.read()
    posted.close()
    return status
