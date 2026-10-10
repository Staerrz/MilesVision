"""One observe loop: instruction, capture, OCR, memory, stub reply, dry-run click.

There is no model client in the four repos that this loop should call.
``dsh-computer-use`` ``vision.js`` and ``ollama-vision-mcp`` both describe
images, but the layout asks for a stub reply. The stub quotes the instruction
and the OCR text, then the loop issues one ``mouse_click`` with ``dry_run=True``.

Run it on Windows with::

    python -m desktop_agent.agents.example_loop "Read the title of the front window"
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from desktop_agent.bridge.api import Bridge


def stub_reply(instruction: str, ocr_text: str, click: dict[str, int] | None) -> str:
    """Deterministic stand-in for a model reply. No network call."""
    preview = ocr_text.strip().replace("\n", " ")
    if len(preview) > 240:
        preview = preview[:240] + "..."
    if not preview:
        preview = "(no text)"
    where = "no text box; dry-run click at 1,1" if click is None else f"dry-run click at {click['x']},{click['y']}"
    return f"Instruction: {instruction}\nOCR: {preview}\nProposed action: {where}."


def _ocr_text(outcome: dict[str, Any]) -> str:
    items = outcome.get("items") or []
    return " ".join(str(item.get("text") or "") for item in items if isinstance(item, dict)).strip()


def _first_click(outcome: dict[str, Any]) -> dict[str, int] | None:
    items = outcome.get("items") or []
    if not items or not isinstance(items[0], dict):
        return None
    box = items[0].get("box_pixel")
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    return {"x": int((int(box[0]) + int(box[2])) / 2), "y": int((int(box[1]) + int(box[3])) / 2)}


def run_example(instruction: str, bridge: Bridge, *, session_id: str = "example") -> dict[str, Any]:
    """Run the example loop and return each bridge result.

    Capture or OCR failure is stored and the dry-run click still happens.
    The click is always ``dry_run=True``, including when screen control is off.
    """
    text = instruction.strip() or "Observe the screen."
    capture = bridge.screen_capture_full()
    if capture["ok"]:
        ocr = bridge.screen_ocr_full()
    else:
        ocr = {
            "ok": False,
            "tool": "screen_ocr_full",
            "timestamp": capture["timestamp"],
            "params": {},
            "outcome": {"ok": False, "error": "skipped because capture failed", "items": []},
            "event_id": None,
        }
    seen = _ocr_text(ocr.get("outcome") or {})
    point = _first_click(ocr.get("outcome") or {}) if ocr.get("ok") else None
    reply = stub_reply(text, seen, point)
    note = bridge.memory_add_event(
        "observation",
        {"instruction": text},
        {"ocr_text": seen, "capture_ok": capture["ok"], "reply": reply},
        kind="note",
        session_id=session_id,
        archive=True,
    )
    click_at = point or {"x": 1, "y": 1}
    action = bridge.mouse_click(click_at["x"], click_at["y"], dry_run=True, label="example")
    return {
        "instruction": text,
        "capture": capture,
        "ocr": ocr,
        "reply": reply,
        "memory": note,
        "action": action,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry. Prints the loop result as JSON."""
    parser = argparse.ArgumentParser(description="Run one desktop observe loop with a stub reply.")
    parser.add_argument("instruction", nargs="?", default="Observe the screen and report visible text.")
    args = parser.parse_args(argv)
    result = run_example(args.instruction, Bridge())
    print(json.dumps(_public(result), ensure_ascii=False, indent=2, default=str))
    return 0 if result["action"]["ok"] else 1


def _public(result: dict[str, Any]) -> dict[str, Any]:
    """Drop nothing structural; JSON-friendly copy of the loop result."""
    return {
        "instruction": result["instruction"],
        "reply": result["reply"],
        "capture": result["capture"],
        "ocr": result["ocr"],
        "memory": result["memory"],
        "action": result["action"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
