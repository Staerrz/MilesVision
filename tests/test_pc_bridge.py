"""PC-Control is on the vision bridge. It is not a second server, and dry-run does not import Win32."""

from pathlib import Path

from desktop_agent.bridge.api import Bridge
from desktop_agent.bridge.pc import MUTATING, SOURCE_NAMES
from desktop_agent.core.settings import Settings
from desktop_agent.memory.manager import MemoryManager
from tests.fakes import FakeGrabber, FakeOcr, Recorder


def _bridge(tmp_path: Path) -> Bridge:
    settings = Settings(
        output_dir=tmp_path / "generated",
        session_db=tmp_path / "session.db",
        memory_kb_db=tmp_path / "memory_kb.db",
        screen_control_allowed=False,
    )
    return Bridge(
        settings,
        memory=MemoryManager(settings.session_db, settings.memory_kb_db),
        grabber=FakeGrabber(),
        ocr=FakeOcr(),
        backend=Recorder(),
    )


def test_source_tool_names_are_the_ten() -> None:
    assert SOURCE_NAMES == (
        "windows",
        "look",
        "click",
        "type",
        "drag",
        "key",
        "scroll",
        "read",
        "show",
        "open_app",
    )
    assert MUTATING == {"click", "type", "drag", "key", "scroll", "show", "open_app"}


def test_dry_run_click_does_not_need_windows(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    result = bridge.pc_click("Notepad", "12", dry_run=True)
    assert result["ok"] is True
    assert result["tool"] == "pc_click"
    assert result["outcome"]["executed"] is False
    assert result["outcome"]["dry_run"] is True
    assert result["outcome"]["plan"]["target"] == "12"
    assert result["timestamp"]
    recent = bridge.memory_get_recent(limit=5)
    assert any(event["name"] == "pc_click" for event in recent["outcome"]["events"])


def test_screen_control_off_refuses_open(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    result = bridge.pc_open_app("notepad.exe", dry_run=False)
    assert result["ok"] is False
    assert "VISION_ALLOW_SCREEN_CONTROL" in result["outcome"]["reason"]


def test_observe_reports_missing_windows_stack(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    result = bridge.pc_windows("word")
    assert result["tool"] == "pc_windows"
    assert result["ok"] is False
    assert "PC-Control" in result["outcome"]["error"]


def test_memory_tools_stay_on_the_same_bridge(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    assert hasattr(bridge, "memory_search")
    assert hasattr(bridge, "pc_look")
    added = bridge.memory_add_event("note", {"from": "pc"}, {"ok": True})
    assert added["tool"] == "memory_add_event"
    assert added["ok"] is True
