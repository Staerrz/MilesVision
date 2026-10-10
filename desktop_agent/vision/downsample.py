"""Downsample a screenshot before it is sent to a vision model.

``fit_model`` and ``scale_geo`` are ``vision-primitives-mcp`` ``_fit_model``
and ``_scale_geo``. ``NORM_SIZE`` / ``MAX_MODEL_SIDE`` keep the same meaning:
a positive norm size forces the long side, otherwise the image is only
shrunk when the long side exceeds the cap. The default cap is 2600.

``ollama-vision-mcp`` ``ImageHandler._process_image_bytes`` thumbnails to
2048. That path is the Ollama request encoder, not this function. Callers
that talk to Ollama still send the fitted image through the OCR swap.
"""

from __future__ import annotations

from typing import Any

from PIL import Image


def fit_model(
    img: Image.Image,
    *,
    max_side: int = 2600,
    norm_size: int = 0,
) -> tuple[Image.Image, float, float]:
    """Return ``(model image, scale_x, scale_y)``.

    ``scale_x`` and ``scale_y`` convert model pixels back to source pixels
    (source = model * scale), matching ``_fit_model``.
    """
    width, height = img.size
    long_side = max(width, height)
    if norm_size > 0:
        ratio = norm_size / long_side
        new_w = max(1, round(width * ratio))
        new_h = max(1, round(height * ratio))
        fitted = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        return fitted, width / new_w, height / new_h
    if long_side <= max_side:
        return img, 1.0, 1.0
    ratio = max_side / long_side
    new_w = max(1, round(width * ratio))
    new_h = max(1, round(height * ratio))
    fitted = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    return fitted, width / new_w, height / new_h


def scale_geo(geo: dict[str, Any], scale_x: float, scale_y: float) -> dict[str, Any]:
    """Map source-pixel geometry onto the model image.

    This is ``_scale_geo``. Points divide by the scales returned from
    ``fit_model``.
    """
    scaled: dict[str, Any] = {}
    for key, value in geo.items():
        if key == "points" and isinstance(value, list):
            scaled[key] = [[round(x / scale_x), round(y / scale_y)] for x, y in value]
        elif (
            key in {"box", "from", "to", "center", "point"}
            and isinstance(value, list)
            and len(value) in (2, 4)
            and all(isinstance(item, (int, float)) for item in value)
        ):
            if len(value) == 2:
                scaled[key] = [round(value[0] / scale_x), round(value[1] / scale_y)]
            else:
                scaled[key] = [
                    round(value[0] / scale_x),
                    round(value[1] / scale_y),
                    round(value[2] / scale_x),
                    round(value[3] / scale_y),
                ]
        elif key == "radius" and isinstance(value, (int, float)):
            scaled[key] = max(1, round(value / min(scale_x, scale_y)))
        else:
            scaled[key] = value
    return scaled
