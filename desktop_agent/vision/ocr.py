"""OCR with a Tesseract default and two source swaps.

``TesseractOcr`` is the default. It is not in any of the four repos. The
layout asks for Tesseract and for an easy swap, so the other two engines are
the OCR functions that do exist:

* ``OllamaReadText`` — ``ollama-vision-mcp`` ``read_text``. The prompt is
  "Extract and transcribe all visible text in this image. If no text is
  visible, say 'No text found'". The HTTP body is ``OllamaClient.analyze_image``:
  ``POST {ollama_url}/api/generate`` with ``model``, ``prompt``, ``images``,
  ``stream: false``. The source returns one string, not boxes.
* ``VlmBoxOcr`` — ``vision-primitives-mcp`` ``tool_ocr_image``. The prompt asks
  for a JSON array of ``{"text", "box"}``. This client posts that prompt to
  the configured OpenAI-compatible ``/chat/completions`` endpoint. The MCP
  server, cache, and locate tools are not included.

Swap by constructing the engine, or set ``DESKTOP_AGENT_OCR`` to
``tesseract``, ``ollama``, or ``vlm``.
"""

from __future__ import annotations

import base64
import io
import json
import urllib.request
from typing import Any, Callable, Protocol

from PIL import Image

from desktop_agent.core.logging import get_logger
from desktop_agent.core.settings import Settings

log = get_logger("vision.ocr")

READ_TEXT_PROMPT = (
    "Extract and transcribe all visible text in this image. "
    "If no text is visible, say 'No text found'"
)

VLM_OCR_SYSTEM = (
    "你是辅助视觉分析模型。请仔细分析用户提供的图像，并严格按要求的输出格式作答。"
    "不要提及隐藏的推理过程、内部工具，也不要提到会有另一个模型阅读你的回答。"
    "直接给出分析与结论。"
)


class OcrError(RuntimeError):
    """OCR could not run."""


class OcrEngine(Protocol):
    """One OCR backend. ``read`` returns the ``tool_ocr_image`` item shape."""

    name: str

    def read(self, image: Image.Image, language: str = "eng") -> dict[str, Any]:
        """Read ``image`` and return ``count``, ``items``, ``image_size``, ``engine``."""


def _png_b64(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def words_to_items(data: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Turn a Tesseract ``image_to_data`` dict into OCR items.

    Each word with a positive confidence becomes one item. ``box_pixel`` is
    ``[x1, y1, x2, y2]``, the same box field ``tool_ocr_image`` emits.
    """
    texts = data.get("text") or []
    lefts = data.get("left") or []
    tops = data.get("top") or []
    widths = data.get("width") or []
    heights = data.get("height") or []
    confs = data.get("conf") or []
    items: list[dict[str, Any]] = []
    for index, raw in enumerate(texts):
        text = str(raw or "").strip()
        if not text:
            continue
        try:
            conf = float(confs[index])
        except (TypeError, ValueError, IndexError):
            conf = -1.0
        if conf < 0:
            continue
        left = int(lefts[index])
        top = int(tops[index])
        width = int(widths[index])
        height = int(heights[index])
        items.append(
            {
                "text": text,
                "box_pixel": [left, top, left + width, top + height],
                "confidence": conf,
            }
        )
    return items


class TesseractOcr:
    """Default OCR. Requires the Tesseract binary and ``pytesseract``."""

    name = "tesseract"

    def __init__(self, command: str | None = None, reader: Callable[..., dict[str, list[Any]]] | None = None) -> None:
        self.command = command
        self._reader = reader

    def read(self, image: Image.Image, language: str = "eng") -> dict[str, Any]:
        if self._reader is not None:
            data = self._reader(image, language)
        else:
            try:
                import pytesseract
            except ImportError as exc:
                raise OcrError(
                    "pytesseract is not installed. pip install pytesseract, install the "
                    "Tesseract binary, or set DESKTOP_AGENT_OCR=ollama or vlm."
                ) from exc
            if self.command:
                pytesseract.pytesseract.tesseract_cmd = self.command
            try:
                data = pytesseract.image_to_data(image, lang=language, output_type=pytesseract.Output.DICT)
            except pytesseract.TesseractNotFoundError as exc:
                raise OcrError(
                    "Tesseract binary was not found. Install it, set TESSERACT_CMD, "
                    "or set DESKTOP_AGENT_OCR=ollama or vlm."
                ) from exc
        items = words_to_items(data)
        return {
            "engine": self.name,
            "count": len(items),
            "items": items,
            "image_size": [image.width, image.height],
            "language": language,
        }


class OllamaReadText:
    """Swap-in OCR: the ``read_text`` prompt against a local Ollama model."""

    name = "ollama"

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llava-phi3",
        timeout: int = 120,
        poster: Callable[[str, dict[str, Any], int], dict[str, Any]] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._poster = poster or _post_json

    def read(self, image: Image.Image, language: str = "eng") -> dict[str, Any]:
        del language  # read_text has no language argument
        payload = {
            "model": self.model,
            "prompt": READ_TEXT_PROMPT,
            "images": [_png_b64(image)],
            "stream": False,
        }
        body = self._poster(f"{self.base_url}/api/generate", payload, self.timeout)
        text = str(body.get("response") or "").strip()
        items = []
        if text and text != "No text found":
            items.append({"text": text, "box_pixel": [0, 0, image.width, image.height], "confidence": None})
        return {
            "engine": self.name,
            "count": len(items),
            "items": items,
            "image_size": [image.width, image.height],
            "model": self.model,
        }


class VlmBoxOcr:
    """Swap-in OCR: ``tool_ocr_image`` JSON boxes from an OpenAI-compatible VLM."""

    name = "vlm"

    def __init__(
        self,
        api_base: str,
        api_key: str,
        model: str,
        timeout: int = 120,
        poster: Callable[[str, dict[str, Any], int, str], dict[str, Any]] | None = None,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._poster = poster

    def read(self, image: Image.Image, language: str = "eng") -> dict[str, Any]:
        if not self.api_key and self._poster is None:
            raise OcrError("VISION_API_KEY is not set; cannot use the vlm OCR engine")
        prompt = (
            "请对这张图像做 OCR：提取图像中所有文字块，输出 JSON 数组（每块一个对象，不要遗漏）:\n"
            '[{"text":"...","box":[x1,y1,x2,y2]}]\n'
            f"- box 为像素坐标，图像宽 {image.width}px 高 {image.height}px"
            + (f"\n- 语言提示：{language}" if language not in {"", "auto", "eng"} else "")
        )
        data_url = "data:image/png;base64," + _png_b64(image)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": VLM_OCR_SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
        }
        if self._poster is not None:
            body = self._poster(f"{self.api_base}/chat/completions", payload, self.timeout, self.api_key)
        else:
            body = _post_json(
                f"{self.api_base}/chat/completions",
                payload,
                self.timeout,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        content = _chat_text(body)
        rows = _extract_json_array(content)
        items = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            box = row.get("box") or row.get("bbox")
            if not isinstance(box, (list, tuple)) or len(box) != 4:
                continue
            items.append(
                {
                    "text": str(row.get("text") or "").strip(),
                    "box_pixel": [int(box[0]), int(box[1]), int(box[2]), int(box[3])],
                    "confidence": row.get("confidence"),
                }
            )
        return {
            "engine": self.name,
            "count": len(items),
            "items": items,
            "image_size": [image.width, image.height],
            "model": self.model,
        }


def build_ocr(settings: Settings) -> OcrEngine:
    """Build the engine named by ``settings.ocr_engine``."""
    name = settings.ocr_engine
    if name in {"", "tesseract"}:
        return TesseractOcr(command=settings.tesseract_cmd)
    if name == "ollama":
        return OllamaReadText(settings.ollama_url, settings.ollama_model, settings.ollama_timeout)
    if name == "vlm":
        return VlmBoxOcr(
            settings.vision_api_base,
            settings.vision_api_key,
            settings.vision_model,
            settings.vision_timeout_s,
        )
    raise OcrError(f"unknown OCR engine {name!r}; use tesseract, ollama, or vlm")


def _post_json(
    url: str,
    payload: dict[str, Any],
    timeout: int,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    request = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
    log.info("ocr http POST %s", url)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise OcrError("OCR endpoint did not return a JSON object")
    return parsed


def _chat_text(body: dict[str, Any]) -> str:
    choices = body.get("choices") or []
    if not choices:
        raise OcrError("VLM response has no choices")
    message = choices[0].get("message") or {}
    content = message.get("content") or ""
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content)


def _extract_json_array(text: str) -> list[Any]:
    """Pull the first JSON array out of a model reply. A lone object is wrapped."""
    start = text.find("[")
    end = text.rfind("]")
    blob = text
    if start != -1 and end != -1 and end > start:
        blob = text[start : end + 1]
    else:
        obj_start = text.find("{")
        obj_end = text.rfind("}")
        if obj_start != -1 and obj_end > obj_start:
            blob = text[obj_start : obj_end + 1]
    try:
        parsed = json.loads(blob)
    except json.JSONDecodeError as exc:
        raise OcrError(f"VLM OCR did not return JSON: {text[:300]}") from exc
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return parsed
    raise OcrError("VLM OCR JSON was not a list")
