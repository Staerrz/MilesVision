"""The only API a model calls."""

from desktop_agent.bridge.api import (
    Bridge,
    get_bridge,
    keyboard_hotkey,
    keyboard_type,
    memory_add_event,
    memory_get_recent,
    memory_search,
    mouse_click,
    mouse_drag,
    mouse_move,
    screen_capture_full,
    screen_capture_region,
    screen_ocr_full,
    screen_ocr_region,
    window_focus,
)

__all__ = [
    "Bridge",
    "get_bridge",
    "keyboard_hotkey",
    "keyboard_type",
    "memory_add_event",
    "memory_get_recent",
    "memory_search",
    "mouse_click",
    "mouse_drag",
    "mouse_move",
    "screen_capture_full",
    "screen_capture_region",
    "screen_ocr_full",
    "screen_ocr_region",
    "window_focus",
]
