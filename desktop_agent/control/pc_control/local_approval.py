"""One-shot approval by the person at this PC.

Not an MCP tool, not a chat reply, and not the connect PIN.
"""
from __future__ import annotations

import ctypes
import logging
import threading
import time
from ctypes import wintypes

log = logging.getLogger("pc_control.approval")
TTL = 20.0
_WAIT = 45.0
_TITLE = "MilesVision approval"
# MB_YESNO | MB_DEFBUTTON2 | MB_ICONWARNING | MB_SETFOREGROUND | MB_TOPMOST
_BOX_FLAGS = 0x00000004 | 0x00000100 | 0x00000030 | 0x00010000 | 0x00040000
_lock = threading.Lock()
_grant: tuple[str, int, float] | None = None
_dialog = 0


def is_approval_window(hwnd: int) -> bool:
    if not hwnd:
        return False
    with _lock:
        if int(hwnd) == _dialog:
            return True
    user32 = ctypes.windll.user32
    buf = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(int(hwnd), buf, 64)
    if buf.value != "#32770":
        return False
    title = ctypes.create_unicode_buffer(120)
    user32.GetWindowTextW(int(hwnd), title, 120)
    return title.value == _TITLE


def take(action: str, hwnd: int) -> bool:
    """Consume the one stored grant. Only the same action and hwnd succeed."""
    global _grant
    now = time.monotonic()
    with _lock:
        current = _grant
        if current is None:
            return False
        act, win, exp = current
        _grant = None
        return act == action and win == int(hwnd) and now <= exp


def _store(action: str, hwnd: int) -> None:
    global _grant
    with _lock:
        _grant = (action, int(hwnd), time.monotonic() + TTL)


def ask(action: str, hwnd: int, category: str) -> str:
    """Block until the person at this PC chooses, or the wait ends.

    Returns ``allow``, ``deny``, or ``timeout``. The question is not returned
    to the caller for the model to answer.
    """
    decision = _message_box(action, int(hwnd), category)
    log.info(
        "protected decision action=%s hwnd=%s category=%s decision=%s",
        action,
        int(hwnd),
        category,
        decision,
    )
    if decision == "allow":
        _store(action, int(hwnd))
    return decision


def decide(why: str | None, action: str, hwnd: int, ask_fn=ask, take_fn=take) -> None:
    """Fail closed unless this action on this hwnd was just allowed."""
    if not why:
        return
    from .server import ToolError

    if take_fn(action, hwnd):
        return
    if ask_fn(action, hwnd, why) != "allow" or not take_fn(action, hwnd):
        raise ToolError(
            "Not executed. The person at this PC did not approve this action on this window."
        )


def _message_box(action: str, hwnd: int, category: str) -> str:
    """Show the box on a worker thread. The caller never waits longer than 45s."""
    global _dialog
    user32 = ctypes.windll.user32
    user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
    user32.MessageBoxW.restype = ctypes.c_int
    done = threading.Event()
    result: dict[str, int | None] = {"code": None}
    found: dict[str, int] = {}

    def _show() -> None:
        try:
            result["code"] = int(
                user32.MessageBoxW(
                    0,
                    "Allow this one PC-Control action on this window?\n\n"
                    f"Action: {action}\nCategory: {category}\nWindow id: {hwnd}",
                    _TITLE,
                    _BOX_FLAGS,
                )
            )
        except Exception:
            result["code"] = None
        finally:
            done.set()

    def _watch() -> None:
        global _dialog
        buf = ctypes.create_unicode_buffer(120)
        enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _each(window, _lparam):
            user32.GetWindowTextW(window, buf, 120)
            if buf.value == _TITLE:
                found["hwnd"] = int(window)
                return False
            return True

        while not done.is_set():
            user32.EnumWindows(enum_proc(_each), 0)
            if "hwnd" in found:
                with _lock:
                    _dialog = found["hwnd"]
                return
            time.sleep(0.05)

    threading.Thread(target=_show, daemon=True).start()
    threading.Thread(target=_watch, daemon=True).start()
    finished = done.wait(_WAIT)
    known = found.get("hwnd", 0)
    with _lock:
        _dialog = 0
    if not finished:
        if known:
            user32.PostMessageW(known, 0x0010, 0, 0)  # WM_CLOSE
        return "timeout"
    code = result["code"]
    if code == 6:  # IDYES
        return "allow"
    return "deny"
