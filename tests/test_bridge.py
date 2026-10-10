"""Bridge calls log timestamp, params, and outcome."""

from pathlib import Path

from desktop_agent.bridge.api import Bridge, reset_bridge
from desktop_agent.core.settings import Settings
from desktop_agent.memory.manager import MemoryManager
from tests.fakes import FakeGrabber, FakeOcr, Recorder


def _bridge(tmp_path: Path, **overrides: object) -> Bridge:
    settings = Settings(
        output_dir=tmp_path / "generated",
        session_db=tmp_path / "session.db",
        memory_kb_db=tmp_path / "memory_kb.db",
        screen_control_allowed=False,
        ocr_engine="tesseract",
        max_model_side=100,
    )
    for key, value in overrides.items():
        setattr(settings, key, value)
    memory = MemoryManager(settings.session_db, settings.memory_kb_db)
    return Bridge(settings, memory=memory, grabber=FakeGrabber(), ocr=FakeOcr(), backend=Recorder())


def test_bridge_logs_every_call(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    captured = bridge.screen_capture_full()
    assert captured["ok"] is True
    assert captured["timestamp"]
    assert captured["params"] == {}
    assert captured["outcome"]["size"] == [320, 200]
    assert Path(captured["outcome"]["model_path"]).is_file()

    clicked = bridge.mouse_click(3, 4, dry_run=True)
    assert clicked["ok"] is True
    assert clicked["params"]["x"] == 3
    assert clicked["outcome"]["dry_run"] is True
    assert clicked["event_id"]

    recent = bridge.memory_get_recent(limit=10)
    names = [event["name"] for event in recent["outcome"]["events"]]
    assert "screen_capture_full" in names
    assert "mouse_click" in names
    logged = next(event for event in recent["outcome"]["events"] if event["name"] == "mouse_click")
    assert logged["timestamp"] == clicked["timestamp"]
    assert logged["params"]["y"] == 4
    assert logged["outcome"]["executed"] is False


def test_region_ocr_uses_engine(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    result = bridge.screen_ocr_region(0, 0, 40, 20)
    assert result["ok"] is True
    assert result["outcome"]["items"][0]["text"] == "Notepad"
    assert result["outcome"]["engine"] == "fake"
    assert result["outcome"]["region"] == [0, 0, 40, 20]


def test_module_functions_use_reset_bridge(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    reset_bridge(bridge)
    from desktop_agent.bridge.api import keyboard_hotkey

    result = keyboard_hotkey("enter", dry_run=True)
    assert result["tool"] == "keyboard_hotkey"
    assert result["outcome"]["dry_run"] is True
    reset_bridge(Bridge(
        Settings(session_db=tmp_path / "other.db", memory_kb_db=tmp_path / "other-kb.db", output_dir=tmp_path / "out"),
        grabber=FakeGrabber(),
        ocr=FakeOcr(),
        backend=Recorder(),
    ))
