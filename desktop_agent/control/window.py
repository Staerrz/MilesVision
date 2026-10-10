"""Window focus, application launch, and URL open.

``focus_window`` rewrites ``bring_to_front`` from ``launchApp``. ``launch_app``
rewrites ``launch_app`` (name, optional foreground). ``open_url`` has no
source function; it is ``os.startfile`` restricted to ``http`` and ``https``.
"""

from __future__ import annotations

from typing import Any

from desktop_agent.control.backend import InputBackend, Win32Backend
from desktop_agent.control.guard import gate, log_action
from desktop_agent.core.settings import Settings


def _backend(backend: InputBackend | None) -> InputBackend:
    return backend if backend is not None else Win32Backend()


def focus_window(
    settings: Settings,
    *,
    title: str | None = None,
    pid: int | None = None,
    dry_run: bool | None = None,
    backend: InputBackend | None = None,
    label: str | None = None,
    approved: bool = False,
) -> dict[str, Any]:
    """Bring a window to the foreground by exact title or process id."""
    if not title and pid is None:
        raise ValueError("focus_window needs title or pid")
    params = {"title": title, "pid": pid, "label": label}
    blocked = gate(
        "focus_window",
        params,
        settings,
        dry_run=dry_run,
        label=label,
        app_name=title,
        approved=approved,
    )
    if blocked is not None:
        return blocked
    found = _backend(backend).focus(title, pid)
    return log_action(
        "focus_window",
        params,
        {"ok": True, "executed": True, "dry_run": False, "focused": found},
    )


def launch_app(
    name: str,
    settings: Settings,
    *,
    bring_to_front: bool = False,
    dry_run: bool | None = None,
    backend: InputBackend | None = None,
    label: str | None = None,
    approved: bool = False,
) -> dict[str, Any]:
    """Start an application by name. ``bring_to_front`` focuses that title once."""
    if not name or not str(name).strip():
        raise ValueError("launch_app needs a name")
    params = {"name": name, "bring_to_front": bool(bring_to_front), "label": label}
    blocked = gate(
        "launch_app",
        params,
        settings,
        dry_run=dry_run,
        label=label,
        approved=approved,
        check_allowlist=False,
    )
    if blocked is not None:
        return blocked
    launched = _backend(backend).launch(name)
    front = None
    if bring_to_front:
        front = _backend(backend).focus(name, None)
    return log_action(
        "launch_app",
        params,
        {"ok": True, "executed": True, "dry_run": False, "launched": launched, "focused": front},
    )


def open_url(
    url: str,
    settings: Settings,
    *,
    dry_run: bool | None = None,
    backend: InputBackend | None = None,
    label: str | None = None,
    app_name: str | None = None,
    approved: bool = False,
) -> dict[str, Any]:
    """Open an ``http`` or ``https`` URL with the Windows shell."""
    target = str(url or "").strip()
    lowered = target.lower()
    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        raise ValueError("open_url only accepts http:// and https:// URLs")
    params = {"url": target, "label": label, "app_name": app_name}
    blocked = gate(
        "open_url",
        params,
        settings,
        dry_run=dry_run,
        label=label,
        approved=approved,
        check_allowlist=False,
    )
    if blocked is not None:
        return blocked
    _backend(backend).open_url(target)
    return log_action(
        "open_url",
        params,
        {"ok": True, "executed": True, "dry_run": False, "opened": target},
    )
