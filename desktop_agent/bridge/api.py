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
from desktop_agent.control.mouse import click, drag, move_mouse
from desktop_agent.control.window import focus_window
from desktop_agent.core.logging import configure_logging, get_logger
from desktop_agent.core.settings import Settings
from desktop_agent.memory.manager import MemoryManager
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
            lambda: click(
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
            lambda: drag(
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
