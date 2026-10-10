"""Session events, and MilesMemory recall when the package is installed."""

from pathlib import Path

import pytest

from desktop_agent.memory.manager import MemoryManager


def test_session_add_and_recent(tmp_path: Path) -> None:
    manager = MemoryManager(tmp_path / "session.db", tmp_path / "kb.db")
    first = manager.add_event("observation", {"instruction": "look"}, {"text": "Hi"}, kind="note")
    second = manager.add_event("mouse_click", {"x": 1}, {"ok": True}, kind="tool")
    recent = manager.get_recent(limit=10)
    assert recent["count"] == 2
    assert recent["events"][0]["id"] == second["id"]
    assert recent["events"][1]["params"]["instruction"] == "look"
    assert first["kind"] == "note"
    manager.close()


def test_search_reports_missing_package_or_runs_both(tmp_path: Path) -> None:
    manager = MemoryManager(tmp_path / "session.db", tmp_path / "kb.db", agent_id="desktop-agent")
    try:
        import memory_kb  # noqa: F401
    except ImportError:
        found = manager.search("anything")
        assert found["status"] == "memory_kb_unavailable"
        manager.close()
        return

    token = "zxq-desktop-archive-token-991"
    archived = manager.archive_summary(f"desktop saw {token}", session_id="example")
    assert archived["status"] == "ok", archived
    found = manager.search(token, limit=5)
    assert found["status"] == "ok"
    assert found["cell_mem"]["framework"] == "cell-mem"
    assert found["agent_memory_os"]["framework"] == "agent-memory-os"
    memories = found["agent_memory_os"].get("memories") or found["agent_memory_os"].get("data") or []
    assert any(token in row["content"] for row in memories)
    cell_rows = found["cell_mem"].get("data") or []
    assert any(token in row.get("content", "") for row in cell_rows)
    manager.close()


def test_archive_without_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "memory_kb", None)
    monkeypatch.setitem(sys.modules, "memory_kb.engine", None)
    manager = MemoryManager(tmp_path / "session.db", tmp_path / "kb.db")
    # A poisoned module entry makes the import fail inside _open_kb.
    result = manager.archive_summary("a summary")
    assert result["status"] == "memory_kb_unavailable"
    manager.close()
