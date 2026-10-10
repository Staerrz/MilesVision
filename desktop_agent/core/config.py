"""Environment and JSON config lookup.

Rewritten from ``ollama-vision-mcp`` ``Config._get_config`` and from
``vision-primitives-mcp`` ``_env`` / ``_env_int``. Values resolve as
environment, then an optional JSON file, then the caller default.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def env_str(name: str, default: str = "") -> str:
    """Return a stripped environment variable, or ``default`` when unset."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip()


def env_int(name: str, default: int) -> int:
    """Return an integer environment variable, or ``default`` when invalid."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def env_bool(name: str, default: bool = False) -> bool:
    """Return a boolean environment variable.

    ``1``, ``true``, and ``yes`` are true. ``0``, ``false``, and ``no`` are
    false. Any other value keeps ``default``.
    """
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes"}:
        return True
    if value in {"0", "false", "no"}:
        return False
    return default


def lookup(key: str, default: Any, env_names: list[str], file_data: dict[str, Any]) -> Any:
    """Resolve one setting the way ``Config._get_config`` does.

    The first set environment variable wins. Types follow ``default``:
    bool, int, and list (comma-separated). The JSON file is next.
    """
    for name in env_names:
        raw = os.environ.get(name)
        if raw is None:
            continue
        if isinstance(default, bool):
            return raw.strip().lower() in {"1", "true", "yes"}
        if isinstance(default, int) and not isinstance(default, bool):
            try:
                return int(raw.strip())
            except ValueError:
                return default
        if isinstance(default, (list, tuple)):
            return [part.strip() for part in raw.split(",") if part.strip()]
        return raw.strip()
    if key in file_data:
        return file_data[key]
    return default


def load_json_config(path: str | None) -> dict[str, Any]:
    """Load a JSON object from ``path``. Missing or invalid files yield ``{}``."""
    if not path:
        return {}
    file_path = Path(path)
    if not file_path.is_file():
        return {}
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
