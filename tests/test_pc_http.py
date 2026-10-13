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


def test_default_port_is_not_memory() -> None:
    assert PORT == 8770
    assert PORT != 8765
    assert HTTP_PATH == "/mcp"
