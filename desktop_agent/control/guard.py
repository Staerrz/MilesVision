"""Action gate: allowlist, dangerous labels, password fields, dry-run.

Rewritten from ``dsh-computer-use`` ``guard.js`` and from
``vision-primitives-mcp`` ``_require_screen_control``.

* ``allowed_apps`` empty means unrestricted. A non-empty list rejects an
  action whose ``app_name`` is missing or outside the list.
* Labels matching the dangerous-word list do not run unless ``approved`` is
  true. ``dry_run`` still records the plan and does not touch the desktop.
* ``AXSecureTextField`` and ``AXPasswordField`` never accept ``type_text``.
* Mouse, keyboard, focus, launch, and URL actions require
  ``VISION_ALLOW_SCREEN_CONTROL`` unless ``dry_run`` is set. The vision
  source defaults that switch to off.
"""

from __future__ import annotations

import re
from typing import Any

from desktop_agent.core.logging import get_logger
from desktop_agent.core.settings import Settings

log = get_logger("control")

DANGEROUS_PATTERNS = [
    re.compile(r"删除|移除|清空|清倒|格式化|卸载|永久"),
    re.compile(r"支付|付款|购买|下单|结账|转账|汇款|提交订单|确认交易"),
    re.compile(r"退出登录|注销|登出"),
]

PASSWORD_ROLES = frozenset({"AXSecureTextField", "AXPasswordField"})

TYPE_ACTIONS = frozenset({"type_text", "keyboard_type"})


class ActionError(RuntimeError):
    """The action was rejected before it ran."""


def is_dangerous_label(label: str | None) -> bool:
    """True when ``label`` matches the dsh dangerous-word list."""
    text = str(label or "")
    return any(pattern.search(text) for pattern in DANGEROUS_PATTERNS)


def effective_dry_run(settings: Settings, dry_run: bool | None) -> bool:
    """Per-call ``dry_run`` wins. ``None`` uses ``settings.dry_run``."""
    if dry_run is None:
        return settings.dry_run
    return dry_run


def gate(
    name: str,
    params: dict[str, Any],
    settings: Settings,
    *,
    dry_run: bool | None,
    label: str | None = None,
    field_role: str | None = None,
    app_name: str | None = None,
    approved: bool = False,
    check_allowlist: bool = True,
) -> dict[str, Any] | None:
    """Return a finished outcome when the action must not execute.

    ``None`` means the caller should perform the action.
    ``check_allowlist`` is false for ``launch_app`` and ``open_url``.
    ``dsh-computer-use`` does not apply ``allowedApps`` to ``app_launch``.
    """
    planned = effective_dry_run(settings, dry_run)
    if field_role in PASSWORD_ROLES and name in TYPE_ACTIONS:
        return _refuse(
            name,
            params,
            "Password field refused. AXSecureTextField and AXPasswordField "
            "do not accept automated typing.",
        )
    if check_allowlist and settings.allowed_apps:
        if not app_name or app_name not in settings.allowed_apps:
            listed = " / ".join(settings.allowed_apps)
            return _refuse(
                name,
                params,
                f'Allowlist refused "{app_name or ""}". Allowed: {listed}.',
            )
    if is_dangerous_label(label) and not approved:
        if planned:
            return _planned(name, params, "dangerous label; dry_run only")
        return _refuse(
            name,
            params,
            f'Dangerous label "{label}" was not approved. Pass approved=True or dry_run=True.',
        )
    if not planned and not settings.screen_control_allowed:
        return _refuse(
            name,
            params,
            "Screen control is off. Set VISION_ALLOW_SCREEN_CONTROL=1. This call was not executed.",
        )
    if planned:
        return _planned(name, params, "dry_run")
    return None


def log_action(name: str, params: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any]:
    """Log one action and return ``outcome``. Called for executed and refused actions."""
    log.info(
        "action %s ok=%s dry_run=%s params=%s",
        name,
        outcome.get("ok"),
        outcome.get("dry_run", False),
        params,
    )
    return outcome


def _refuse(name: str, params: dict[str, Any], reason: str) -> dict[str, Any]:
    return log_action(
        name,
        params,
        {"ok": False, "executed": False, "dry_run": False, "action": name, "reason": reason, "plan": params},
    )


def _planned(name: str, params: dict[str, Any], reason: str) -> dict[str, Any]:
    return log_action(
        name,
        params,
        {"ok": True, "executed": False, "dry_run": True, "action": name, "reason": reason, "plan": params},
    )
