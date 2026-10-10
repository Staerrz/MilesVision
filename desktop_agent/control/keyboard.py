"""High-level keyboard actions.

``type_text`` is ``tool_screen_type``. ``press`` is ``tool_screen_key``.
Both are logged. Password roles are refused by ``gate``.
"""

from __future__ import annotations

from typing import Any

from desktop_agent.control.backend import InputBackend, Win32Backend
from desktop_agent.control.guard import TYPE_ACTIONS, gate, log_action
from desktop_agent.control.keys import parse_combo, type_method
from desktop_agent.core.settings import Settings


def _backend(backend: InputBackend | None) -> InputBackend:
    return backend if backend is not None else Win32Backend()


def type_text(
    text: str,
    settings: Settings,
    *,
    dry_run: bool | None = None,
    backend: InputBackend | None = None,
    label: str | None = None,
    field_role: str | None = None,
    app_name: str | None = None,
    approved: bool = False,
) -> dict[str, Any]:
    """Type ``text`` into the focused control.

    ASCII that ``key_for_char`` accepts uses virtual keys. Any non-ASCII
    character switches the whole string to the clipboard paste path.
    """
    method = type_method(text)
    params: dict[str, Any] = {
        "text": text,
        "method": method,
        "label": label,
        "field_role": field_role,
        "app_name": app_name,
    }
    blocked = gate(
        "type_text",
        params,
        settings,
        dry_run=dry_run,
        label=label,
        field_role=field_role,
        app_name=app_name,
        approved=approved,
    )
    if blocked is not None:
        return blocked
    used = _backend(backend).type_text(text)
    return log_action(
        "type_text",
        params,
        {"ok": True, "executed": True, "dry_run": False, "typed": text, "method": used},
    )


def press(
    key: str,
    settings: Settings,
    *,
    dry_run: bool | None = None,
    backend: InputBackend | None = None,
    label: str | None = None,
    app_name: str | None = None,
    approved: bool = False,
) -> dict[str, Any]:
    """Press one key or a combo such as ``enter`` or ``ctrl+c``."""
    normalized = str(key or "").strip().lower()
    if not normalized:
        raise ValueError("key is empty")
    combo = "+" in normalized
    if combo:
        parse_combo(normalized)
    params = {"key": normalized, "combo": combo, "label": label, "app_name": app_name}
    blocked = gate(
        "press",
        params,
        settings,
        dry_run=dry_run,
        label=label,
        app_name=app_name,
        approved=approved,
    )
    if blocked is not None:
        return blocked
    _backend(backend).press(normalized)
    return log_action(
        "press",
        params,
        {"ok": True, "executed": True, "dry_run": False, "pressed": normalized, "combo": combo},
    )


# The gate treats this name as a typing action. The public name is type_text.
assert "type_text" in TYPE_ACTIONS
