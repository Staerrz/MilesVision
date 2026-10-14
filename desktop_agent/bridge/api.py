"""Model-facing functions.

Every call writes one session event with the timestamp, the parameters, and
the outcome. Screen and input work is delegated to ``vision`` and ``control``.
Long-term search is delegated to ``MemoryManager.search``, which returns
cell-mem recall and agent-memory-os search without mixing their ranks.

``launch_app`` and ``open_url`` stay on the control module. They are not
bridge tools. Active-window capture stays on ``vision.capture``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from desktop_agent.control.backend import InputBackend
from desktop_agent.control.keyboard import press, type_text
from desktop_agent.control.mouse import click as _win32_click, drag as _win32_drag, move_mouse
from desktop_agent.control.window import focus_window
from desktop_agent.core.logging import configure_logging, get_logger
from desktop_agent.core.settings import Settings
from desktop_agent.memory.manager import MemoryManager
from desktop_agent.bridge.pc import run as _pc
from desktop_agent.vision.capture import CaptureError, Grabber, default_grabber
from desktop_agent.vision.ocr import OcrEngine, OcrError, build_ocr

log = get_logger("bridge")

_bridge: Bridge | None = None


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class Bridge:
    """Bound settings, memory, grabber, OCR engine, and input backend."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        memory: MemoryManager | None = None,
        grabber: Grabber | None = None,
        ocr: OcrEngine | None = None,
        backend: InputBackend | None = None,
    ) -> None:
        self.settings = settings or Settings.load()
        configure_logging(self.settings.log_level)
        self.memory = memory or MemoryManager(
            self.settings.session_db,
            self.settings.memory_kb_db,
            agent_id=self.settings.agent_id,
        )
        self.grabber = grabber
        self.ocr = ocr or build_ocr(self.settings)
        self.backend = backend

    def _grabber(self) -> Grabber:
        if self.grabber is None:
            self.grabber = default_grabber()
        return self.grabber

    def _call(self, name: str, params: dict[str, Any], fn: Any) -> dict[str, Any]:
        """Run ``fn``, then store timestamp, params, and outcome."""
        stamped = _stamp()
        try:
            outcome = fn()
            if not isinstance(outcome, dict):
                outcome = {"ok": True, "value": outcome}
            ok = bool(outcome.get("ok", True))
        except (CaptureError, OcrError, ValueError, OSError, RuntimeError) as exc:
            outcome = {"ok": False, "error": str(exc)}
            ok = False
        event = self.memory.add_event(
            name,
            params,
            outcome,
            kind="tool",
            timestamp=stamped,
        )
        log.info("bridge %s ok=%s event=%s", name, ok, event["id"])
        return {
            "ok": ok,
            "tool": name,
            "timestamp": stamped,
            "params": params,
            "outcome": outcome,
            "event_id": event["id"],
        }

    def memory_add_event(
        self,
        name: str,
        params: dict[str, Any] | None = None,
        outcome: dict[str, Any] | None = None,
        *,
        kind: str = "note",
        session_id: str = "default",
        archive: bool = False,
    ) -> dict[str, Any]:
        """Record a session event. ``archive=True`` also writes a long-term summary."""
        call_params = {
            "name": name,
            "params": params or {},
            "outcome": outcome or {},
            "kind": kind,
            "session_id": session_id,
            "archive": archive,
        }

        def run() -> dict[str, Any]:
            event = self.memory.add_event(
                name,
                params,
                outcome,
                kind=kind,
                session_id=session_id,
            )
            archived = None
            if archive:
                text = _summary_text(name, params, outcome)
                archived = self.memory.archive_summary(text, session_id=session_id)
            return {"ok": True, "event": event, "archived": archived}

        return self._call("memory_add_event", call_params, run)

    def memory_search(self, query: str, limit: int = 10, **options: Any) -> dict[str, Any]:
        """Search long-term memory. Both framework results are returned."""
        params = {"query": query, "limit": limit, **options}

        def run() -> dict[str, Any]:
            found = self.memory.search(query, limit=limit, **options)
            found["ok"] = found.get("status") != "memory_kb_unavailable"
            return found

        return self._call("memory_search", params, run)

    def memory_get_recent(self, limit: int = 20, session_id: str | None = None) -> dict[str, Any]:
        """Return the newest session and tool events."""
        params = {"limit": limit, "session_id": session_id}

        def run() -> dict[str, Any]:
            recent = self.memory.get_recent(limit=limit, session_id=session_id)
            recent["ok"] = True
            return recent

        return self._call("memory_get_recent", params, run)

    def screen_capture_full(self) -> dict[str, Any]:
        """Capture the full screen and a downsampled model image."""

        def run() -> dict[str, Any]:
            shot = self._capture_full()
            payload = shot.as_dict()
            payload["ok"] = True
            return payload

        return self._call("screen_capture_full", {}, run)

    def screen_capture_region(self, x1: int, y1: int, x2: int, y2: int) -> dict[str, Any]:
        """Capture one screen rectangle and a downsampled model image."""
        params = {"x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2)}

        def run() -> dict[str, Any]:
            from desktop_agent.vision.capture import capture_region

            shot = capture_region(
                self._grabber(),
                self.settings.output_dir,
                int(x1),
                int(y1),
                int(x2),
                int(y2),
                max_side=self.settings.max_model_side,
                norm_size=self.settings.norm_size,
            )
            payload = shot.as_dict()
            payload["ok"] = True
            return payload

        return self._call("screen_capture_region", params, run)

    def screen_ocr_full(self, language: str | None = None) -> dict[str, Any]:
        """Capture the full screen and OCR the full-resolution image."""
        params = {"language": language or self.settings.ocr_language}

        def run() -> dict[str, Any]:
            shot = self._capture_full()
            return self._ocr(shot, str(params["language"]))

        return self._call("screen_ocr_full", params, run)

    def screen_ocr_region(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        language: str | None = None,
    ) -> dict[str, Any]:
        """Capture a rectangle and OCR that image at full resolution."""
        params = {
            "x1": int(x1),
            "y1": int(y1),
            "x2": int(x2),
            "y2": int(y2),
            "language": language or self.settings.ocr_language,
        }

        def run() -> dict[str, Any]:
            from desktop_agent.vision.capture import capture_region

            shot = capture_region(
                self._grabber(),
                self.settings.output_dir,
                int(x1),
                int(y1),
                int(x2),
                int(y2),
                max_side=self.settings.max_model_side,
                norm_size=self.settings.norm_size,
            )
            return self._ocr(shot, str(params["language"]))

        return self._call("screen_ocr_region", params, run)

    def mouse_move(
        self,
        x: int,
        y: int,
        *,
        dry_run: bool | None = None,
        label: str | None = None,
        app_name: str | None = None,
        approved: bool = False,
    ) -> dict[str, Any]:
        """Move the cursor. Risky: honors ``dry_run``."""
        params = {"x": int(x), "y": int(y), "dry_run": dry_run, "label": label, "app_name": app_name, "approved": approved}
        return self._call(
            "mouse_move",
            params,
            lambda: move_mouse(
                int(x),
                int(y),
                self.settings,
                dry_run=dry_run,
                backend=self.backend,
                label=label,
                app_name=app_name,
                approved=approved,
            ),
        )

    def mouse_click(
        self,
        x: int,
        y: int,
        *,
        button: str = "left",
        double: bool = False,
        dry_run: bool | None = None,
        label: str | None = None,
        app_name: str | None = None,
        approved: bool = False,
    ) -> dict[str, Any]:
        """Click. Risky: honors ``dry_run``."""
        params = {
            "x": int(x),
            "y": int(y),
            "button": button,
            "double": double,
            "dry_run": dry_run,
            "label": label,
            "app_name": app_name,
            "approved": approved,
        }
        return self._call(
            "mouse_click",
            params,
            lambda: _win32_click(
                int(x),
                int(y),
                self.settings,
                button=button,
                double=double,
                dry_run=dry_run,
                backend=self.backend,
                label=label,
                app_name=app_name,
                approved=approved,
            ),
        )

    def mouse_drag(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        *,
        duration: float = 0.2,
        button: str = "left",
        dry_run: bool | None = None,
        label: str | None = None,
        app_name: str | None = None,
        approved: bool = False,
    ) -> dict[str, Any]:
        """Drag. Risky: honors ``dry_run``."""
        params = {
            "x1": int(x1),
            "y1": int(y1),
            "x2": int(x2),
            "y2": int(y2),
            "duration": duration,
            "button": button,
            "dry_run": dry_run,
            "label": label,
            "app_name": app_name,
            "approved": approved,
        }
        return self._call(
            "mouse_drag",
            params,
            lambda: _win32_drag(
                int(x1),
                int(y1),
                int(x2),
                int(y2),
                self.settings,
                duration=duration,
                button=button,
                dry_run=dry_run,
                backend=self.backend,
                label=label,
                app_name=app_name,
                approved=approved,
            ),
        )

    def keyboard_type(
        self,
        text: str,
        *,
        dry_run: bool | None = None,
        label: str | None = None,
        field_role: str | None = None,
        app_name: str | None = None,
        approved: bool = False,
    ) -> dict[str, Any]:
        """Type text. Risky: honors ``dry_run``. Password roles are refused."""
        params = {
            "text": text,
            "dry_run": dry_run,
            "label": label,
            "field_role": field_role,
            "app_name": app_name,
            "approved": approved,
        }
        return self._call(
            "keyboard_type",
            params,
            lambda: type_text(
                text,
                self.settings,
                dry_run=dry_run,
                backend=self.backend,
                label=label,
                field_role=field_role,
                app_name=app_name,
                approved=approved,
            ),
        )

    def keyboard_hotkey(
        self,
        key: str,
        *,
        dry_run: bool | None = None,
        label: str | None = None,
        app_name: str | None = None,
        approved: bool = False,
    ) -> dict[str, Any]:
        """Press a key or combo. Risky: honors ``dry_run``."""
        params = {"key": key, "dry_run": dry_run, "label": label, "app_name": app_name, "approved": approved}
        return self._call(
            "keyboard_hotkey",
            params,
            lambda: press(
                key,
                self.settings,
                dry_run=dry_run,
                backend=self.backend,
                label=label,
                app_name=app_name,
                approved=approved,
            ),
        )

    def window_focus(
        self,
        title: str | None = None,
        pid: int | None = None,
        *,
        dry_run: bool | None = None,
        label: str | None = None,
        approved: bool = False,
    ) -> dict[str, Any]:
        """Focus a window by title or pid. Risky: honors ``dry_run``."""
        params = {"title": title, "pid": pid, "dry_run": dry_run, "label": label, "approved": approved}
        return self._call(
            "window_focus",
            params,
            lambda: focus_window(
                self.settings,
                title=title,
                pid=pid,
                dry_run=dry_run,
                backend=self.backend,
                label=label,
                approved=approved,
            ),
        )

    def windows(self, filter: str = "") -> dict[str, Any]:
        """List windows. The name a client copies from tools/list. Not ``window_focus``."""
        params = {"filter": filter}
        return self._call("windows", params, lambda: _pc("windows", params, self.settings, None))

    def look(
        self,
        window: str,
        mode: str = "auto",
        find: str = "",
        wait: float = 0,
    ) -> dict[str, Any]:
        """See one window. The name a client copies from tools/list."""
        params = {"window": window, "mode": mode, "find": find, "wait": wait}
        return self._call("look", params, lambda: _pc("look", params, self.settings, None))

    def click(
        self,
        window: str,
        target: str,
        right: bool = False,
        double: bool = False,
        *,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        """Click an element id from look. ``mouse_click`` stays the Win32 cursor click."""
        params = {"window": window, "target": target, "right": right, "double": double}
        return self._call("click", params, lambda: _pc("click", params, self.settings, dry_run))

    def type(
        self,
        window: str,
        target: str,
        text: str,
        replace: bool = False,
        *,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        """Type into an element id from look. ``keyboard_type`` stays the Win32 keystrokes."""
        params = {"window": window, "target": target, "text": text, "replace": replace}
        return self._call("type", params, lambda: _pc("type", params, self.settings, dry_run))

    def drag(
        self,
        window: str,
        points: str,
        shape: str = "path",
        right: bool = False,
        *,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        """Drag through image points. ``mouse_drag`` stays the Win32 cursor drag."""
        params = {"window": window, "points": points, "shape": shape, "right": right}
        return self._call("drag", params, lambda: _pc("drag", params, self.settings, dry_run))

    def key(
        self,
        window: str,
        name: str,
        *,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        """A key or the app's own shortcut. ``keyboard_hotkey`` stays the Win32 press."""
        params = {"window": window, "name": name}
        return self._call("key", params, lambda: _pc("key", params, self.settings, dry_run))

    def scroll(
        self,
        window: str,
        direction: str = "down",
        target: str = "",
        amount: int = 1,
        *,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        """Scroll a window or element."""
        params = {"window": window, "direction": direction, "target": target, "amount": amount}
        return self._call("scroll", params, lambda: _pc("scroll", params, self.settings, dry_run))

    def read(
        self,
        window: str,
        target: str = "",
        start: int = 0,
        length: int = 6000,
        find: str = "",
    ) -> dict[str, Any]:
        """Read a document, page, or field, including text out of view."""
        params = {"window": window, "target": target, "start": start, "length": length, "find": find}
        return self._call("read", params, lambda: _pc("read", params, self.settings, None))

    def show(
        self,
        window: str,
        target: str,
        label: str = "",
        seconds: int = 10,
        *,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        """Draw an orange circle for the user. Nothing is clicked."""
        params = {"window": window, "target": target, "label": label, "seconds": seconds}
        return self._call("show", params, lambda: _pc("show", params, self.settings, dry_run))

    def open_app(
        self,
        command: str,
        hidden: bool = False,
        *,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        """Launch an app minimized, or on the hidden desktop."""
        params = {"command": command, "hidden": hidden}
        return self._call("open_app", params, lambda: _pc("open_app", params, self.settings, dry_run))

    def pc_windows(self, filter: str = "") -> dict[str, Any]:
        """List windows. PC-Control ``windows``. Does not start a second server."""
        params = {"filter": filter}
        return self._call("pc_windows", params, lambda: _pc("windows", params, self.settings, None))

    def pc_look(
        self,
        window: str,
        mode: str = "auto",
        find: str = "",
        wait: float = 0,
    ) -> dict[str, Any]:
        """See one window. PC-Control ``look`` (UI tree, OCR, or a marked image)."""
        params = {"window": window, "mode": mode, "find": find, "wait": wait}
        return self._call("pc_look", params, lambda: _pc("look", params, self.settings, None))

    def pc_click(
        self,
        window: str,
        target: str,
        right: bool = False,
        double: bool = False,
        *,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        """Click in a window without moving the user's mouse. PC-Control ``click``."""
        params = {"window": window, "target": target, "right": right, "double": double}
        return self._call("pc_click", params, lambda: _pc("click", params, self.settings, dry_run))

    def pc_type(
        self,
        window: str,
        target: str,
        text: str,
        replace: bool = False,
        *,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        """Type into an element id from ``pc_look``. PC-Control ``type``. No blind typing."""
        params = {"window": window, "target": target, "text": text, "replace": replace}
        return self._call("pc_type", params, lambda: _pc("type", params, self.settings, dry_run))

    def pc_drag(
        self,
        window: str,
        points: str,
        shape: str = "path",
        right: bool = False,
        *,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        """Drag through image points. PC-Control ``drag``. Not ``mouse_drag``."""
        params = {"window": window, "points": points, "shape": shape, "right": right}
        return self._call("pc_drag", params, lambda: _pc("drag", params, self.settings, dry_run))

    def pc_key(
        self,
        window: str,
        name: str,
        *,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        """A key or the app's own shortcut command. PC-Control ``key``. Not ``keyboard_hotkey``."""
        params = {"window": window, "name": name}
        return self._call("pc_key", params, lambda: _pc("key", params, self.settings, dry_run))

    def pc_scroll(
        self,
        window: str,
        direction: str = "down",
        target: str = "",
        amount: int = 1,
        *,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        """Scroll a window or element. PC-Control ``scroll``."""
        params = {"window": window, "direction": direction, "target": target, "amount": amount}
        return self._call("pc_scroll", params, lambda: _pc("scroll", params, self.settings, dry_run))

    def pc_read(
        self,
        window: str,
        target: str = "",
        start: int = 0,
        length: int = 6000,
        find: str = "",
    ) -> dict[str, Any]:
        """Read a document, page, or field, including text out of view. PC-Control ``read``."""
        params = {"window": window, "target": target, "start": start, "length": length, "find": find}
        return self._call("pc_read", params, lambda: _pc("read", params, self.settings, None))

    def pc_show(
        self,
        window: str,
        target: str,
        label: str = "",
        seconds: int = 10,
        *,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        """Draw an orange circle for the user. PC-Control ``show``. Nothing is clicked."""
        params = {"window": window, "target": target, "label": label, "seconds": seconds}
        return self._call("pc_show", params, lambda: _pc("show", params, self.settings, dry_run))

    def pc_open_app(
        self,
        command: str,
        hidden: bool = False,
        *,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        """Launch an app minimized, or on the hidden desktop. PC-Control ``open_app``."""
        params = {"command": command, "hidden": hidden}
        return self._call("pc_open_app", params, lambda: _pc("open_app", params, self.settings, dry_run))

    def _capture_full(self):
        from desktop_agent.vision.capture import capture_full

        return capture_full(
            self._grabber(),
            self.settings.output_dir,
            max_side=self.settings.max_model_side,
            norm_size=self.settings.norm_size,
        )

    def _ocr(self, shot: Any, language: str) -> dict[str, Any]:
        read = self.ocr.read(shot.image, language)
        read["ok"] = True
        read["path"] = str(shot.path)
        read["model_path"] = str(shot.model_path)
        read["model_size"] = [shot.model_size[0], shot.model_size[1]]
        read["region"] = list(shot.region) if shot.region else None
        return read


def _summary_text(name: str, params: dict[str, Any] | None, outcome: dict[str, Any] | None) -> str:
    return f"{name}\nparams={params or {}}\noutcome={outcome or {}}"


def get_bridge() -> Bridge:
    """Process-wide bridge built from ``Settings.load()``."""
    global _bridge
    if _bridge is None:
        _bridge = Bridge()
    return _bridge


def reset_bridge(bridge: Bridge | None = None) -> Bridge:
    """Replace the process-wide bridge. Tests use this."""
    global _bridge
    _bridge = bridge if bridge is not None else Bridge()
    return _bridge


def memory_add_event(
    name: str,
    params: dict[str, Any] | None = None,
    outcome: dict[str, Any] | None = None,
    *,
    kind: str = "note",
    session_id: str = "default",
    archive: bool = False,
) -> dict[str, Any]:
    """Record a session event on the process bridge. See ``Bridge.memory_add_event``."""
    return get_bridge().memory_add_event(
        name, params, outcome, kind=kind, session_id=session_id, archive=archive
    )


def memory_search(query: str, limit: int = 10, **options: Any) -> dict[str, Any]:
    """Search long-term memory on the process bridge."""
    return get_bridge().memory_search(query, limit=limit, **options)


def memory_get_recent(limit: int = 20, session_id: str | None = None) -> dict[str, Any]:
    """Recent session events on the process bridge."""
    return get_bridge().memory_get_recent(limit=limit, session_id=session_id)


def screen_capture_full() -> dict[str, Any]:
    """Full-screen capture on the process bridge."""
    return get_bridge().screen_capture_full()


def screen_capture_region(x1: int, y1: int, x2: int, y2: int) -> dict[str, Any]:
    """Region capture on the process bridge."""
    return get_bridge().screen_capture_region(x1, y1, x2, y2)


def screen_ocr_full(language: str | None = None) -> dict[str, Any]:
    """Full-screen OCR on the process bridge."""
    return get_bridge().screen_ocr_full(language)


def screen_ocr_region(
    x1: int, y1: int, x2: int, y2: int, language: str | None = None
) -> dict[str, Any]:
    """Region OCR on the process bridge."""
    return get_bridge().screen_ocr_region(x1, y1, x2, y2, language)


def mouse_move(
    x: int,
    y: int,
    *,
    dry_run: bool | None = None,
    label: str | None = None,
    app_name: str | None = None,
    approved: bool = False,
) -> dict[str, Any]:
    """Move the cursor on the process bridge."""
    return get_bridge().mouse_move(x, y, dry_run=dry_run, label=label, app_name=app_name, approved=approved)


def mouse_click(
    x: int,
    y: int,
    *,
    button: str = "left",
    double: bool = False,
    dry_run: bool | None = None,
    label: str | None = None,
    app_name: str | None = None,
    approved: bool = False,
) -> dict[str, Any]:
    """Click on the process bridge."""
    return get_bridge().mouse_click(
        x, y, button=button, double=double, dry_run=dry_run, label=label, app_name=app_name, approved=approved
    )


def mouse_drag(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    *,
    duration: float = 0.2,
    button: str = "left",
    dry_run: bool | None = None,
    label: str | None = None,
    app_name: str | None = None,
    approved: bool = False,
) -> dict[str, Any]:
    """Drag on the process bridge."""
    return get_bridge().mouse_drag(
        x1,
        y1,
        x2,
        y2,
        duration=duration,
        button=button,
        dry_run=dry_run,
        label=label,
        app_name=app_name,
        approved=approved,
    )


def keyboard_type(
    text: str,
    *,
    dry_run: bool | None = None,
    label: str | None = None,
    field_role: str | None = None,
    app_name: str | None = None,
    approved: bool = False,
) -> dict[str, Any]:
    """Type text on the process bridge."""
    return get_bridge().keyboard_type(
        text,
        dry_run=dry_run,
        label=label,
        field_role=field_role,
        app_name=app_name,
        approved=approved,
    )


def keyboard_hotkey(
    key: str,
    *,
    dry_run: bool | None = None,
    label: str | None = None,
    app_name: str | None = None,
    approved: bool = False,
) -> dict[str, Any]:
    """Press a key or combo on the process bridge."""
    return get_bridge().keyboard_hotkey(key, dry_run=dry_run, label=label, app_name=app_name, approved=approved)


def window_focus(
    title: str | None = None,
    pid: int | None = None,
    *,
    dry_run: bool | None = None,
    label: str | None = None,
    approved: bool = False,
) -> dict[str, Any]:
    """Focus a window on the process bridge."""
    return get_bridge().window_focus(title, pid, dry_run=dry_run, label=label, approved=approved)


def pc_windows(filter: str = "") -> dict[str, Any]:
    """PC-Control ``windows`` on the process bridge."""
    return get_bridge().pc_windows(filter)


def pc_look(window: str, mode: str = "auto", find: str = "", wait: float = 0) -> dict[str, Any]:
    """PC-Control ``look`` on the process bridge."""
    return get_bridge().pc_look(window, mode=mode, find=find, wait=wait)


def pc_click(
    window: str,
    target: str,
    right: bool = False,
    double: bool = False,
    *,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    """PC-Control ``click`` on the process bridge."""
    return get_bridge().pc_click(window, target, right=right, double=double, dry_run=dry_run)


def pc_type(
    window: str,
    target: str,
    text: str,
    replace: bool = False,
    *,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    """PC-Control ``type`` on the process bridge."""
    return get_bridge().pc_type(window, target, text, replace=replace, dry_run=dry_run)


def pc_drag(
    window: str,
    points: str,
    shape: str = "path",
    right: bool = False,
    *,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    """PC-Control ``drag`` on the process bridge."""
    return get_bridge().pc_drag(window, points, shape=shape, right=right, dry_run=dry_run)


def pc_key(window: str, name: str, *, dry_run: bool | None = None) -> dict[str, Any]:
    """PC-Control ``key`` on the process bridge."""
    return get_bridge().pc_key(window, name, dry_run=dry_run)


def pc_scroll(
    window: str,
    direction: str = "down",
    target: str = "",
    amount: int = 1,
    *,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    """PC-Control ``scroll`` on the process bridge."""
    return get_bridge().pc_scroll(window, direction=direction, target=target, amount=amount, dry_run=dry_run)


def pc_read(
    window: str,
    target: str = "",
    start: int = 0,
    length: int = 6000,
    find: str = "",
) -> dict[str, Any]:
    """PC-Control ``read`` on the process bridge."""
    return get_bridge().pc_read(window, target=target, start=start, length=length, find=find)


def pc_show(
    window: str,
    target: str,
    label: str = "",
    seconds: int = 10,
    *,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    """PC-Control ``show`` on the process bridge."""
    return get_bridge().pc_show(window, target, label=label, seconds=seconds, dry_run=dry_run)


def pc_open_app(command: str, hidden: bool = False, *, dry_run: bool | None = None) -> dict[str, Any]:
    """PC-Control ``open_app`` on the process bridge."""
    return get_bridge().pc_open_app(command, hidden=hidden, dry_run=dry_run)


def windows(filter: str = "") -> dict[str, Any]:
    """PC-Control ``windows`` on the process bridge. The kit name."""
    return get_bridge().windows(filter)


def look(window: str, mode: str = "auto", find: str = "", wait: float = 0) -> dict[str, Any]:
    """PC-Control ``look`` on the process bridge. The kit name."""
    return get_bridge().look(window, mode=mode, find=find, wait=wait)


def click(
    window: str,
    target: str,
    right: bool = False,
    double: bool = False,
    *,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    """PC-Control ``click`` on the process bridge. Not ``mouse_click``."""
    return get_bridge().click(window, target, right=right, double=double, dry_run=dry_run)


def type(
    window: str,
    target: str,
    text: str,
    replace: bool = False,
    *,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    """PC-Control ``type`` on the process bridge. Not ``keyboard_type``."""
    return get_bridge().type(window, target, text, replace=replace, dry_run=dry_run)


def drag(
    window: str,
    points: str,
    shape: str = "path",
    right: bool = False,
    *,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    """PC-Control ``drag`` on the process bridge. Not ``mouse_drag``."""
    return get_bridge().drag(window, points, shape=shape, right=right, dry_run=dry_run)


def key(window: str, name: str, *, dry_run: bool | None = None) -> dict[str, Any]:
    """PC-Control ``key`` on the process bridge."""
    return get_bridge().key(window, name, dry_run=dry_run)


def scroll(
    window: str,
    direction: str = "down",
    target: str = "",
    amount: int = 1,
    *,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    """PC-Control ``scroll`` on the process bridge."""
    return get_bridge().scroll(window, direction=direction, target=target, amount=amount, dry_run=dry_run)


def read(
    window: str,
    target: str = "",
    start: int = 0,
    length: int = 6000,
    find: str = "",
) -> dict[str, Any]:
    """PC-Control ``read`` on the process bridge."""
    return get_bridge().read(window, target=target, start=start, length=length, find=find)


def show(
    window: str,
    target: str,
    label: str = "",
    seconds: int = 10,
    *,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    """PC-Control ``show`` on the process bridge."""
    return get_bridge().show(window, target, label=label, seconds=seconds, dry_run=dry_run)


def open_app(command: str, hidden: bool = False, *, dry_run: bool | None = None) -> dict[str, Any]:
    """PC-Control ``open_app`` on the process bridge."""
    return get_bridge().open_app(command, hidden=hidden, dry_run=dry_run)
