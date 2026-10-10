"""Process logging.

The format is the one ``ollama-vision-mcp`` ``server.py`` installs with
``logging.basicConfig``. Call ``configure_logging`` once at startup.
"""

from __future__ import annotations

import logging

_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def configure_logging(level: str = "INFO") -> logging.Logger:
    """Install the process log format and return the ``desktop_agent`` logger."""
    numeric = getattr(logging, str(level).upper(), logging.INFO)
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=numeric, format=_FORMAT)
    else:
        root.setLevel(numeric)
    logger = logging.getLogger("desktop_agent")
    logger.setLevel(numeric)
    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the ``desktop_agent`` hierarchy."""
    suffix = name.removeprefix("desktop_agent.")
    return logging.getLogger(f"desktop_agent.{suffix}")
