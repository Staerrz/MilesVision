"""The example loop stores OCR text and issues one dry-run click."""

from pathlib import Path

from desktop_agent.agents.example_loop import run_example
from desktop_agent.bridge.api import Bridge
from desktop_agent.core.settings import Settings
from desktop_agent.memory.manager import MemoryManager
from tests.fakes import FakeGrabber, FakeOcr, Recorder


def test_example_loop_dry_run_click(tmp_path: Path) -> None:
    settings = Settings(
        output_dir=tmp_path / "generated",
        session_db=tmp_path / "session.db",
        memory_kb_db=tmp_path / "memory_kb.db",
        screen_control_allowed=False,
        max_model_side=80,
    )
    backend = Recorder()
    bridge = Bridge(
        settings,
        memory=MemoryManager(settings.session_db, settings.memory_kb_db),
        grabber=FakeGrabber(),
        ocr=FakeOcr(),
        backend=backend,
    )
    result = run_example("Read the Notepad title", bridge)
    assert "Notepad" in result["reply"]
    assert result["action"]["ok"] is True
    assert result["action"]["outcome"]["dry_run"] is True
    assert result["action"]["params"]["x"] == 30
    assert result["action"]["params"]["y"] == 30
    assert backend.calls == []
    assert result["memory"]["ok"] is True
    assert result["capture"]["outcome"]["model_size"][0] <= 80
