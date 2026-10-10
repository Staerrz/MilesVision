"""Screen capture, model downsample, and swappable OCR."""

from desktop_agent.vision.capture import capture_active_window, capture_full, capture_region
from desktop_agent.vision.downsample import fit_model
from desktop_agent.vision.ocr import build_ocr

__all__ = [
    "build_ocr",
    "capture_active_window",
    "capture_full",
    "capture_region",
    "fit_model",
]
