"""Start the PC control listener from the ``desktop_agent`` directory.

``python -m pc_control.server`` here loads
``desktop_agent/control/pc_control/server.py`` and calls its ``main``.
The same command from ``desktop_agent/control`` loads that file directly.
The listener stays on ``127.0.0.1:8770``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REAL_SERVER = Path(__file__).resolve().parents[1] / "control" / "pc_control" / "server.py"


def main() -> None:
    """Import the real server and stay up on its listener."""
    root = str(_REAL_SERVER.resolve().parents[3])
    if root not in sys.path:
        sys.path.insert(0, root)
    from desktop_agent.control.pc_control.server import main as serve

    serve()


if __name__ == "__main__":
    main()
