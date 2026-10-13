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
from desktop_agent.control.pc_control.http_server import HOST, HTTP_PATH, PORT, registered_tools

CONTROL = Path(__file__).resolve().parents[1] / "desktop_agent" / "control"
EXPECTED = tuple(f"pc_{name}" for name in SOURCE_NAMES)


def test_one_session_manager_for_the_process_lifespan() -> None:
    import anyio

    from desktop_agent.control.pc_control.http_server import build_http_app

    app = build_http_app()
    manager = app.state.pc_session_manager
    assert manager.stateless is True
    assert manager.json_response is True
    assert manager._task_group is None

    async def enter_once() -> None:
        async with app.router.lifespan_context(app):
            assert manager._task_group is not None

    anyio.run(enter_once)
    assert manager._task_group is None


def test_registered_names_match_the_bridge() -> None:
    names = tuple(fn.__name__ for fn in registered_tools())
    assert names == EXPECTED
    assert "memory_recall" not in names
    assert "mouse_click" not in names


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
        names, click, refused = asyncio.run(_listed_and_called(port, pinggy["access_token"]))
        assert names == list(EXPECTED)
        assert click["ok"] is True
        assert click["outcome"]["dry_run"] is True
        assert click["outcome"]["executed"] is False
        assert refused["ok"] is False
        assert "VISION_ALLOW_SCREEN_CONTROL" in refused["outcome"]["reason"]
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
                    "pc_click",
                    {"window": "Notepad", "target": "12", "dry_run": True},
                )
                refused = await session.call_tool(
                    "pc_open_app",
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
        sent = {"Host": tunnel_host}
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
    token_route_status, _token_headers, _token_raw = request(
        "POST",
        "/token",
        body=b"",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    protected_status, _protected_headers, protected_body = request("GET", "/.well-known/oauth-protected-resource")
    if protected_status != 200:
        raise AssertionError(f"protected resource {protected_status}: {protected_body!r}")

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
    authorize_status, authorize_headers, authorize_body = request("GET", f"/authorize?{query}")
    if authorize_status != 302:
        raise AssertionError(f"authorize {authorize_status}: {authorize_body!r}")
    code = parse_qs(urlparse(authorize_headers["location"]).query)["code"][0]
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
    access_token = json.loads(issued_body.decode())["access_token"]
    listed_status, _listed_headers, listed_body = request(
        "POST",
        HTTP_PATH,
        body=json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "mcp-protocol-version": "2025-11-25",
        },
    )
    if listed_status != 200:
        raise AssertionError(f"tools/list {listed_status}: {listed_body!r}")
    listed = json.loads(listed_body.decode())
    www = unauthenticated_headers.get("www-authenticate", "")
    return {
        "unauthenticated_status": unauthenticated_status,
        "www_authenticate_has_metadata": f'resource_metadata="{metadata}"' in www,
        "token_route_status": token_route_status,
        "protected_resource_status": protected_status,
        "access_token": access_token,
        "tools": [tool["name"] for tool in listed["result"]["tools"]],
    }


def test_default_port_is_not_memory() -> None:
    assert PORT == 8770
    assert PORT != 8765
    assert HTTP_PATH == "/mcp"
