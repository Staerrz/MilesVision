"""Full screen, region, and active-window capture.

``capture_full`` and ``capture_region`` rewrite ``tool_screen_capture``:
Pillow ``ImageGrab.grab`` with an optional ``[x1, y1, x2, y2]`` bbox.
The saved PNG name follows ``_unique_path``.

Active-window capture uses that same region grab. The rectangle comes from
``GetForegroundWindow`` and ``GetWindowRect``. ``tool_screen_info`` already
talks to ``user32`` (``GetSystemMetrics``, ``GetDesktopWindow``, DPI). It
does not read the foreground window, so the foreground query is the Windows
call that makes "active window" a region capture rather than a new vision
stack.

Every capture also runs ``fit_model`` and writes a second PNG for model
input. OCR should use the full image. ``tool_ocr_image`` does not downsample.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from PIL import Image

from desktop_agent.core.logging import get_logger
from desktop_agent.vision.downsample import fit_model

log = get_logger("vision.capture")


class CaptureError(RuntimeError):
    """The screen could not be captured."""


class Grabber(Protocol):
    """Screen source. Tests supply a fake. Windows uses ``ImageGrab``."""

    def grab(self, bbox: tuple[int, int, int, int] | None) -> Image.Image:
        """Return the full screen, or the pixels inside ``bbox``."""

    def active_window(self) -> tuple[str, tuple[int, int, int, int]]:
        """Return ``(title, (left, top, right, bottom))`` for the foreground window."""


@dataclass
class Capture:
    """One screenshot plus the downsampled model image."""

    image: Image.Image
    path: Path
    model_image: Image.Image
    model_path: Path
    size: tuple[int, int]
    model_size: tuple[int, int]
    region: tuple[int, int, int, int] | None
    scale_x: float
    scale_y: float
    window_title: str | None = None

    def as_dict(self) -> dict[str, object]:
        """JSON-ready description. Pixel buffers stay on disk."""
        return {
            "path": str(self.path),
            "model_path": str(self.model_path),
            "size": [self.size[0], self.size[1]],
            "model_size": [self.model_size[0], self.model_size[1]],
            "region": list(self.region) if self.region else None,
            "scale_x": self.scale_x,
            "scale_y": self.scale_y,
            "window_title": self.window_title,
        }


_seq = 0


def _unique_path(output_dir: Path, prefix: str) -> Path:
    """PNG path under the output directory.

    The vision-primitives name is ``{prefix}_{timestamp}_{pid}.png``. A counter
    is appended so two captures in the same second do not overwrite each other.
    """
    global _seq
    _seq += 1
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return output_dir / f"{prefix}_{stamp}_{os.getpid()}_{_seq}.png"


def _store(
    image: Image.Image,
    output_dir: Path,
    prefix: str,
    region: tuple[int, int, int, int] | None,
    *,
    max_side: int,
    norm_size: int,
    window_title: str | None = None,
) -> Capture:
    path = _unique_path(output_dir, prefix)
    image.save(path, "PNG")
    model_image, scale_x, scale_y = fit_model(image, max_side=max_side, norm_size=norm_size)
    model_path = _unique_path(output_dir, prefix + "_model")
    if model_path == path:
        model_path = path.with_name(path.stem + "_model" + path.suffix)
    model_image.save(model_path, "PNG")
    log.info("captured %s %sx%s model %sx%s", path.name, image.width, image.height, model_image.width, model_image.height)
    return Capture(
        image=image,
        path=path,
        model_image=model_image,
        model_path=model_path,
        size=(image.width, image.height),
        model_size=(model_image.width, model_image.height),
        region=region,
        scale_x=scale_x,
        scale_y=scale_y,
        window_title=window_title,
    )


def capture_full(
    grabber: Grabber,
    output_dir: Path,
    *,
    max_side: int = 2600,
    norm_size: int = 0,
) -> Capture:
    """Capture the whole screen. ``region`` in the result is ``None``."""
    image = grabber.grab(None)
    return _store(image, output_dir, "screen", None, max_side=max_side, norm_size=norm_size)


def capture_region(
    grabber: Grabber,
    output_dir: Path,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    *,
    max_side: int = 2600,
    norm_size: int = 0,
) -> Capture:
    """Capture ``[x1, y1, x2, y2]``. The box must have positive area."""
    if x2 <= x1 or y2 <= y1:
        raise CaptureError("region is invalid; x2 and y2 must be greater than x1 and y1")
    region = (int(x1), int(y1), int(x2), int(y2))
    image = grabber.grab(region)
    return _store(image, output_dir, "screen_region", region, max_side=max_side, norm_size=norm_size)


def capture_active_window(
    grabber: Grabber,
    output_dir: Path,
    *,
    max_side: int = 2600,
    norm_size: int = 0,
) -> Capture:
    """Capture the foreground window by grabbing its screen rectangle."""
    title, region = grabber.active_window()
    if region[2] <= region[0] or region[3] <= region[1]:
        raise CaptureError(f"active window rectangle is empty: {region}")
    image = grabber.grab(region)
    return _store(
        image,
        output_dir,
        "screen_window",
        region,
        max_side=max_side,
        norm_size=norm_size,
        window_title=title,
    )


class WindowsGrabber:
    """``ImageGrab`` plus the foreground window rectangle.

    DPI awareness follows ``tool_screen_info``: ``SetProcessDpiAwareness(1)``
    so grab coordinates match the Win32 window rectangle.
    """

    def __init__(self) -> None:
        self._dpi_ready = False

    def grab(self, bbox: tuple[int, int, int, int] | None) -> Image.Image:
        self._ensure_windows()
        self._dpi()
        from PIL import ImageGrab

        if bbox is None:
            return ImageGrab.grab()
        return ImageGrab.grab(bbox=bbox)

    def active_window(self) -> tuple[str, tuple[int, int, int, int]]:
        self._ensure_windows()
        self._dpi()
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            raise CaptureError("no foreground window")
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise CaptureError("GetWindowRect failed")
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        box = (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
        return buffer.value, box

    def _ensure_windows(self) -> None:
        if sys.platform != "win32":
            raise CaptureError("screen capture requires Windows")

    def _dpi(self) -> None:
        if self._dpi_ready:
            return
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass
        self._dpi_ready = True


GrabberFactory = Callable[[], Grabber]


def default_grabber() -> Grabber:
    """The Windows grabber. Import of ``ImageGrab`` waits until a capture."""
    return WindowsGrabber()
