"""PC-Control: see and operate Windows apps without stealing focus or moving the mouse.

The ten tools live in ``server.TOOLS``. ``desktop_agent.bridge`` calls them.
``python -m pc_control.server`` from ``desktop_agent/control`` or from
``desktop_agent`` listens on ``127.0.0.1:8770/mcp``. The ``desktop_agent``
command is a shim; this package is the implementation.
"""
__version__ = "0.6.1"
