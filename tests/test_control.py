"""Gates, key planning, and dry-run. No Win32 calls."""

import pytest

from desktop_agent.control.keyboard import press, type_text
from desktop_agent.control.keys import drag_points, key_for_char, parse_combo, type_method
from desktop_agent.control.mouse import click, drag, move_mouse
from desktop_agent.control.window import focus_window, launch_app, open_url
from desktop_agent.core.settings import Settings
from tests.fakes import Recorder


def _settings(**overrides: object) -> Settings:
    settings = Settings(screen_control_allowed=False, dry_run=False, allowed_apps=())
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


def test_key_for_char_letters_and_space() -> None:
    assert key_for_char("a") == (ord("A"), False)
    assert key_for_char("A") == (ord("A"), True)
    assert key_for_char(" ") == (0x20, False)
    with pytest.raises(ValueError):
        key_for_char("!")


def test_type_method_clipboard_for_non_ascii() -> None:
    assert type_method("Hello") == "keyboard"
    assert type_method("你好") == "clipboard"


def test_parse_combo_maps_cmd_to_win() -> None:
    assert parse_combo("ctrl+c") == (["ctrl"], ["c"])
    assert parse_combo("cmd+c") == (["win"], ["c"])


def test_drag_points_follow_source_step_count() -> None:
    points = drag_points(0, 0, 10, 0, 0.2)
    assert len(points) == 10
    assert points[0] == (1, 0)
    assert points[-1] == (10, 0)


def test_dry_run_does_not_call_backend() -> None:
    backend = Recorder()
    settings = _settings()
    moved = move_mouse(4, 5, settings, dry_run=True, backend=backend)
    clicked = click(1, 2, settings, dry_run=True, backend=backend)
    dragged = drag(0, 0, 3, 4, settings, dry_run=True, backend=backend)
    typed = type_text("Hi", settings, dry_run=True, backend=backend)
    pressed = press("ctrl+c", settings, dry_run=True, backend=backend)
    focused = focus_window(settings, title="Notepad", dry_run=True, backend=backend)
    launched = launch_app("notepad", settings, dry_run=True, backend=backend)
    opened = open_url("https://example.com", settings, dry_run=True, backend=backend)
    assert backend.calls == []
    assert moved["dry_run"] and clicked["dry_run"] and dragged["dry_run"]
    assert typed["plan"]["method"] == "keyboard"
    assert pressed["plan"]["key"] == "ctrl+c"
    assert focused["ok"] and launched["ok"] and opened["ok"]


def test_screen_control_off_refuses_without_calling_backend() -> None:
    backend = Recorder()
    refused = click(1, 1, _settings(), dry_run=False, backend=backend)
    assert refused["ok"] is False
    assert "VISION_ALLOW_SCREEN_CONTROL" in refused["reason"]
    assert backend.calls == []


def test_execute_calls_backend_when_allowed() -> None:
    backend = Recorder()
    settings = _settings(screen_control_allowed=True)
    result = click(8, 9, settings, button="right", double=True, dry_run=False, backend=backend)
    assert result["executed"] is True
    assert backend.calls == [("click", 8, 9, "right", True)]


def test_password_role_refuses_even_dry_run() -> None:
    backend = Recorder()
    refused = type_text("secret", _settings(), dry_run=True, field_role="AXPasswordField", backend=backend)
    assert refused["ok"] is False
    assert "Password" in refused["reason"]
    assert backend.calls == []


def test_dangerous_label_refuses_unless_dry_run_or_approved() -> None:
    backend = Recorder()
    settings = _settings(screen_control_allowed=True)
    refused = click(1, 1, settings, label="删除文件", dry_run=False, backend=backend)
    assert refused["ok"] is False
    planned = click(1, 1, settings, label="删除文件", dry_run=True, backend=backend)
    assert planned["dry_run"] is True
    allowed = click(1, 1, settings, label="删除文件", dry_run=False, approved=True, backend=backend)
    assert allowed["executed"] is True
    assert backend.calls == [("click", 1, 1, "left", False)]


def test_allowlist_blocks_click_but_not_launch() -> None:
    backend = Recorder()
    settings = _settings(screen_control_allowed=True, allowed_apps=("Notepad",))
    blocked = click(1, 1, settings, dry_run=False, backend=backend)
    assert blocked["ok"] is False
    named = click(1, 1, settings, app_name="Notepad", dry_run=False, backend=backend)
    assert named["executed"] is True
    launched = launch_app("other", settings, dry_run=False, backend=backend)
    assert launched["executed"] is True


def test_open_url_rejects_non_http() -> None:
    with pytest.raises(ValueError):
        open_url("file:///C:/Windows", _settings(), dry_run=True, backend=Recorder())
