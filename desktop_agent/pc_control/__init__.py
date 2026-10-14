"""Launch shim for the PC control listener.

The implementation stays in ``desktop_agent/control/pc_control``. This package
exists so ``python -m pc_control.server`` from the ``desktop_agent`` directory
can find a module. It does not replace that implementation.
"""
