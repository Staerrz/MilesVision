"""Windows input backend, and the protocol tests substitute.

The Win32 calls are ``vision-primitives-mcp`` ``tool_screen_move``,
``tool_screen_click``, ``tool_screen_drag``, ``tool_screen_type``, and
``tool_screen_key``: ``SetCursorPos``, ``mouse_event``, ``keybd_event``.
Non-ASCII typing still shells out to PowerShell ``Set-Clipboard`` and then
``ctrl+v``.

``focus`` is the Windows rewrite of ``dsh-computer-use`` ``launchApp``'s
``bring_to_front``: ``FindWindowW`` or a pid scan, then ``ShowWindow`` and
``SetForegroundWindow``. ``launch`` is ``cmd /c start``. ``open_url`` is
``os.startfile``. No source function opens a URL; the control surface asks
for it, and the Windows shell is the whole implementation.
"""

from __future__ import annotations

import sys
import time
from typing import Protocol

from desktop_agent.control.keys import VK, key_for_char, parse_combo, type_method

KEYEVENTF_KEYUP = 0x0002
MOUSE_DOWN = {"left": 0x0002, "right": 0x0008, "middle": 0x0020}
MOUSE_UP = {"left": 0x0004, "right": 0x0010, "middle": 0x0040}
SW_RESTORE = 9


class PlatformError(RuntimeError):
    """The call needs a Windows desktop."""


class InputBackend(Protocol):
    """What mouse, keyboard, and window functions call after the gate."""

    def move(self, x: int, y: int) -> None: ...

    def click(self, x: int, y: int, button: str, double: bool) -> None: ...

    def drag(self, x1: int, y1: int, x2: int, y2: int, duration: float, button: str) -> None: ...

    def type_text(self, text: str) -> str: ...

    def press(self, key: str) -> None: ...

    def focus(self, title: str | None, pid: int | None) -> dict[str, object]: ...

    def launch(self, name: str) -> dict[str, object]: ...

    def open_url(self, url: str) -> None: ...


def _require_windows() -> None:
    if sys.platform != "win32":
        raise PlatformError("mouse, keyboard, and window actions require Windows")


def _user32():  # type: ignore[no-untyped-def]
    import ctypes

    _require_windows()
    return ctypes.windll.user32


class Win32Backend:
    """user32 implementation. Methods raise ``PlatformError`` off Windows."""

    def move(self, x: int, y: int) -> None:
        user32 = _user32()
        user32.SetCursorPos(int(x), int(y))

    def click(self, x: int, y: int, button: str, double: bool) -> None:
        user32 = _user32()
        user32.SetCursorPos(int(x), int(y))
        time.sleep(0.05)
        down = MOUSE_DOWN[button]
        up = MOUSE_UP[button]
        user32.mouse_event(down, 0, 0, 0, 0)
        time.sleep(0.05)
        user32.mouse_event(up, 0, 0, 0, 0)
        if double:
            time.sleep(0.05)
            user32.mouse_event(down, 0, 0, 0, 0)
            time.sleep(0.05)
            user32.mouse_event(up, 0, 0, 0, 0)

    def drag(self, x1: int, y1: int, x2: int, y2: int, duration: float, button: str) -> None:
        from desktop_agent.control.keys import drag_points

        user32 = _user32()
        down = MOUSE_DOWN[button]
        up = MOUSE_UP[button]
        user32.SetCursorPos(int(x1), int(y1))
        time.sleep(0.05)
        user32.mouse_event(down, 0, 0, 0, 0)
        points = drag_points(x1, y1, x2, y2, duration)
        step_sleep = duration / max(1, len(points))
        for cx, cy in points:
            user32.SetCursorPos(cx, cy)
            time.sleep(step_sleep)
        user32.mouse_event(up, 0, 0, 0, 0)

    def type_text(self, text: str) -> str:
        method = type_method(text)
        if method == "keyboard":
            for ch in text:
                vk, needs_shift = key_for_char(ch)
                if needs_shift:
                    self._key_down(VK["shift"])
                self._tap(vk)
                if needs_shift:
                    self._key_up(VK["shift"])
            return method
        self._clipboard_paste(text)
        return method

    def press(self, key: str) -> None:
        normalized = key.strip().lower()
        if "+" in normalized:
            mods, keys = parse_combo(normalized)
            for mod in mods:
                self._key_down(VK[mod])
            for part in keys:
                if len(part) == 1:
                    vk, needs_shift = key_for_char(part)
                    if needs_shift:
                        self._key_down(VK["shift"])
                    self._tap(vk)
                    if needs_shift:
                        self._key_up(VK["shift"])
                else:
                    self._tap(VK[part])
            for mod in reversed(mods):
                self._key_up(VK[mod])
            return
        if len(normalized) == 1:
            vk, needs_shift = key_for_char(normalized)
            if needs_shift:
                self._key_down(VK["shift"])
            self._tap(vk)
            if needs_shift:
                self._key_up(VK["shift"])
            return
        if normalized not in VK:
            raise PlatformError(f"unsupported key: {normalized}")
        self._tap(VK[normalized])

    def focus(self, title: str | None, pid: int | None) -> dict[str, object]:
        import ctypes

        user32 = _user32()
        hwnd = 0
        if title:
            hwnd = user32.FindWindowW(None, title)
        if not hwnd and pid is not None:
            hwnd = _hwnd_for_pid(user32, int(pid))
        if not hwnd:
            raise PlatformError(f"window not found: title={title!r} pid={pid!r}")
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return {"hwnd": int(hwnd), "title": buffer.value, "pid": pid}

    def launch(self, name: str) -> dict[str, object]:
        import subprocess

        _require_windows()
        # CREATE_NO_WINDOW, the same flag tool_screen_type uses for PowerShell.
        completed = subprocess.Popen(  # noqa: S603
            ["cmd", "/c", "start", "", name],
            creationflags=0x08000000,
        )
        return {"name": name, "starter_pid": completed.pid}

    def open_url(self, url: str) -> None:
        import os

        _require_windows()
        os.startfile(url)  # type: ignore[attr-defined]

    def _tap(self, vk: int, hold: float = 0.03) -> None:
        self._key_down(vk)
        time.sleep(hold)
        self._key_up(vk)
        time.sleep(0.02)

    def _key_down(self, vk: int) -> None:
        _user32().keybd_event(vk, 0, 0, 0)

    def _key_up(self, vk: int) -> None:
        _user32().keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

    def _clipboard_paste(self, text: str) -> None:
        import base64
        import subprocess

        _require_windows()
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        command = (
            "[Console]::InputEncoding=[Text.Encoding]::UTF8; "
            "Set-Clipboard -Value ([Text.Encoding]::UTF8.GetString("
            f"[Convert]::FromBase64String('{encoded}')))"
        )
        subprocess.run(  # noqa: S603
            ["powershell", "-NoProfile", "-Command", command],
            creationflags=0x08000000,
            timeout=30,
            check=True,
        )
        for mod in ("ctrl",):
            self._key_down(VK[mod])
        self._tap(key_for_char("v")[0])
        self._key_up(VK["ctrl"])


def _hwnd_for_pid(user32, pid: int) -> int:  # type: ignore[no-untyped-def]
    import ctypes
    from ctypes import wintypes

    found = {"hwnd": 0}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd, _lparam):  # type: ignore[no-untyped-def]
        window_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
        if int(window_pid.value) == pid and user32.IsWindowVisible(hwnd):
            found["hwnd"] = int(hwnd)
            return False
        return True

    user32.EnumWindows(_enum, 0)
    return found["hwnd"]
