"""High-level mouse actions.

``move_mouse`` is ``tool_screen_move``. ``click`` is ``tool_screen_click``.
``drag`` is ``tool_screen_drag``. Each call goes through ``gate`` and is logged.
"""

from __future__ import annotations

from typing import Any

from desktop_agent.control.backend import InputBackend, Win32Backend
from desktop_agent.control.guard import gate, log_action
from desktop_agent.control.keys import drag_points
from desktop_agent.core.settings import Settings

_BUTTONS = frozenset({"left", "right", "middle"})


def _backend(backend: InputBackend | None) -> InputBackend:
    return backend if backend is not None else Win32Backend()


def _check_button(button: str) -> str:
    name = button.lower()
    if name not in _BUTTONS:
        raise ValueError(f"button must be left, right, or middle; got {button!r}")
    return name


def move_mouse(
    x: int,
    y: int,
    settings: Settings,
    *,
    dry_run: bool | None = None,
    backend: InputBackend | None = None,
    label: str | None = None,
    app_name: str | None = None,
    approved: bool = False,
) -> dict[str, Any]:
    """Move the cursor to screen pixel ``(x, y)``."""
    params = {"x": int(x), "y": int(y), "label": label, "app_name": app_name}
    blocked = gate(
        "move_mouse",
        params,
        settings,
        dry_run=dry_run,
        label=label,
        app_name=app_name,
        approved=approved,
    )
    if blocked is not None:
        return blocked
    _backend(backend).move(int(x), int(y))
    return log_action("move_mouse", params, {"ok": True, "executed": True, "dry_run": False, "moved_to": [int(x), int(y)]})


def click(
    x: int,
    y: int,
    settings: Settings,
    *,
    button: str = "left",
    double: bool = False,
    dry_run: bool | None = None,
    backend: InputBackend | None = None,
    label: str | None = None,
    app_name: str | None = None,
    approved: bool = False,
) -> dict[str, Any]:
    """Click at screen pixel ``(x, y)``. ``button`` is left, right, or middle."""
    button_name = _check_button(button)
    params = {
        "x": int(x),
        "y": int(y),
        "button": button_name,
        "double": bool(double),
        "label": label,
        "app_name": app_name,
    }
    blocked = gate(
        "click",
        params,
        settings,
        dry_run=dry_run,
        label=label,
        app_name=app_name,
        approved=approved,
    )
    if blocked is not None:
        return blocked
    _backend(backend).click(int(x), int(y), button_name, bool(double))
    return log_action(
        "click",
        params,
        {"ok": True, "executed": True, "dry_run": False, "clicked": [int(x), int(y)], "button": button_name, "double": bool(double)},
    )


def drag(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    settings: Settings,
    *,
    duration: float = 0.2,
    button: str = "left",
    dry_run: bool | None = None,
    backend: InputBackend | None = None,
    label: str | None = None,
    app_name: str | None = None,
    approved: bool = False,
) -> dict[str, Any]:
    """Drag from ``(x1, y1)`` to ``(x2, y2)``. ``duration`` is seconds."""
    button_name = _check_button(button)
    span = max(0.0, float(duration))
    params = {
        "x1": int(x1),
        "y1": int(y1),
        "x2": int(x2),
        "y2": int(y2),
        "duration": span,
        "button": button_name,
        "points": [list(point) for point in drag_points(int(x1), int(y1), int(x2), int(y2), span)],
        "label": label,
        "app_name": app_name,
    }
    blocked = gate(
        "drag",
        params,
        settings,
        dry_run=dry_run,
        label=label,
        app_name=app_name,
        approved=approved,
    )
    if blocked is not None:
        return blocked
    _backend(backend).drag(int(x1), int(y1), int(x2), int(y2), span, button_name)
    return log_action(
        "drag",
        params,
        {"ok": True, "executed": True, "dry_run": False, "dragged": [[int(x1), int(y1)], [int(x2), int(y2)]], "button": button_name},
    )
