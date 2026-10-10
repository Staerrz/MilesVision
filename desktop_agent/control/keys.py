"""Key names shared by typing and hotkeys.

Virtual-key codes are the ``_VK`` table in ``vision-primitives-mcp``.
``parse_combo`` merges that table with ``dsh-computer-use`` ``dispatchKey``
modifier names: ``cmd`` and ``command`` become ``win``, ``control`` becomes
``ctrl``, ``option`` becomes ``alt``.

``key_for_char`` rewrites ``_vk_for_char``. The source accepts digits and
``A-Z`` only, so a lowercase letter and a space never resolve. Space is the
named ``space`` entry (``0x20``). Letters use the same ``A-Z`` virtual key.
Uppercase asks for shift, because ``keybd_event`` on that virtual key types
the lowercase letter when shift is up.
"""

from __future__ import annotations

VK: dict[str, int] = {
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "backspace": 0x08,
    "space": 0x20,
    "escape": 0x1B,
    "esc": 0x1B,
    "delete": 0x2E,
    "insert": 0x2D,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "ctrl": 0x11,
    "shift": 0x10,
    "alt": 0x12,
    "win": 0x5B,
    "capslock": 0x14,
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
}

MODIFIERS = frozenset({"ctrl", "shift", "alt", "win"})

_MOD_ALIAS = {
    "cmd": "win",
    "command": "win",
    "control": "ctrl",
    "option": "alt",
}


class KeyError_(ValueError):
    """A key or character is outside the vision-primitives set."""


def key_for_char(ch: str) -> tuple[int, bool]:
    """Return ``(virtual_key, needs_shift)`` for one ASCII character."""
    if len(ch) != 1:
        raise KeyError_(f"unsupported character: {ch!r}")
    if "a" <= ch <= "z":
        return ord(ch.upper()), False
    if "A" <= ch <= "Z":
        return ord(ch), True
    if "0" <= ch <= "9":
        return ord(ch), False
    if ch == " ":
        return VK["space"], False
    named = VK.get(ch.lower())
    if named is not None:
        return named, False
    raise KeyError_(f"unsupported character: {ch!r}")


def type_method(text: str) -> str:
    """``keyboard`` for ASCII that ``key_for_char`` accepts, else ``clipboard``.

    ``tool_screen_type`` sends the whole string through the clipboard when any
    character is non-ASCII. Unsupported ASCII (punctuation) still raises, as
    the source does, but the check runs before any key is pressed.
    """
    if not text:
        raise KeyError_("text is empty")
    if all(ord(ch) < 128 for ch in text):
        for ch in text:
            key_for_char(ch)
        return "keyboard"
    return "clipboard"


def parse_combo(combo: str) -> tuple[list[str], list[str]]:
    """Split ``ctrl+c`` into modifiers and keys. Names are normalized."""
    parts = [_MOD_ALIAS.get(part.strip().lower(), part.strip().lower()) for part in combo.split("+")]
    parts = [part for part in parts if part]
    mods = [part for part in parts if part in MODIFIERS]
    keys = [part for part in parts if part not in MODIFIERS]
    if not keys:
        raise KeyError_(f"no key in combo: {combo!r}")
    for key in keys:
        if len(key) == 1:
            key_for_char(key)
        elif key not in VK:
            raise KeyError_(f"unsupported key: {key}")
    return mods, keys


def drag_points(x1: int, y1: int, x2: int, y2: int, duration: float) -> list[tuple[int, int]]:
    """Intermediate cursor points from ``tool_screen_drag``.

    Step count is ``max(1, int(duration * 50))``. Each step is integer
    interpolation from the start point to the end point.
    """
    steps = max(1, int(duration * 50))
    points: list[tuple[int, int]] = []
    for index in range(1, steps + 1):
        cx = x1 + (x2 - x1) * index // steps
        cy = y1 + (y2 - y1) * index // steps
        points.append((cx, cy))
    return points
