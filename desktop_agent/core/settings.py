"""Runtime settings for the desktop agent.

Fields come from the source projects, not a new configuration schema:

* ``ttl_ms``, ``allowed_apps`` — ``dsh-computer-use`` plugin config.
  ``allowed_apps`` is enforced on mouse, keyboard, and focus. ``ttl_ms`` is
  kept so the dsh default (30000) is visible. It is not enforced: this tree
  does not port the AX snapshot those actions were bound to.
* ``screen_control_allowed`` — ``VISION_ALLOW_SCREEN_CONTROL``
* ``max_model_side``, ``norm_size``, ``output_dir`` — vision-primitives image fit
* ``ollama_url``, ``ollama_model``, ``ollama_timeout``, ``log_level`` — ollama-vision
* ``vision_api_base``, ``vision_api_key``, ``vision_model``, ``vision_timeout_s``
  — vision-primitives VLM OCR swap
* ``memory_kb_db`` — MilesMemory ``MEMORY_KB_DB``

``dry_run`` and ``ocr_engine`` select behavior the layout asks for. OCR
defaults to Tesseract. ``ollama`` and ``vlm`` swap in the two source readers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from desktop_agent.core.config import load_json_config, lookup


def _find_config_file() -> str | None:
    """Find a JSON settings file the way ``Config._find_config_file`` does."""
    env_path = os.environ.get("DESKTOP_AGENT_CONFIG") or os.environ.get("OLLAMA_VISION_CONFIG")
    if env_path and Path(env_path).is_file():
        return env_path
    candidates = [
        Path.cwd() / "desktop-agent-config.json",
        Path.cwd() / "ollama-vision-config.json",
        Path.home() / ".ollama-vision-mcp" / "config.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


@dataclass
class Settings:
    """Resolved settings. Construct with ``Settings.load()`` for env files."""

    log_level: str = "INFO"
    output_dir: Path = field(default_factory=lambda: Path("generated"))
    session_db: Path = field(default_factory=lambda: Path("desktop_agent_session.db"))
    memory_kb_db: Path = field(default_factory=lambda: Path("memory_kb.db"))
    ocr_engine: str = "tesseract"
    tesseract_cmd: str | None = None
    ocr_language: str = "eng"
    max_model_side: int = 2600
    norm_size: int = 0
    screen_control_allowed: bool = False
    dry_run: bool = False
    ttl_ms: int = 30000
    allowed_apps: tuple[str, ...] = ()
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llava-phi3"
    ollama_timeout: int = 120
    vision_api_base: str = "https://api.xiaomimimo.com/v1"
    vision_api_key: str = ""
    vision_model: str = "mimo-v2.5"
    vision_timeout_s: int = 120
    agent_id: str = "desktop-agent"

    @classmethod
    def load(cls, config_path: str | None = None) -> Settings:
        """Load settings from the environment and an optional JSON file."""
        file_data = load_json_config(config_path if config_path is not None else _find_config_file())
        allowed = lookup("allowed_apps", [], ["DESKTOP_AGENT_ALLOWED_APPS"], file_data)
        if isinstance(allowed, str):
            allowed = [part.strip() for part in allowed.split(",") if part.strip()]
        tesseract_cmd = lookup("tesseract_cmd", "", ["TESSERACT_CMD"], file_data) or None
        return cls(
            log_level=str(lookup("log_level", "INFO", ["DESKTOP_AGENT_LOG_LEVEL", "OLLAMA_VISION_LOG_LEVEL"], file_data)),
            output_dir=Path(str(lookup("output_dir", "generated", ["VISION_OUTPUT_DIR", "DESKTOP_AGENT_OUTPUT_DIR"], file_data))),
            session_db=Path(str(lookup("session_db", "desktop_agent_session.db", ["DESKTOP_AGENT_SESSION_DB"], file_data))),
            memory_kb_db=Path(str(lookup("memory_kb_db", "memory_kb.db", ["MEMORY_KB_DB", "DESKTOP_AGENT_MEMORY_DB"], file_data))),
            ocr_engine=str(lookup("ocr_engine", "tesseract", ["DESKTOP_AGENT_OCR"], file_data)).strip().lower(),
            tesseract_cmd=tesseract_cmd,
            ocr_language=str(lookup("ocr_language", "eng", ["DESKTOP_AGENT_OCR_LANG"], file_data)),
            max_model_side=int(lookup("max_model_side", 2600, ["VISION_MAX_MODEL_SIDE"], file_data)),
            norm_size=int(lookup("norm_size", 0, ["VISION_NORM_SIZE"], file_data)),
            screen_control_allowed=bool(
                lookup("screen_control_allowed", False, ["VISION_ALLOW_SCREEN_CONTROL"], file_data)
            ),
            dry_run=bool(lookup("dry_run", False, ["DESKTOP_AGENT_DRY_RUN"], file_data)),
            ttl_ms=int(lookup("ttl_ms", 30000, ["DESKTOP_AGENT_TTL_MS"], file_data)),
            allowed_apps=tuple(allowed),
            ollama_url=str(lookup("ollama_url", "http://localhost:11434", ["OLLAMA_VISION_OLLAMA_URL"], file_data)),
            ollama_model=str(lookup("default_model", "llava-phi3", ["OLLAMA_VISION_DEFAULT_MODEL"], file_data)),
            ollama_timeout=int(lookup("timeout", 120, ["OLLAMA_VISION_TIMEOUT"], file_data)),
            vision_api_base=str(lookup("vision_api_base", "https://api.xiaomimimo.com/v1", ["VISION_API_BASE"], file_data)).rstrip("/"),
            vision_api_key=str(lookup("vision_api_key", "", ["VISION_API_KEY"], file_data)),
            vision_model=str(lookup("vision_model", "mimo-v2.5", ["VISION_MODEL"], file_data)),
            vision_timeout_s=int(lookup("vision_timeout_s", 120, ["VISION_TIMEOUT_S"], file_data)),
            agent_id=str(lookup("agent_id", "desktop-agent", ["DESKTOP_AGENT_ID"], file_data)),
        )
