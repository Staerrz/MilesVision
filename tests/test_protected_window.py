"""The person at the PC approves a protected window. The remote client cannot."""
import inspect

from desktop_agent.bridge.api import pc_click, pc_key, pc_look, pc_type
from desktop_agent.bridge.pc import SOURCE_NAMES
from desktop_agent.control.pc_control import local_approval, policy
from desktop_agent.control.pc_control.server import ToolError


def test_github_desktop_is_protected():
    assert policy.blocked_category("githubdesktop") == "development with credentials"
    try:
        policy.check_window("auto", "githubdesktop", "GitHub Desktop", False, set(), confirm=False, hwnd=1)
    except policy.NeedsPermission as exc:
        assert "PROTECTED" in str(exc)
    else:
        raise AssertionError("protected window was not refused")


def test_unprotected_does_not_ask():
    calls = []
    local_approval.decide(None, "look", 1, ask_fn=lambda *args: calls.append(args) or "allow")
    assert calls == []


def test_local_grant_is_one_action_one_window_one_use():
    calls = []

    def ask(action, hwnd, category):
        calls.append((action, hwnd, category))
        local_approval._store(action, hwnd)
        return "allow"

    local_approval.decide("development with credentials", "look", 10, ask_fn=ask, take_fn=local_approval.take)
    assert calls == [("look", 10, "development with credentials")]
    calls.clear()
    local_approval.decide("development with credentials", "look", 10, ask_fn=ask, take_fn=local_approval.take)
    assert calls == [("look", 10, "development with credentials")]


def test_deny_and_timeout_fail_closed():
    for answer in ("deny", "timeout"):
        try:
            local_approval.decide(
                "development with credentials",
                "read",
                11,
                ask_fn=lambda *args: answer,
                take_fn=lambda *args: False,
            )
        except ToolError as exc:
            assert "person at this PC" in str(exc)
            assert "Do you allow" not in str(exc)
        else:
            raise AssertionError(answer)


def test_a_grant_for_look_does_not_cover_click():
    local_approval._store("look", 12)
    try:
        local_approval.decide(
            "development with credentials",
            "click",
            12,
            ask_fn=lambda *args: "deny",
            take_fn=local_approval.take,
        )
    except ToolError:
        return
    raise AssertionError("click reused a look grant")


def test_no_remote_approve_tool_and_no_confirm_argument():
    assert "approve" not in SOURCE_NAMES
    for fn in (pc_look, pc_click, pc_type, pc_key):
        assert "confirm" not in inspect.signature(fn).parameters


def test_message_box_flags_default_to_no_and_stay_on_top():
    assert local_approval._BOX_FLAGS & 0x100
    assert local_approval._BOX_FLAGS & 0x40000
