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
        stale = _stale_get_and_post_roundtrip(port)
        assert stale["get_status"] != 404
        assert stale["initialize_status"] == 200
        assert "mcp-session-id" not in {name.lower() for name in stale["initialize_headers"]}
        assert stale["tools"] == list(EXPECTED)
        names, click, refused = asyncio.run(_listed_and_called(port))
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


async def _listed_and_called(port: int):
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    url = f"http://{HOST}:{port}{HTTP_PATH}"
    async with streamable_http_client(url) as (read, write):
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


def _stale_get_and_post_roundtrip(port: int) -> dict:
    """A tunnel GET may still carry a session id this process never issued."""
    import http.client
    import json

    stale_id = "e4a70d315b7f4ea48a9f7291e752d2d7"
    host = f"{HOST}:{port}"
    connection = http.client.HTTPConnection(HOST, port, timeout=5)
    try:
        connection.request(
            "GET",
            HTTP_PATH,
            headers={
                "Host": host,
                "Accept": "application/json, text/event-stream",
                "mcp-session-id": stale_id,
            },
        )
        get_response = connection.getresponse()
        get_status = get_response.status
    finally:
        connection.close()

    def post(body: dict, extra_headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
        posted = http.client.HTTPConnection(HOST, port, timeout=5)
        headers = {
            "Host": host,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)
        posted.request("POST", HTTP_PATH, body=json.dumps(body).encode(), headers=headers)
        response = posted.getresponse()
        status = response.status
        header_map = {name.lower(): value for name, value in response.getheaders()}
        raw = response.read()
        posted.close()
        return status, header_map, raw

    initialize_status, initialize_headers, initialize_body = post(
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
    )
    post({"jsonrpc": "2.0", "method": "notifications/initialized"})
    listed_status, _listed_headers, listed_body = post(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"mcp-session-id": stale_id, "mcp-protocol-version": "2025-11-25"},
    )
    if listed_status != 200:
        raise AssertionError(f"tools/list status {listed_status}: {listed_body!r}")
    listed = json.loads(listed_body.decode())
    if initialize_status != 200:
        raise AssertionError(f"initialize status {initialize_status}: {initialize_body!r}")
    return {
        "get_status": get_status,
        "initialize_status": initialize_status,
        "initialize_headers": list(initialize_headers),
        "tools": [tool["name"] for tool in listed["result"]["tools"]],
    }


def test_default_port_is_not_memory() -> None:
    assert PORT == 8770
    assert PORT != 8765
    assert HTTP_PATH == "/mcp"
