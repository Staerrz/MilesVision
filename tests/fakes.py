"""Test doubles for grab, OCR, and input. They do not touch Win32."""

from __future__ import annotations

from typing import Any

from PIL import Image


class FakeGrabber:
    def grab(self, bbox: tuple[int, int, int, int] | None) -> Image.Image:
        if bbox is None:
            return Image.new("RGB", (320, 200), "white")
        width = max(1, bbox[2] - bbox[0])
        height = max(1, bbox[3] - bbox[1])
        return Image.new("RGB", (width, height), "blue")

    def active_window(self) -> tuple[str, tuple[int, int, int, int]]:
        return "Notepad", (5, 6, 105, 86)


class FakeOcr:
    name = "fake"

    def read(self, image: Image.Image, language: str = "eng") -> dict[str, Any]:
        return {
            "engine": self.name,
            "count": 1,
            "items": [{"text": "Notepad", "box_pixel": [10, 20, 50, 40], "confidence": 90}],
            "image_size": [image.width, image.height],
            "language": language,
        }


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def move(self, x: int, y: int) -> None:
        self.calls.append(("move", x, y))

    def click(self, x: int, y: int, button: str, double: bool) -> None:
        self.calls.append(("click", x, y, button, double))

    def drag(self, x1: int, y1: int, x2: int, y2: int, duration: float, button: str) -> None:
        self.calls.append(("drag", x1, y1, x2, y2, duration, button))

    def type_text(self, text: str) -> str:
        self.calls.append(("type", text))
        return "keyboard"

    def press(self, key: str) -> None:
        self.calls.append(("press", key))

    def focus(self, title: str | None, pid: int | None) -> dict[str, object]:
        self.calls.append(("focus", title, pid))
        return {"hwnd": 1, "title": title or "", "pid": pid}

    def launch(self, name: str) -> dict[str, object]:
        self.calls.append(("launch", name))
        return {"name": name, "starter_pid": 1}

    def open_url(self, url: str) -> None:
        self.calls.append(("open_url", url))
