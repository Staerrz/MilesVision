"""PC-Control tools, called by the one vision bridge.

The implementations are ``desktop_agent.control.pc_control.server.TOOLS``:
``windows``, ``look``, ``click``, ``type``, ``drag``, ``key``, ``scroll``,
``read``, ``show``, ``open_app``. Those names are on the bridge. ``pc_*``
aliases call the same tools. Neither set replaces ``mouse_click``,
``keyboard_type``, ``mouse_drag``, or ``keyboard_hotkey``.

Miles Memory is not imported. The HTTP listener is ``pc_control.server``.
"""

from __future__ import annotations

from typing import Any

from desktop_agent.control.guard import effective_dry_run
from desktop_agent.core.settings import Settings

# These change a window or start a process. look / windows / read do not.
MUTATING = frozenset({"click", "type", "drag", "key", "scroll", "show", "open_app"})

SOURCE_NAMES = (
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


def run(name: str, arguments: dict[str, Any], settings: Settings, dry_run: bool | None) -> dict[str, Any]:
    """Run one PC-Control tool, or return the plan when dry-run or screen control is off."""
    if name not in SOURCE_NAMES:
        return {"ok": False, "executed": False, "error": f"unknown PC-Control tool {name}"}
    planned = effective_dry_run(settings, dry_run) if name in MUTATING else False
    if name in MUTATING and planned:
        return {
            "ok": True,
            "executed": False,
            "dry_run": True,
            "action": name,
            "reason": "dry_run",
            "plan": arguments,
        }
    if name in MUTATING and not settings.screen_control_allowed:
        return {
            "ok": False,
            "executed": False,
            "dry_run": False,
            "action": name,
            "reason": (
                "Screen control is off. Set VISION_ALLOW_SCREEN_CONTROL=1. "
                "This PC-Control call was not executed."
            ),
            "plan": arguments,
        }
    try:
        from desktop_agent.control.pc_control.policy import NeedsPermission
        from desktop_agent.control.pc_control.server import TOOLS, ToolError
    except Exception as exc:
        return {
            "ok": False,
            "executed": False,
            "error": (
                "PC-Control needs Windows (uiautomation, pywin32, opencv). "
                f"Import failed: {exc}"
            ),
        }
    try:
        result = TOOLS[name](**arguments)
    except NeedsPermission as exc:
        return {
            "ok": False,
            "executed": False,
            "needs_permission": True,
            "question": exc.question,
            "error": str(exc),
        }
    except ToolError as exc:
        return {"ok": False, "executed": False, "error": str(exc)}
    return {"ok": True, "executed": True, "dry_run": False, "action": name, "result": result}
