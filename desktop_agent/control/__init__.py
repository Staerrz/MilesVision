"""Mouse, keyboard, and window actions. Every action is logged."""

from desktop_agent.control.keyboard import press, type_text
from desktop_agent.control.mouse import click, drag, move_mouse
from desktop_agent.control.window import focus_window, launch_app, open_url

__all__ = [
    "click",
    "drag",
    "focus_window",
    "launch_app",
    "move_mouse",
    "open_url",
    "press",
    "type_text",
]
